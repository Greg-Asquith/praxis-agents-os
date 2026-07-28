# apps/api/integrations/bigquery/operations/get_table_schema.py

"""Read one cached table schema from a selected BigQuery dataset."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.integration_table_schema import IntegrationTableSchema


async def get_table_schema(
    db: AsyncSession,
    *,
    integration_resource_id: UUID,
    table_external_id: str,
) -> IntegrationTableSchema | None:
    return await db.scalar(
        select(IntegrationTableSchema).where(
            IntegrationTableSchema.resource_id == integration_resource_id,
            IntegrationTableSchema.table_external_id == table_external_id,
            IntegrationTableSchema.availability == "available",
        )
    )
