# apps/api/routes/integrations/get_context_preview.py

"""Resolve provider previews through a conversation's active context."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep, require_read
from core.exceptions.integration import IntegrationValidationError
from services.integrations.context import (
    get_active_context_selection,
    resolve_active_context_targets,
)
from services.integrations.context.schemas import ActiveContextSelectionValue
from services.integrations.previews import IntegrationPreviewRead, get_integration_preview

router = APIRouter(dependencies=[Depends(require_read)])


@router.get("/conversations/{conversation_id}/previews/{kind}")
async def get_context_preview(
    conversation_id: Annotated[UUID, Path()],
    kind: Annotated[str, Path(pattern=r"^[a-z][a-z0-9_]*$")],
    provider_key: Annotated[str, Query(pattern=r"^[a-z][a-z0-9_-]*$")],
    scope_id: Annotated[str, Query(min_length=1, max_length=512)],
    ref: Annotated[str, Query(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")],
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> IntegrationPreviewRead:
    workspace, _membership = workspace_context
    selections = await get_active_context_selection(
        db,
        actor=actor,
        workspace=workspace,
        conversation_id=conversation_id,
    )
    resolved = await resolve_active_context_targets(
        db,
        selections=[
            ActiveContextSelectionValue.from_selection(selection) for selection in selections
        ],
        user=actor,
        workspace=workspace,
    )
    matches = [
        entry
        for entry in resolved.entries
        if entry.provider_key == provider_key and entry.external_id == scope_id
    ]
    if len(matches) != 1:
        raise IntegrationValidationError(
            "The preview target is unavailable in the active context",
            provider_key=provider_key,
            operation=f"preview_{kind}",
        )
    return await get_integration_preview(
        db,
        connection_id=matches[0].connection_id,
        kind=kind,
        ref=ref,
        actor=actor,
        workspace=workspace,
    )
