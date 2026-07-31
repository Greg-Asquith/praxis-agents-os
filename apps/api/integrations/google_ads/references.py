# apps/api/integrations/google_ads/references.py

"""Google Ads-owned scoped entity reference types."""

from typing import Literal

from pydantic import Field

from services.integrations.entity_references import ScopedEntityReference


class GoogleAdsCampaignReference(ScopedEntityReference):
    entity_kind: Literal["google_ads_campaign"] = "google_ads_campaign"
    status: str | None = Field(default=None, max_length=64)
