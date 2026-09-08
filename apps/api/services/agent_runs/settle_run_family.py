# apps/api/services/agent_runs/settle_run_family.py

"""Locks and settles execution families in root-first order."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_run import AgentRun
from services.agent_runs.domain import RUN_STATUS_CANCELLED, RUN_STATUS_FAILED, is_terminal
from services.agent_runs.staged_content_cleanup import enqueue_staged_approval_content_cleanup


async def lock_run_family(db: AsyncSession, *, run_id: UUID) -> list[AgentRun]:
    """Locks root then children; callers holding a child must already hold its root."""
    candidate = (
        await db.execute(
            select(
                AgentRun.id, AgentRun.parent_run_id, AgentRun.workspace_id, AgentRun.user_id
            ).where(AgentRun.id == run_id, AgentRun.deleted.is_(False))
        )
    ).one_or_none()
    if candidate is None:
        return []
    root_id = candidate.parent_run_id or candidate.id
    scope = (
        AgentRun.workspace_id == candidate.workspace_id,
        AgentRun.user_id == candidate.user_id,
        AgentRun.deleted.is_(False),
    )
    root = await db.scalar(
        select(AgentRun)
        .where(AgentRun.id == root_id, *scope)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if root is None:
        return []
    children = await db.scalars(
        select(AgentRun)
        .where(AgentRun.parent_run_id == root_id, *scope)
        .order_by(AgentRun.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return [root, *children]


async def settle_run_family(
    db: AsyncSession,
    *,
    run_id: UUID,
    status: str = RUN_STATUS_FAILED,
    error_code: str | None = None,
    error_message: str | None = None,
    owner_instance_id: str | None = None,
) -> list[AgentRun]:
    """Settles a target and its non-terminal descendants while preserving terminal verdicts."""
    from services.agent_runs.utils import transition_run_status

    if status not in {RUN_STATUS_FAILED, RUN_STATUS_CANCELLED}:
        raise ValueError("Family settlement requires failure or cancellation")
    family = await lock_run_family(db, run_id=run_id)
    target = next((run for run in family if run.id == run_id), None)
    if target is None or (
        owner_instance_id is not None and target.owner_instance_id != owner_instance_id
    ):
        return []
    completion_json = None
    if (status == RUN_STATUS_FAILED and error_code == "agent_run_resume_requires_recovery") or (
        (family[0].metadata_json or {}).get("approval_continuation") is not None
    ):
        from services.agent_runs.build_family_recovery_evidence import (
            RECOVERY_ERROR_CODE,
            build_family_recovery_evidence,
        )

        completion_json = await build_family_recovery_evidence(db, family=family)
        if status == RUN_STATUS_FAILED and (
            target.id == family[0].id
            or error_code in {RECOVERY_ERROR_CODE, "code_mode_resume_requires_recovery"}
        ):
            error_code = RECOVERY_ERROR_CODE
            error_message = (
                "The approved work stopped before its result could be confirmed. "
                "Review completed and uncertain actions before starting more work."
            )
    changed = []
    for run in family:
        if run.id != run_id and run.parent_run_id != run_id:
            continue
        if is_terminal(run.status):
            continue
        await enqueue_staged_approval_content_cleanup(db, run=run)
        await transition_run_status(
            db,
            run,
            status,
            error_code=error_code if run.id == run_id else "run_parent_terminated",
            completion_json=completion_json if run.id == run_id else None,
            error_message=error_message
            if run.id == run_id
            else "The specialist stopped because its parent run ended.",
        )
        changed.append(run)
    return changed
