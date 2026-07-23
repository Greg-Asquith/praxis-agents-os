# apps/api/routes/integrations/get_preview.py

"""Generic route for ephemeral provider-contributed content previews."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep, require_read
from services.integrations.previews import IntegrationPreviewRead, get_integration_preview

router = APIRouter(dependencies=[Depends(require_read)])


@router.get("/connections/{connection_id}/previews/{kind}")
async def get_preview(
    connection_id: Annotated[UUID, Path()],
    kind: Annotated[str, Path(pattern=r"^[a-z][a-z0-9_]*$")],
    ref: Annotated[str, Query(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")],
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> IntegrationPreviewRead:
    workspace, _membership = workspace_context
    return await get_integration_preview(
        db,
        connection_id=connection_id,
        kind=kind,
        ref=ref,
        actor=actor,
        workspace=workspace,
    )
