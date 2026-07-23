# apps/api/integrations/google_ads/operations/list_accounts.py

"""Read the persisted Google Ads hierarchy for one connection."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.integrations import IntegrationResource


async def list_accounts(
    db: AsyncSession,
    *,
    connection_id: UUID,
    integration_resource_id: UUID,
) -> dict[str, Any]:
    row = await db.scalar(
        select(IntegrationResource).where(
            IntegrationResource.id == integration_resource_id,
            IntegrationResource.connection_id == connection_id,
            IntegrationResource.resource_type == "google_ads_account",
            IntegrationResource.deleted.is_(False),
        )
    )
    return {
        "accounts": (
            [
                {
                    "customer_id": row.external_id,
                    "display_name": row.display_name,
                    "parent_customer_id": row.parent_external_id,
                    "manager": bool(row.permissions_metadata.get("manager", False)),
                    "currency_code": str(row.permissions_metadata.get("currency_code", "")),
                    "status": str(row.permissions_metadata.get("status", "")),
                    "writable": row.writable,
                    "enabled": row.enabled,
                }
            ]
            if row is not None
            else []
        )
    }
