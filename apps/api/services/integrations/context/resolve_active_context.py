# apps/api/services/integrations/context/resolve_active_context.py

"""Resolve persisted integration context into run-scoped resources."""

import logging
from collections.abc import Sequence
from typing import Literal
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import AgentSchedule, AgentScheduleRun
from models.agent_run import AgentRun
from models.integration_context import (
    ActiveContextSelection,
    IntegrationContextGroup,
    IntegrationContextGroupMember,
)
from models.integrations import IntegrationConnection, IntegrationResource
from models.user import User
from models.workspace import Workspace
from services.agent_runs.domain import (
    RUN_TRIGGER_DELEGATED,
    RUN_TRIGGER_INTERACTIVE,
    RUN_TRIGGER_SCHEDULED,
)
from services.integrations.context.domain import (
    EMPTY_ACTIVE_CONTEXT,
    ResolvedActiveContext,
    ResolvedContextEntry,
    UnavailableContextEntry,
)
from services.integrations.context.schemas import (
    MAX_ACTIVE_CONTEXT_TARGETS,
    ActiveContextSelectionValue,
    ActiveContextTargets,
)
from services.integrations.domain import (
    CONNECTION_STATUS_ACTIVE,
    CONNECTION_STATUS_DEGRADED,
    CONNECTION_STATUS_ERROR,
    CONNECTION_STATUS_NEEDS_CREDENTIAL,
    CONNECTION_STATUS_NEEDS_REAUTH,
    CONNECTION_STATUS_REVOKED,
)

logger = logging.getLogger(__name__)


async def resolve_active_context(
    db: AsyncSession,
    *,
    run: AgentRun,
    user: User,
    workspace: Workspace,
) -> ResolvedActiveContext:
    """Resolve the root principal's saved selection without failing a run."""
    root_run = await _load_root_run(db, run=run, workspace_id=workspace.id)
    if root_run is None:
        return EMPTY_ACTIVE_CONTEXT

    selections, source = await _load_selection(db, run=root_run, workspace_id=workspace.id)
    if not selections:
        return EMPTY_ACTIVE_CONTEXT

    return await resolve_active_context_targets(
        db,
        selections=selections,
        user=user,
        workspace=workspace,
        source=source,
    )


async def resolve_active_context_targets(
    db: AsyncSession,
    *,
    selections: Sequence[ActiveContextSelectionValue],
    user: User,
    workspace: Workspace,
    source: Literal["conversation", "schedule"] | None = None,
) -> ResolvedActiveContext:
    """Resolve validated targets with the runtime visibility and degradation rules."""
    if not selections:
        return EMPTY_ACTIVE_CONTEXT

    resource_ids, groups, dangling = await _expand_selection(
        db,
        selections=selections,
        workspace_id=workspace.id,
    )
    entries, unavailable = await _resolve_resources(
        db,
        resource_ids=resource_ids,
        user_id=user.id,
        workspace_id=workspace.id,
    )
    return ResolvedActiveContext(
        source=source,
        groups=groups,
        entries=tuple(
            sorted(entries, key=lambda item: (item.provider_key, item.display_name.casefold()))
        ),
        unavailable=tuple(
            sorted(
                (*dangling, *unavailable),
                key=lambda item: (item.provider_key, item.display_name.casefold(), item.reason),
            )
        ),
    )


async def _load_root_run(
    db: AsyncSession,
    *,
    run: AgentRun,
    workspace_id: UUID,
) -> AgentRun | None:
    current = run
    remaining = max(int(run.delegation_depth or 0), 0)
    while current.trigger == RUN_TRIGGER_DELEGATED:
        if current.parent_run_id is None or remaining == 0:
            logger.warning(
                "Delegated run has no resolvable root for active context",
                extra={"agent_run_id": str(run.id)},
            )
            return None
        parent = await db.get(AgentRun, current.parent_run_id)
        if parent is None or parent.workspace_id != workspace_id:
            logger.warning(
                "Delegated run parent is unavailable for active context",
                extra={"agent_run_id": str(run.id)},
            )
            return None
        current = parent
        remaining -= 1
    return current


async def _load_selection(
    db: AsyncSession,
    *,
    run: AgentRun,
    workspace_id: UUID,
) -> tuple[list[ActiveContextSelectionValue], str | None]:
    if run.trigger == RUN_TRIGGER_INTERACTIVE:
        rows = list(
            await db.scalars(
                select(ActiveContextSelection).where(
                    ActiveContextSelection.conversation_id == run.conversation_id,
                    ActiveContextSelection.workspace_id == workspace_id,
                )
            )
        )
        targets = [ActiveContextSelectionValue.from_selection(row) for row in rows]
        return sorted(
            targets,
            key=lambda target: (
                target.type,
                str(target.integration_resource_id or target.context_group_id),
            ),
        ), "conversation"
    if run.trigger != RUN_TRIGGER_SCHEDULED:
        return [], None

    saved = await db.scalar(
        select(AgentSchedule.active_context)
        .join(AgentScheduleRun, AgentScheduleRun.schedule_id == AgentSchedule.id)
        .where(
            AgentScheduleRun.agent_run_id == run.id,
            AgentScheduleRun.workspace_id == workspace_id,
        )
    )
    if saved is None:
        return [], "schedule"
    try:
        return ActiveContextTargets.model_validate(saved).targets, "schedule"
    except (ValidationError, TypeError, ValueError):
        logger.warning(
            "Ignoring malformed scheduled active context",
            extra={"agent_run_id": str(run.id)},
        )
        return [], "schedule"


