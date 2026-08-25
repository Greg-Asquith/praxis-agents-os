# apps/api/routes/integrations/update_table_scopes.py

"""Replace table row filters for one integration connection."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep, require_editor
from services.integrations.table_scopes.schemas import (
    TableScopeListResponse,
    TableScopeReplaceRequest,
)
from services.integrations.table_scopes.update_table_scopes import (
    update_table_scopes as update_table_scopes_service,
)

router = APIRouter(dependencies=[Depends(require_editor)])


@router.put("/connections/{connection_id}/table-scopes")
async def update_table_scopes(
    connection_id: Annotated[UUID, Path()],
    payload: TableScopeReplaceRequest,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> TableScopeListResponse:
    workspace, membership = workspace_context
    return await update_table_scopes_service(
        db,
        connection_id=connection_id,
        actor=actor,
        workspace=workspace,
        membership=membership,
        payload=payload,
    )
