# apps/api/services/jobs/handlers/persist_interrupted_history.py

"""Retries transcript persistence in the originating run's tenant context."""

from pydantic_ai.messages import ModelMessagesTypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import (
    SESSION_MAINTENANCE_KEY,
    SESSION_WORKSPACE_ID_KEY,
    set_session_tenant_context,
)
from models.jobs import Job
from services.agent_runs.settle_run_family import lock_run_family
from services.agents.runtime.approval_identity import MAX_PROPOSAL_BYTES
from services.agents.runtime.interrupted_history import (
    INTERRUPTED_HISTORY_JOB_KIND,
    InterruptedHistory,
    InterruptedHistoryPayload,
    interrupted_payload_size,
)
from services.agents.runtime.persist_interrupted_messages import persist_interrupted_messages
from services.jobs.registry import job_handler


@job_handler(kind=INTERRUPTED_HISTORY_JOB_KIND, timeout=30.0, max_attempts=5)
async def persist_interrupted_history(db: AsyncSession, job: Job) -> None:
    """Persists a bounded suffix once without re-executing tools or changing verdicts."""
    payload = InterruptedHistoryPayload.model_validate(job.payload)
    if (
        db.info.get(SESSION_MAINTENANCE_KEY)
        or db.info.get(SESSION_WORKSPACE_ID_KEY) != payload.workspace_id
        or job.workspace_id != payload.workspace_id
        or job.initiated_by_user_id != payload.user_id
        or job.concurrency_user_id is not None
        or job.subject_type != "agent_run"
        or job.subject_id != payload.run_id
        or interrupted_payload_size(payload) > MAX_PROPOSAL_BYTES
    ):
        raise ValueError("Interrupted history job has invalid tenant or payload identity")
    await set_session_tenant_context(db, workspace_id=payload.workspace_id, user_id=payload.user_id)
    family = await lock_run_family(db, run_id=payload.run_id)
    run = next((item for item in family if item.id == payload.run_id), None)
    if run is None or (
        run.workspace_id != payload.workspace_id
        or run.user_id != payload.user_id
        or run.conversation_id != payload.conversation_id
        or run.owner_instance_id != payload.invocation_id
    ):
        return
    await persist_interrupted_messages(
        db,
        run=run,
        history=InterruptedHistory(
            messages=ModelMessagesTypeAdapter.validate_python(payload.messages),
            tool_approval_metadata_by_call_id=payload.approval_metadata,
        ),
        invocation_id=payload.invocation_id,
        history_wait=None,
    )
