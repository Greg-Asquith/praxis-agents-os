# apps/api/services/audit_events/queries.py

"""Read access to the audit log for routes to call later."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import String, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from models.audit_event import AuditEvent
from services.audit_events.enums import AuditAction, AuditResourceType, AuditStatus
from utils.pagination import paginate


def _filtered_select(
    base,
    *,
    workspace_id: UUID | str | None,
    resource_type: AuditResourceType | None,
    resource_id: str | None,
    actor_user_id: UUID | str | None,
    action: AuditAction | None,
    status: AuditStatus | None,
    tool_name: str | None,
    tool_provider: str | None,
    occurred_after: datetime | None,
    occurred_before: datetime | None,
    event_type=AuditEvent,
):
    """Apply the shared audit-log filters to a select() statement."""
    if workspace_id is not None:
        base = base.where(event_type.workspace_id == workspace_id)
    if resource_type is not None:
        base = base.where(event_type.resource_type == resource_type)
    if resource_id is not None:
        base = base.where(event_type.resource_id == resource_id)
    if actor_user_id is not None:
        base = base.where(event_type.actor_user_id == actor_user_id)
    if action is not None:
        base = base.where(event_type.action == action)
    if status is not None:
        base = base.where(event_type.status == status)
    if tool_name is not None:
        base = base.where(event_type.tool_name == tool_name)
    if tool_provider is not None:
        base = base.where(event_type.tool_provider == tool_provider)
    if occurred_after is not None:
        base = base.where(event_type.occurred_at >= occurred_after)
    if occurred_before is not None:
        base = base.where(event_type.occurred_at < occurred_before)
    return base


async def list_audit_events(
    db: AsyncSession,
    *,
    workspace_id: UUID | str | None = None,
    resource_type: AuditResourceType | None = None,
    resource_id: str | None = None,
    actor_user_id: UUID | str | None = None,
    action: AuditAction | None = None,
    status: AuditStatus | None = None,
    tool_name: str | None = None,
    tool_provider: str | None = None,
    occurred_after: datetime | None = None,
    occurred_before: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AuditEvent]:
    """Return audit events newest-first, narrowed by the given filters."""
    events, _total = await list_audit_events_page(
        db,
        workspace_id=workspace_id,
        resource_type=resource_type,
        resource_id=resource_id,
        actor_user_id=actor_user_id,
        action=action,
        status=status,
        tool_name=tool_name,
        tool_provider=tool_provider,
        occurred_after=occurred_after,
        occurred_before=occurred_before,
        limit=limit,
        offset=offset,
    )
    return events


async def list_audit_events_page(
    db: AsyncSession,
    *,
    workspace_id: UUID | str | None = None,
    resource_type: AuditResourceType | None = None,
    resource_id: str | None = None,
    actor_user_id: UUID | str | None = None,
    action: AuditAction | None = None,
    status: AuditStatus | None = None,
    tool_name: str | None = None,
    tool_provider: str | None = None,
    occurred_after: datetime | None = None,
    occurred_before: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AuditEvent], int]:
    """Return audit events and the total count for the same filters."""
    stmt = _filtered_select(
        select(AuditEvent),
        workspace_id=workspace_id,
        resource_type=resource_type,
        resource_id=resource_id,
        actor_user_id=actor_user_id,
        action=action,
        status=status,
        tool_name=tool_name,
        tool_provider=tool_provider,
        occurred_after=occurred_after,
        occurred_before=occurred_before,
    )
    return await paginate(db, stmt, AuditEvent.occurred_at.desc(), limit=limit, offset=offset)


async def list_rolled_up_audit_events_page(
    db: AsyncSession,
    *,
    workspace_id: UUID | str,
    resource_type: AuditResourceType | None = None,
    resource_id: str | None = None,
    actor_user_id: UUID | str | None = None,
    action: AuditAction | None = None,
    status: AuditStatus | None = None,
    tool_name: str | None = None,
    tool_provider: str | None = None,
    occurred_after: datetime | None = None,
    occurred_before: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[tuple[AuditEvent, UUID, str, str]], int]:
    """Page logical tool invocations after provider-event roll-up."""
    is_tool_call = AuditEvent.resource_type == AuditResourceType.TOOL_CALL
    is_integration_resource = AuditEvent.resource_type == AuditResourceType.INTEGRATION_RESOURCE
    run_id = AuditEvent.details["run_id"].as_string()
    integration_tool_call_id = AuditEvent.details["tool_call_id"].as_string()
    correlation_tool_call_id = case(
        (is_tool_call, AuditEvent.resource_id),
        (is_integration_resource, integration_tool_call_id),
        else_=None,
    )
    has_tool_correlation = (
        run_id.is_not(None)
        & (run_id != "")
        & correlation_tool_call_id.is_not(None)
        & (correlation_tool_call_id != "")
    )
    integration_with_tool_call = is_integration_resource & has_tool_correlation
    group_key = case(
        (
            has_tool_correlation,
            func.concat(
                "tool:",
                func.length(run_id),
                ":",
                run_id,
                ":",
                func.length(correlation_tool_call_id),
                ":",
                correlation_tool_call_id,
            ),
        ),
        else_=func.concat("event:", cast(AuditEvent.id, String)),
    )
    is_pending = AuditEvent.status == AuditStatus.PENDING
    display_priority = case(
        (
            is_tool_call & ~is_pending,
            4,
        ),
        (is_tool_call, 3),
        (integration_with_tool_call & ~is_pending, 2),
        else_=1,
    )
    outcome_priority = case(
        (integration_with_tool_call & ~is_pending, 4),
        (
            is_tool_call & ~is_pending,
            3,
        ),
        (integration_with_tool_call, 2),
        else_=1,
    )
    detail_priority = case(
        (integration_with_tool_call & ~is_pending, 4),
        (integration_with_tool_call, 3),
        (
            is_tool_call & ~is_pending,
            2,
        ),
        else_=1,
    )
    ranked = (
        select(
            AuditEvent,
            group_key.label("group_key"),
            func.row_number()
            .over(
                partition_by=group_key,
                order_by=(
                    display_priority.desc(),
                    AuditEvent.occurred_at.desc(),
                    AuditEvent.id.desc(),
                ),
            )
            .label("display_rank"),
            func.row_number()
            .over(
                partition_by=group_key,
                order_by=(
                    outcome_priority.desc(),
                    AuditEvent.occurred_at.desc(),
                    AuditEvent.id.desc(),
                ),
            )
            .label("outcome_rank"),
            func.row_number()
            .over(
                partition_by=group_key,
                order_by=(
                    detail_priority.desc(),
                    AuditEvent.occurred_at.desc(),
                    AuditEvent.id.desc(),
                ),
            )
            .label("detail_rank"),
        )
        .where(AuditEvent.workspace_id == workspace_id)
        .cte("ranked_audit_events")
    )
    qualifying_groups = _filtered_select(
        select(ranked.c.group_key).distinct(),
        workspace_id=None,
        resource_type=resource_type,
        resource_id=resource_id,
        actor_user_id=actor_user_id,
        action=action,
        status=None,
        tool_name=tool_name,
        tool_provider=tool_provider,
        occurred_after=occurred_after,
        occurred_before=occurred_before,
        event_type=ranked.c,
    ).cte("qualifying_audit_event_groups")
    qualified_ranked = (
        select(ranked)
        .join(qualifying_groups, qualifying_groups.c.group_key == ranked.c.group_key)
        .cte("qualified_ranked_audit_events")
    )
    display_rows = select(qualified_ranked).where(qualified_ranked.c.display_rank == 1).subquery()
    detail_rows = (
        select(
            qualified_ranked.c.group_key,
            qualified_ranked.c.id.label("detail_event_id"),
        )
        .where(qualified_ranked.c.detail_rank == 1)
        .subquery()
    )
    outcome_rows = (
        select(
            qualified_ranked.c.group_key,
            qualified_ranked.c.status.label("effective_status"),
            qualified_ranked.c.summary.label("effective_summary"),
        )
        .where(qualified_ranked.c.outcome_rank == 1)
        .subquery()
    )
    display_event = aliased(AuditEvent, display_rows)
    stmt = select(
        display_event,
        detail_rows.c.detail_event_id,
        outcome_rows.c.effective_status,
        outcome_rows.c.effective_summary,
    ).join(detail_rows, detail_rows.c.group_key == display_rows.c.group_key)
    stmt = stmt.join(outcome_rows, outcome_rows.c.group_key == display_rows.c.group_key)
    if status is not None:
        stmt = stmt.where(outcome_rows.c.effective_status == status)
    total = int(
        (
            await db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
        ).scalar_one()
    )
    rows = (
        await db.execute(
            stmt.order_by(display_event.occurred_at.desc(), display_event.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return [
        (event, detail_event_id, effective_status, effective_summary)
        for event, detail_event_id, effective_status, effective_summary in rows
    ], total


async def get_audit_event(
    db: AsyncSession,
    *,
    event_id: UUID | str,
    workspace_id: UUID | str | None = None,
) -> AuditEvent | None:
    """Fetch a single audit event by id, optionally scoped to a workspace."""
    stmt = select(AuditEvent).where(AuditEvent.id == event_id)
    if workspace_id is not None:
        stmt = stmt.where(AuditEvent.workspace_id == workspace_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
