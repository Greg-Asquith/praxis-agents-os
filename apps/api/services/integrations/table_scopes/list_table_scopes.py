# apps/api/services/integrations/table_scopes/list_table_scopes.py

"""List row-scope rules for one integration connection."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.integration_table_scope_rule import IntegrationTableScopeRule
from models.integrations import IntegrationResource
from models.user import User
from models.workspace import Workspace
from services.integrations.connections.utils import get_visible_connection

from .schemas import TableScopeListResponse, TableScopeRuleRead
from .utils import table_scope_adapter_for


async def list_table_scopes(
    db: AsyncSession,
    *,
    connection_id: UUID,
    actor: User,
    workspace: Workspace,
) -> TableScopeListResponse:
    """Returns every active rule on a visible supported connection."""
    connection = await get_visible_connection(
        db,
        connection_id=connection_id,
        actor=actor,
        workspace=workspace,
    )
    table_scope_adapter_for(connection)
    rows = (
        await db.execute(
            select(IntegrationTableScopeRule, IntegrationResource)
            .join(
                IntegrationResource,
                IntegrationResource.id == IntegrationTableScopeRule.resource_id,
            )
            .where(
                IntegrationTableScopeRule.connection_id == connection.id,
                IntegrationTableScopeRule.deleted.is_(False),
                IntegrationResource.deleted.is_(False),
            )
            .order_by(
                IntegrationResource.display_name,
                IntegrationTableScopeRule.table_external_id,
            )
        )
    ).all()
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
            for rule, resource in rows
        ],
    )
