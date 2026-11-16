# apps/api/routes/integrations/view_context_file.py

"""Stream a provider file for a person to view from a conversation's tool card."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Response

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep, require_read
from services.integrations.file_sources import IntegrationFileSourceCreate, view_integration_file

router = APIRouter(dependencies=[Depends(require_read)])


# POST keeps the reference out of URLs and logs; the bytes are never stored.
@router.post("/conversations/{conversation_id}/file-views")
async def view_context_file(
    conversation_id: Annotated[UUID, Path()],
    payload: IntegrationFileSourceCreate,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> Response:
    workspace, _membership = workspace_context
    download = await view_integration_file(
        db,
        actor=actor,
        workspace=workspace,
        conversation_id=conversation_id,
        payload=payload,
    )
    return Response(
        content=download.content,
        media_type=download.content_type,
        headers={
            "Content-Security-Policy": "sandbox; default-src 'none'",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
