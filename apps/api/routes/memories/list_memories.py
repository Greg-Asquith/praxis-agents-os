# apps/api/routes/memories/list_memories.py

"""List workspace-visible memories."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep, require_read
from services.memories import list_memories as list_memories_service
from services.memories.schemas import MemoriesListResponse

router = APIRouter(dependencies=[Depends(require_read)])


@router.get("/")
async def list_memories(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    scope: Literal["agent", "user", "workspace"] | None = None,
    kind: Literal["core", "note"] | None = None,
    memory_type: Literal["fact", "preference", "episode", "outcome"] | None = None,
    agent_id: UUID | None = None,
    status: Literal["active", "superseded", "archived"] = "active",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MemoriesListResponse:
    workspace, _membership = workspace_context
    return await list_memories_service(
        db,
        actor=actor,
        workspace=workspace,
        scope=scope,
        kind=kind,
        memory_type=memory_type,
        agent_id=agent_id,
        status=status,
        limit=limit,
        offset=offset,
    )
