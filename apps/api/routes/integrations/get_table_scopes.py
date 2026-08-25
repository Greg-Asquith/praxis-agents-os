# apps/api/routes/integrations/get_table_scopes.py

"""List table row filters for one integration connection."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep, require_editor
from services.integrations.table_scopes.list_table_scopes import (
    list_table_scopes as list_table_scopes_service,
)
from services.integrations.table_scopes.schemas import TableScopeListResponse

router = APIRouter(dependencies=[Depends(require_editor)])


@router.get("/connections/{connection_id}/table-scopes")
async def get_table_scopes(
    connection_id: Annotated[UUID, Path()],
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> TableScopeListResponse:
    workspace, _membership = workspace_context
    return await list_table_scopes_service(
        db,
        connection_id=connection_id,
        actor=actor,
        workspace=workspace,
    )
