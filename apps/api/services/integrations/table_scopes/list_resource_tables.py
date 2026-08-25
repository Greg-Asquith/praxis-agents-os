# apps/api/services/integrations/table_scopes/list_resource_tables.py

"""List cached base tables eligible for row-scope rules."""

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationValidationError
from models.integration_table_schema import IntegrationTableSchema
from models.integrations import IntegrationResource
from models.user import User
from models.workspace import Workspace
from services.integrations.connections.utils import get_visible_connection

from .adapter import TableScopeAdapter
from .schemas import (
    EligibleTableScopeColumnRead,
    TableScopeTableListResponse,
    TableScopeTableRead,
)
from .utils import table_scope_adapter_for, table_scope_resource_types


async def list_resource_tables(
    db: AsyncSession,
    *,
    connection_id: UUID,
    resource_id: UUID,
    actor: User,
    workspace: Workspace,
    limit: int,
    cursor: str | None,
) -> TableScopeTableListResponse:
    """Returns one page of base tables and bounded eligible column metadata."""
    connection = await get_visible_connection(
        db,
        connection_id=connection_id,
        actor=actor,
        workspace=workspace,
    )
    adapter = table_scope_adapter_for(connection)
    resource = await db.scalar(
        select(IntegrationResource).where(
            IntegrationResource.id == resource_id,
            IntegrationResource.connection_id == connection.id,
            IntegrationResource.deleted.is_(False),
            IntegrationResource.resource_type.in_(
                table_scope_resource_types(connection.provider_key)
            ),
        )
    )
    if resource is None:
        raise IntegrationValidationError(
            "The selected resource is not available on this connection",
            provider_key=connection.provider_key,
            connection_id=str(connection.id),
            operation="list_table_scope_tables",
        )
    statement = select(IntegrationTableSchema).where(
        IntegrationTableSchema.resource_id == resource.id,
        IntegrationTableSchema.table_type == "table",
        IntegrationTableSchema.availability == "available",
    )
    if cursor is not None:
        statement = statement.where(IntegrationTableSchema.table_external_id > cursor)
    schemas = list(
        (
            await db.scalars(
                statement.order_by(IntegrationTableSchema.table_external_id).limit(limit + 1)
            )
        ).all()
    )
    has_more = len(schemas) > limit
    page = schemas[:limit]
    return TableScopeTableListResponse(
        connection_id=connection.id,
        resource_id=resource.id,
        tables=[_table_read(schema, adapter=adapter) for schema in page],
        next_cursor=page[-1].table_external_id if has_more else None,
    )


def _table_read(
    schema: IntegrationTableSchema,
    *,
    adapter: TableScopeAdapter,
) -> TableScopeTableRead:
    fields = [field for field in schema.schema_fields if isinstance(field, Mapping)]
    descriptions = {
        str(field.get("name", "")): _optional_text(field.get("description")) for field in fields
    }
    return TableScopeTableRead(
        table_external_id=schema.table_external_id,
        description=schema.description,
        columns=[
            EligibleTableScopeColumnRead(
                name=column.name,
                column_type=column.column_type,
                description=descriptions.get(column.name),
            )
            for column in adapter.eligible_columns(fields)
        ],
    )


def _optional_text(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None
