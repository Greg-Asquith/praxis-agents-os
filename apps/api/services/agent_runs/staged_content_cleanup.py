# apps/api/services/agent_runs/staged_content_cleanup.py

"""Durably queue cleanup for staged approval input owned by an agent run."""

from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_run import AgentRun
from models.jobs import Job
from services.agents.runtime.staged_tool_content import (
    staged_write_content_refs_from_metadata,
)

DELETE_STAGED_APPROVAL_CONTENT_KIND = "agent_runs.delete_staged_approval_content"


async def enqueue_staged_approval_content_cleanup(
    db: AsyncSession,
    *,
    run: AgentRun,
) -> Job | None:
    """Queue retryable cleanup before the run's approval metadata is discarded."""
    content_refs = staged_write_content_refs_from_metadata(
        run.metadata_json,
        workspace_id=run.workspace_id,
        run_id=run.id,
    )
    if not content_refs:
        return None

    from services.jobs.enqueue_job import enqueue_job

    return await enqueue_job(
        db,
        kind=DELETE_STAGED_APPROVAL_CONTENT_KIND,
        subject_type="agent_run",
        subject_id=run.id,
        payload={
            "workspace_id": str(run.workspace_id),
            "run_id": str(run.id),
            "content_refs": content_refs,
        },
        content_hash="delete-staged-approval-content",
    )
