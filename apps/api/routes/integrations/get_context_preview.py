# apps/api/routes/integrations/get_context_preview.py

"""Resolve provider previews through a conversation's active context."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep, require_read
from services.integrations.context import resolve_conversation_target
from services.integrations.previews import IntegrationPreviewRead, get_integration_preview

router = APIRouter(dependencies=[Depends(require_read)])


@router.get("/conversations/{conversation_id}/previews/{kind}")
async def get_context_preview(
    conversation_id: Annotated[UUID, Path()],
    kind: Annotated[str, Path(pattern=r"^[a-z][a-z0-9_]*$")],
    provider_key: Annotated[str, Query(pattern=r"^[a-z][a-z0-9_-]*$")],
    scope_id: Annotated[str, Query(min_length=1, max_length=512)],
    ref: Annotated[str, Query(min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_+/=-]+$")],
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> IntegrationPreviewRead:
    workspace, _membership = workspace_context
    scope = await resolve_conversation_target(
        db,
        actor=actor,
        workspace=workspace,
        conversation_id=conversation_id,
        provider_key=provider_key,
        scope_id=scope_id,
        operation=f"preview_{kind}",
    )
    return await get_integration_preview(
        db,
        connection_id=scope.connection_id,
        kind=kind,
        ref=ref,
        actor=actor,
        workspace=workspace,
        scope=scope,
    )
