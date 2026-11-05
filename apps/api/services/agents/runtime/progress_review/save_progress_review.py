# apps/api/services/agents/runtime/progress_review/save_progress_review.py

"""Saves a run family's review history on the root run with an audit event and transcript row."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_run import AgentRun
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.persistence import persist_progress_review_message
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
    reviewed: RuntimeDeps,
    requests_granted: int,
    steer_text: str | None,
) -> UUID:
    """Commits the latest review and returns its transcript row in the reviewed run's conversation.

    The caller holds the root run's session lock.
    """
    latest = grant.reviews[-1]
    reviewed_run_id = reviewed.run.id
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
    # Written through the root session, so pass identifiers rather than the specialist's rows.
    row = await persist_progress_review_message(
        db,
        workspace_id=root_run.workspace_id,
        conversation_id=reviewed.conversation.id,
        run_id=reviewed_run_id,
        review={
            "verdict": latest.verdict,
            "reason": latest.reason,
            "steer_text": steer_text,
            "review_number": len(grant.reviews),
        },
    )
    await db.commit()
    return row.id
