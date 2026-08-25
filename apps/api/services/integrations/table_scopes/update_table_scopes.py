# apps/api/services/integrations/table_scopes/update_table_scopes.py

"""Replace row-scope rules for one integration connection."""

import re
from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationValidationError
from models.integration_table_schema import IntegrationTableSchema
from models.integration_table_scope_rule import IntegrationTableScopeRule
from models.integrations import IntegrationConnection, IntegrationResource
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType
from services.integrations.connections.utils import (
    get_visible_connection,
    require_connection_mutation_allowed,
)
from services.integrations.utils import record_integration_audit

from .adapter import TableScopeAdapter
from .domain import TableScopeValueError
from .schemas import TableScopeListResponse, TableScopeReplaceRequest, TableScopeRuleRead
from .utils import table_scope_adapter_for, table_scope_resource_types

_INTEGER_PATTERN = re.compile(r"^-?(?:0|[1-9][0-9]*)$")


async def update_table_scopes(
    db: AsyncSession,
    *,
    connection_id: UUID,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    payload: TableScopeReplaceRequest,
) -> TableScopeListResponse:
    """Validates and replaces all row-scope rules on a connection."""
    connection = await get_visible_connection(
        db,
        connection_id=connection_id,
        actor=actor,
        workspace=workspace,
        for_update=True,
    )
    require_connection_mutation_allowed(connection, actor=actor, membership=membership)
    adapter = table_scope_adapter_for(connection)

    resources = (
        await db.scalars(
            select(IntegrationResource).where(
                IntegrationResource.connection_id == connection.id,
                IntegrationResource.deleted.is_(False),
                IntegrationResource.resource_type.in_(
                    table_scope_resource_types(connection.provider_key)
                ),
            )
        )
    ).all()
    resources_by_id = {resource.id: resource for resource in resources}
    requested_tables = [
        (item.resource_id, item.table_external_id.strip()) for item in payload.rules
    ]
    if len(set(requested_tables)) != len(requested_tables):
        _invalid(connection, "Each table can have only one row filter")

    requested_resource_ids = {item.resource_id for item in payload.rules}
    if requested_resource_ids - resources_by_id.keys():
        _invalid(connection, "Every selected resource must belong to this connection")

    schema_rows = (
        await db.scalars(
            select(IntegrationTableSchema).where(
                IntegrationTableSchema.resource_id.in_(requested_resource_ids),
                IntegrationTableSchema.availability == "available",
            )
        )
    ).all()
    schemas_by_table = {
        (schema.resource_id, schema.table_external_id): schema for schema in schema_rows
    }

    replacements: list[tuple[IntegrationTableScopeRule, IntegrationResource]] = []
    for item in payload.rules:
        table_external_id = item.table_external_id.strip()
        column_name = item.column_name.strip()
        schema = schemas_by_table.get((item.resource_id, table_external_id))
        if schema is None or schema.table_type != "table":
            _invalid(connection, "Row filters require an available base table")
        fields = [field for field in schema.schema_fields if isinstance(field, Mapping)]
        eligible = {column.name: column.column_type for column in adapter.eligible_columns(fields)}
        column_type = eligible.get(column_name)
        if column_type is None:
            _invalid(connection, "The selected column cannot be used for a row filter")
        allowed_values = _validate_values(
            item.allowed_values,
            column_type=column_type,
            connection=connection,
            adapter=adapter,
        )
        resource = resources_by_id[item.resource_id]
        replacements.append(
            (
                IntegrationTableScopeRule(
                    connection_id=connection.id,
                    resource_id=resource.id,
                    table_external_id=table_external_id,
                    column_name=column_name,
                    column_type=column_type,
                    allowed_values=list(allowed_values),
                    created_by_user_id=actor.id,
                ),
                resource,
            )
        )

    await db.execute(
        delete(IntegrationTableScopeRule).where(
            IntegrationTableScopeRule.connection_id == connection.id
        )
    )
    await db.flush()
    db.add_all([rule for rule, _resource in replacements])
    await db.flush()

    await record_integration_audit(
        db,
        workspace_id=workspace.id,
        action=AuditAction.UPDATE,
        resource_type=AuditResourceType.INTEGRATION_CONNECTION,
        resource_id=connection.id,
        details={
            "connection": connection.label,
            "row_filter_count": len(replacements),
            "tables": [
                {
                    "resource": resource.external_id,
                    "table": rule.table_external_id,
                    "column": rule.column_name,
                }
                for rule, resource in replacements
            ],
        },
    )
    return TableScopeListResponse(
        connection_id=connection.id,
        rules=[
            TableScopeRuleRead(
                id=rule.id,
                resource_id=resource.id,
                resource_external_id=resource.external_id,
                resource_display_name=resource.display_name,
                table_external_id=rule.table_external_id,
                column_name=rule.column_name,
                column_type=rule.column_type,
                allowed_values=list(rule.allowed_values),
            )
            for rule, resource in replacements
        ],
    )


def _validate_values(
    values: list[str],
    *,
    column_type: str,
    connection: IntegrationConnection,
    adapter: TableScopeAdapter,
) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        if not value or len(value) > 256:
            _invalid(connection, "Each row-filter value must contain 1-256 characters")
        if column_type == "integer":
            if _INTEGER_PATTERN.fullmatch(value) is None:
                _invalid(connection, "Integer row-filter values must use whole numbers")
            value = str(int(value))
        normalized.append(value)
    deduplicated = tuple(dict.fromkeys(normalized))
    try:
        adapter.validate_allowed_values(column_type=column_type, values=deduplicated)
    except TableScopeValueError as exc:
        _invalid(connection, str(exc))
    return deduplicated


def _invalid(connection: IntegrationConnection, message: str) -> None:
    raise IntegrationValidationError(
        message,
        provider_key=connection.provider_key,
        connection_id=str(connection.id),
        operation="update_table_scopes",
    )
