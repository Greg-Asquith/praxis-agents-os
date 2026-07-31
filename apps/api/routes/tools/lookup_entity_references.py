# apps/api/routes/tools/lookup_entity_references.py

"""Search and hydrate authorized runtime tool entity references."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep, require_read
from core.rate_limiting import require_rate_limit
from services.agents.runtime.entity_references.schemas import (
    EntityReferenceLookupRequest,
    EntityReferenceLookupResponse,
)
from services.agents.runtime.entity_references.service import lookup_entity_references

router = APIRouter(
    dependencies=[
        Depends(require_read),
        Depends(require_rate_limit(custom_limit=120, custom_window=60)),
    ]
)


@router.post("/conversations/{conversation_id}/entity-references")
async def lookup_references(
    conversation_id: Annotated[UUID, Path()],
    payload: EntityReferenceLookupRequest,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> EntityReferenceLookupResponse:
    workspace, membership = workspace_context
    return await lookup_entity_references(
        db,
        actor=actor,
        workspace=workspace,
        membership=membership,
        conversation_id=conversation_id,
        payload=payload,
    )
