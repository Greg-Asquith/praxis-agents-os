# apps/api/services/audit_events/queries.py

"""Read access to the audit log for routes to call later."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import String, and_, case, cast, func, select, true, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from models.audit_event import AuditEvent
from services.audit_events.enums import AuditAction, AuditResourceType, AuditStatus
from utils.pagination import paginate


def _audit_rollup_group_key(event_type=AuditEvent):
    """Return the trigger-aligned logical identity for an audit event relation."""
    run_id = event_type.audit_rollup_run_id
    tool_call_id = event_type.audit_rollup_tool_call_id
    has_tool_correlation = run_id.is_not(None) & tool_call_id.is_not(None)
    return case(
        (
            has_tool_correlation,
            func.concat(
                "tool:",
                func.length(run_id),
                ":",
                run_id,
                ":",
                func.length(tool_call_id),
                ":",
                tool_call_id,
            ),
        ),
        else_=func.concat("event:", cast(event_type.id, String)),
    )


def _has_non_status_audit_filter(
    *,
    resource_type: AuditResourceType | None,
    resource_id: str | None,
    actor_user_id: UUID | str | None,
    action: AuditAction | None,
    tool_name: str | None,
    tool_provider: str | None,
    occurred_after: datetime | None,
    occurred_before: datetime | None,
) -> bool:
    return any(
        value is not None
        for value in (
            resource_type,
            resource_id,
            actor_user_id,
            action,
            tool_name,
            tool_provider,
            occurred_after,
            occurred_before,
        )
    )


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


def _rolled_up_audit_events_statement(
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
):
    """Build the logical audit-event query before count and pagination."""
    if _has_non_status_audit_filter(
        resource_type=resource_type,
        resource_id=resource_id,
        actor_user_id=actor_user_id,
        action=action,
        tool_name=tool_name,
        tool_provider=tool_provider,
        occurred_after=occurred_after,
        occurred_before=occurred_before,
    ):
        matching_members = _filtered_select(
            select(
                AuditEvent.id,
                AuditEvent.audit_rollup_run_id,
                AuditEvent.audit_rollup_tool_call_id,
            ),
            workspace_id=workspace_id,
            resource_type=resource_type,
            resource_id=resource_id,
            actor_user_id=actor_user_id,
            action=action,
            status=None,
            tool_name=tool_name,
            tool_provider=tool_provider,
            occurred_after=occurred_after,
            occurred_before=occurred_before,
        ).cte("matching_audit_event_members")
        qualifying_correlations = (
            select(
                matching_members.c.audit_rollup_run_id,
                matching_members.c.audit_rollup_tool_call_id,
            )
            .where(
                matching_members.c.audit_rollup_run_id.is_not(None),
                matching_members.c.audit_rollup_tool_call_id.is_not(None),
            )
            .distinct()
            .cte("qualifying_audit_event_correlations")
        )
        qualifying_standalone_ids = (
            select(matching_members.c.id)
            .where(
                (matching_members.c.audit_rollup_run_id.is_(None))
                | (matching_members.c.audit_rollup_tool_call_id.is_(None))
            )
            .cte("qualifying_standalone_audit_events")
        )
        correlated_members = (
            select(AuditEvent)
            .join(
                qualifying_correlations,
                and_(
                    AuditEvent.workspace_id == workspace_id,
                    AuditEvent.audit_rollup_run_id == qualifying_correlations.c.audit_rollup_run_id,
                    AuditEvent.audit_rollup_tool_call_id
                    == qualifying_correlations.c.audit_rollup_tool_call_id,
                ),
            )
            .where(
                AuditEvent.audit_rollup_run_id.is_not(None),
                AuditEvent.audit_rollup_tool_call_id.is_not(None),
            )
        )
        standalone_members = select(AuditEvent).join(
            qualifying_standalone_ids,
            and_(
                AuditEvent.workspace_id == workspace_id,
                AuditEvent.id == qualifying_standalone_ids.c.id,
            ),
        )
        ranking_source = (
            union_all(correlated_members, standalone_members)
            .cte("complete_qualified_audit_event_members")
            .c
        )
        ranking_scope = ()
    else:
        ranking_source = AuditEvent
        ranking_scope = (AuditEvent.workspace_id == workspace_id,)

    is_tool_call = ranking_source.resource_type == AuditResourceType.TOOL_CALL
    is_integration_resource = ranking_source.resource_type == AuditResourceType.INTEGRATION_RESOURCE
    has_tool_correlation = ranking_source.audit_rollup_run_id.is_not(
        None
    ) & ranking_source.audit_rollup_tool_call_id.is_not(None)
    integration_with_tool_call = is_integration_resource & has_tool_correlation
    group_key = _audit_rollup_group_key(ranking_source)
    is_pending = ranking_source.status == AuditStatus.PENDING
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
            ranking_source,
            group_key.label("group_key"),
            func.row_number()
            .over(
                partition_by=group_key,
                order_by=(
                    display_priority.desc(),
                    ranking_source.occurred_at.desc(),
                    ranking_source.id.desc(),
                ),
            )
            .label("display_rank"),
            func.row_number()
            .over(
                partition_by=group_key,
                order_by=(
                    outcome_priority.desc(),
                    ranking_source.occurred_at.desc(),
                    ranking_source.id.desc(),
                ),
            )
            .label("outcome_rank"),
            func.row_number()
            .over(
                partition_by=group_key,
                order_by=(
                    detail_priority.desc(),
                    ranking_source.occurred_at.desc(),
                    ranking_source.id.desc(),
                ),
            )
            .label("detail_rank"),
        )
        .where(*ranking_scope)
        .cte("ranked_audit_events")
    )
    display_rows = select(ranked).where(ranked.c.display_rank == 1).subquery()
    detail_rows = (
        select(
            ranked.c.group_key,
            ranked.c.id.label("detail_event_id"),
        )
        .where(ranked.c.detail_rank == 1)
        .subquery()
    )
    outcome_rows = (
        select(
            ranked.c.group_key,
            ranked.c.status.label("effective_status"),
            ranked.c.summary.label("effective_summary"),
        )
        .where(ranked.c.outcome_rank == 1)
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
    return stmt.order_by(display_event.occurred_at.desc(), display_event.id.desc())


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
    stmt = _rolled_up_audit_events_statement(
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
    numbered_events = (
        stmt.add_columns(func.count().over().label("total_count"))
        .cte("numbered_audit_events")
        .prefix_with("MATERIALIZED")
    )
    page = (
        select(numbered_events)
        .order_by(numbered_events.c.occurred_at.desc(), numbered_events.c.id.desc())
        .limit(limit)
        .offset(offset)
        .cte("audit_event_page")
    )
    page_total = select(
        func.coalesce(func.max(numbered_events.c.total_count), 0).label("total_count")
    ).cte("audit_event_page_total")
    page_event = aliased(AuditEvent, page)
    rows = (
        await db.execute(
            select(
                page_event,
                page.c.detail_event_id,
                page.c.effective_status,
                page.c.effective_summary,
                page_total.c.total_count,
            )
            .select_from(page_total.outerjoin(page, true()))
            .order_by(page.c.occurred_at.desc(), page.c.id.desc())
        )
    ).all()
    total = int(rows[0].total_count)
    return [
        (event, detail_event_id, effective_status, effective_summary)
        for event, detail_event_id, effective_status, effective_summary, _total_count in rows
        if event is not None
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
