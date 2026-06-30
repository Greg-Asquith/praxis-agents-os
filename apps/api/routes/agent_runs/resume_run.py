# apps/api/routes/agent_runs/resume_run.py

"""Route for resuming a suspended agent run."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path
from fastapi.responses import StreamingResponse

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.agent_runs import resume_agent_run_stream
from services.agent_runs.schemas import AgentRunResumeRequest

router = APIRouter()


@router.post("/{run_id}/resume")
async def resume_run(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    run_id: Annotated[UUID, Path()],
    payload: AgentRunResumeRequest,
) -> StreamingResponse:
    workspace, _membership = workspace_context
    return await resume_agent_run_stream(
        db,
        actor=actor,
        workspace=workspace,
        run_id=run_id,
        payload=payload,
    )
