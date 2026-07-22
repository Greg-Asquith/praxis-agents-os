# apps/api/services/integrations/context/resolve_active_context.py

"""Resolve persisted integration context into run-scoped resources."""

import logging
from collections.abc import Sequence
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
from services.integrations.context.schemas import ActiveContextSelectionValue
from services.integrations.domain import (
    CONNECTION_STATUS_ACTIVE,
    CONNECTION_STATUS_DEGRADED,
    CONNECTION_STATUS_ERROR,
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

    selection, source = await _load_selection(db, run=root_run, workspace_id=workspace.id)
    if selection is None:
        return EMPTY_ACTIVE_CONTEXT

    resource_ids, group_id, group_name, dangling = await _expand_selection(
        db,
        selection=selection,
        workspace_id=workspace.id,
    )
    if dangling is not None:
        return ResolvedActiveContext(
            source=source,
            selection_kind=selection.type,
            group_id=group_id,
            group_name=group_name,
            unavailable=(dangling,),
        )

    entries, unavailable = await _resolve_resources(
        db,
        resource_ids=resource_ids,
        user_id=user.id,
        workspace_id=workspace.id,
    )
    return ResolvedActiveContext(
        source=source,
        selection_kind=selection.type,
        group_id=group_id,
        group_name=group_name,
        entries=tuple(
            sorted(entries, key=lambda item: (item.provider_key, item.display_name.casefold()))
        ),
        unavailable=tuple(unavailable),
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
) -> tuple[ActiveContextSelectionValue | None, str | None]:
    if run.trigger == RUN_TRIGGER_INTERACTIVE:
        row = await db.scalar(
            select(ActiveContextSelection).where(
                ActiveContextSelection.conversation_id == run.conversation_id,
                ActiveContextSelection.workspace_id == workspace_id,
            )
        )
        return (
            ActiveContextSelectionValue.from_selection(row) if row is not None else None,
            "conversation",
        )
    if run.trigger != RUN_TRIGGER_SCHEDULED:
        return None, None

    saved = await db.scalar(
        select(AgentSchedule.active_context)
        .join(AgentScheduleRun, AgentScheduleRun.schedule_id == AgentSchedule.id)
        .where(
            AgentScheduleRun.agent_run_id == run.id,
            AgentScheduleRun.workspace_id == workspace_id,
        )
    )
    if saved is None:
        return None, "schedule"
    try:
        return ActiveContextSelectionValue.model_validate(saved), "schedule"
    except (ValidationError, TypeError, ValueError):
        logger.warning(
            "Ignoring malformed scheduled active context",
            extra={"agent_run_id": str(run.id)},
        )
        return None, "schedule"


async def _expand_selection(
    db: AsyncSession,
    *,
    selection: ActiveContextSelectionValue,
    workspace_id: UUID,
) -> tuple[list[UUID], UUID | None, str | None, UnavailableContextEntry | None]:
    if selection.integration_resource_id is not None:
        return [selection.integration_resource_id], None, None, None

    group_id = selection.context_group_id
    if group_id is None:
        return [], None, None, _dangling_entry()
    group = await db.get(IntegrationContextGroup, group_id)
    if group is None or group.workspace_id != workspace_id or group.deleted:
        return [], group_id, None, _dangling_entry()
    resource_ids = list(
        await db.scalars(
            select(IntegrationContextGroupMember.integration_resource_id).where(
                IntegrationContextGroupMember.group_id == group.id
            )
        )
    )
    return resource_ids, group.id, group.name, None


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
