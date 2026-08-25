# apps/api/routes/integrations/list_resource_tables.py

"""List cached tables that can carry row filters."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep, require_editor
from services.integrations.table_scopes.list_resource_tables import (
    list_resource_tables as list_resource_tables_service,
)
from services.integrations.table_scopes.schemas import TableScopeTableListResponse

router = APIRouter(dependencies=[Depends(require_editor)])


@router.get("/connections/{connection_id}/resources/{resource_id}/tables")
async def list_resource_tables(
    connection_id: Annotated[UUID, Path()],
    resource_id: Annotated[UUID, Path()],
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(min_length=1, max_length=1024)] = None,
) -> TableScopeTableListResponse:
    workspace, _membership = workspace_context
    return await list_resource_tables_service(
        db,
        connection_id=connection_id,
        resource_id=resource_id,
        actor=actor,
        workspace=workspace,
        limit=limit,
        cursor=cursor,
    )
