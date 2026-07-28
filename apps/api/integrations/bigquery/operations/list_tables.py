# apps/api/integrations/bigquery/operations/list_tables.py

"""List cached tables for one selected BigQuery dataset."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.integration_table_schema import IntegrationTableSchema


async def list_tables(
    db: AsyncSession,
    *,
    integration_resource_id: UUID,
) -> list[IntegrationTableSchema]:
    return list(
        (
            await db.scalars(
                select(IntegrationTableSchema)
                .where(
                    IntegrationTableSchema.resource_id == integration_resource_id,
                    IntegrationTableSchema.availability == "available",
                )
                .order_by(IntegrationTableSchema.table_external_id)
            )
        ).all()
    )
