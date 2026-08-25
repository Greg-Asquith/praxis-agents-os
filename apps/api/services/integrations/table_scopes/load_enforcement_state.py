# apps/api/services/integrations/table_scopes/load_enforcement_state.py

"""Load fresh row-scope enforcement state for a provider query tool."""

from collections.abc import Collection, Mapping
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from models.integration_table_schema import IntegrationTableSchema
from models.integration_table_scope_rule import IntegrationTableScopeRule
from models.integrations import IntegrationResource

from .adapter import TableScopeAdapter
from .domain import (
    StoredTableScopeRule,
    TableScopeEnforcementState,
    TableScopeRewriteError,
)


async def load_table_scope_enforcement_state(
    db: AsyncSession,
    *,
    connection_id: UUID,
    active_resource_ids: Collection[UUID],
    adapter: TableScopeAdapter,
) -> TableScopeEnforcementState:
    """Returns current rules and cache-known base tables for active resources."""
    rule_rows = (
        await db.execute(
            select(IntegrationTableScopeRule, IntegrationResource)
            .join(
                IntegrationResource,
                IntegrationResource.id == IntegrationTableScopeRule.resource_id,
            )
            .where(
                IntegrationTableScopeRule.connection_id == connection_id,
                IntegrationTableScopeRule.deleted.is_(False),
            )
            .order_by(IntegrationTableScopeRule.id)
        )
    ).all()
    rules = tuple(
        StoredTableScopeRule(
            resource_id=resource.id,
            resource_metadata=dict(resource.permissions_metadata),
            table_external_id=rule.table_external_id,
            column_name=rule.column_name,
            column_type=rule.column_type,
            allowed_values=tuple(str(value) for value in rule.allowed_values),
        )
        for rule, resource in rule_rows
    )
    if not rules:
        return TableScopeEnforcementState(rules=(), permitted_table_ids_by_resource={})

    rule_table_keys = {(rule.resource_id, rule.table_external_id) for rule in rules}
    rule_schemas = (
        await db.scalars(
            select(IntegrationTableSchema).where(
                tuple_(
                    IntegrationTableSchema.resource_id,
                    IntegrationTableSchema.table_external_id,
                ).in_(rule_table_keys)
            )
        )
    ).all()
    schemas_by_table = {
        (schema.resource_id, schema.table_external_id): schema for schema in rule_schemas
    }
    for rule in rules:
        schema = schemas_by_table.get((rule.resource_id, rule.table_external_id))
        if schema is None or schema.table_type != "table" or schema.availability != "available":
            raise TableScopeRewriteError(
                "A saved row filter references a table that is no longer an available base "
                "table. Ask an operator to refresh the connection or update its row filters."
            )
        eligible_columns = {
            column.name: column.column_type
            for column in adapter.eligible_columns(
                [field for field in schema.schema_fields if isinstance(field, Mapping)]
            )
        }
        if eligible_columns.get(rule.column_name) != rule.column_type:
            raise TableScopeRewriteError(
                "A saved row filter no longer matches the cached table schema. Ask an operator "
                "to refresh the connection or update its row filters."
            )

    schema_rows = (
        await db.execute(
            select(
                IntegrationTableSchema.resource_id,
                IntegrationTableSchema.table_external_id,
            ).where(
                IntegrationTableSchema.resource_id.in_(active_resource_ids),
                IntegrationTableSchema.table_type == "table",
                IntegrationTableSchema.availability == "available",
            )
        )
    ).all()
    permitted: dict[UUID, set[str]] = {resource_id: set() for resource_id in active_resource_ids}
    for resource_id, table_external_id in schema_rows:
        permitted.setdefault(resource_id, set()).add(table_external_id)
    return TableScopeEnforcementState(
        rules=rules,
        permitted_table_ids_by_resource={
            resource_id: frozenset(table_ids) for resource_id, table_ids in permitted.items()
        },
    )
