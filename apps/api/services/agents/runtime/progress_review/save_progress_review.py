# apps/api/services/agents/runtime/progress_review/save_progress_review.py

"""Saves a run family's review history on the root run with an audit event."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_run import AgentRun
from services.agents.runtime.progress_review.grant import PROGRESS_REVIEWS_KEY, RequestGrant
from services.audit_events.enums import AuditAction, AuditActorType, AuditResourceType
from services.audit_events.operations import safe_record_operation_audit_event

_SUMMARY_BY_GRANT = {
    True: "Progress review let the run carry on",
    False: "Progress review paused the run for a person",
}


async def save_progress_review(
    db: AsyncSession,
    *,
    root_run: AgentRun,
    grant: RequestGrant,
    reviewed_run_id: UUID,
    requests_granted: int,
) -> None:
    """Commits the latest review. The caller holds the root run's session lock."""
    latest = grant.reviews[-1]
    root_run.metadata_json = {
        **(root_run.metadata_json or {}),
        PROGRESS_REVIEWS_KEY: grant.snapshot(),
    }
    await safe_record_operation_audit_event(
        db,
        workspace_id=root_run.workspace_id,
        action=AuditAction.UPDATE,
        resource_type=AuditResourceType.AGENT_RUN,
        resource_id=root_run.id,
        actor_type=AuditActorType.SYSTEM,
        actor_display="Progress review",
        requested_by_user_id=root_run.user_id,
        summary=_SUMMARY_BY_GRANT[latest.grants_steps],
        details={
            "operation": "progress_review",
            "verdict": latest.verdict,
            "requests_granted": requests_granted,
            "reviews_used": len(grant.reviews),
            "requests": latest.requests,
            "reviewed_run_id": str(reviewed_run_id),
            "provider": latest.provider,
            "model": latest.model,
        },
    )
    await db.commit()