async def _expand_selection(
    db: AsyncSession,
    *,
    selections: Sequence[ActiveContextSelectionValue],
    workspace_id: UUID,
) -> tuple[list[UUID], tuple[tuple[UUID, str], ...], tuple[UnavailableContextEntry, ...]]:
    resource_ids = [
        resource_id
        for selection in selections
        if (resource_id := selection.integration_resource_id) is not None
    ]
    group_ids = [
        group_id for selection in selections if (group_id := selection.context_group_id) is not None
    ]
    resource_ids = list(dict.fromkeys(resource_ids))
    if not group_ids or len(resource_ids) >= MAX_ACTIVE_CONTEXT_TARGETS:
        return resource_ids[:MAX_ACTIVE_CONTEXT_TARGETS], (), ()

    loaded_groups = (
        await db.execute(
            select(IntegrationContextGroup.id, IntegrationContextGroup.name).where(
                IntegrationContextGroup.id.in_(group_ids),
                IntegrationContextGroup.workspace_id == workspace_id,
                IntegrationContextGroup.deleted.is_(False),
            )
        )
    ).all()
    groups_by_id = dict(loaded_groups)
    groups = [
        (group_id, group_name)
        for group_id in group_ids
        if (group_name := groups_by_id.get(group_id)) is not None
    ]
    dangling = [_dangling_entry() for group_id in group_ids if group_id not in groups_by_id]
    if groups:
        remaining = MAX_ACTIVE_CONTEXT_TARGETS - len(resource_ids)
        member_statement = (
            select(IntegrationContextGroupMember.integration_resource_id)
            .distinct()
            .where(
                IntegrationContextGroupMember.group_id.in_(
                    [group_id for group_id, _name in groups]
                ),
                IntegrationContextGroupMember.integration_resource_id.not_in(resource_ids),
            )
            .order_by(IntegrationContextGroupMember.integration_resource_id)
            .limit(remaining)
        )
        resource_ids.extend(await db.scalars(member_statement))
    return resource_ids, tuple(groups), tuple(dangling)


async def _resolve_resources(
    db: AsyncSession,
    *,
    resource_ids: Sequence[UUID],
    user_id: UUID,
    workspace_id: UUID,
) -> tuple[list[ResolvedContextEntry], list[UnavailableContextEntry]]:
    if not resource_ids:
        return [], []
    rows = (
        await db.execute(
            select(IntegrationResource, IntegrationConnection)
            .join(
                IntegrationConnection, IntegrationConnection.id == IntegrationResource.connection_id
            )
            .where(
                IntegrationResource.id.in_(set(resource_ids)),
                or_(
                    IntegrationConnection.owner_workspace_id == workspace_id,
                    IntegrationConnection.owner_user_id == user_id,
                ),
            )
        )
    ).all()
    by_id = {resource.id: (resource, connection) for resource, connection in rows}
    usable: list[tuple[ResolvedContextEntry, IntegrationConnection]] = []
    unavailable: list[UnavailableContextEntry] = []

    for resource_id in resource_ids:
        pair = by_id.get(resource_id)
        if pair is None:
            unavailable.append(_dangling_entry())
            continue
        resource, connection = pair
        reason = _unavailable_reason(resource, connection)
        if reason is not None:
            unavailable.append(
                UnavailableContextEntry(
                    display_name=resource.display_name,
                    provider_key=connection.provider_key,
                    reason=reason,
                )
            )
            continue
        usable.append(
            (
                ResolvedContextEntry(
                    integration_resource_id=resource.id,
                    provider_key=connection.provider_key,
                    resource_type=resource.resource_type,
                    external_id=resource.external_id,
                    display_name=resource.display_name,
                    connection_id=connection.id,
                    connection_label=connection.label,
                    connection_status=connection.status,
                    write_allowed=bool(resource.writable and resource.permissions_metadata),
                    is_personal=(
                        connection.owner_user_id is not None
                        and connection.owner_workspace_id is None
                    ),
                    permissions_metadata=dict(resource.permissions_metadata or {}),
                ),
                connection,
            )
        )

    deduped: dict[tuple[str, str], tuple[ResolvedContextEntry, IntegrationConnection]] = {}
    for entry, connection in usable:
        key = (entry.provider_key, entry.external_id)
        current = deduped.get(key)
        if current is None or _connection_rank(connection) > _connection_rank(current[1]):
            deduped[key] = (entry, connection)
    return [entry for entry, _connection in deduped.values()], unavailable


def _unavailable_reason(resource: IntegrationResource, connection: IntegrationConnection):
    if resource.deleted or resource.availability == "removed" or resource.removed_at is not None:
        return "resource_removed"
    if not resource.enabled:
        return "resource_disabled"
    if connection.deleted or connection.status == CONNECTION_STATUS_REVOKED:
        return "connection_revoked"
    if connection.status == CONNECTION_STATUS_NEEDS_REAUTH:
        return "connection_needs_reauth"
    if connection.status == CONNECTION_STATUS_NEEDS_CREDENTIAL:
        return "connection_needs_credential"
    if connection.status == CONNECTION_STATUS_ERROR:
        return "connection_error"
    if connection.status not in {CONNECTION_STATUS_ACTIVE, CONNECTION_STATUS_DEGRADED}:
        return "connection_inactive"
    return None


def _connection_rank(connection: IntegrationConnection) -> tuple[int, object, str]:
    return (
        1 if connection.status == CONNECTION_STATUS_ACTIVE else 0,
        connection.created_at,
        str(connection.id),
    )


def _dangling_entry() -> UnavailableContextEntry:
    return UnavailableContextEntry(
        display_name="Selected context",
        provider_key="unknown",
        reason="dangling",
    )
