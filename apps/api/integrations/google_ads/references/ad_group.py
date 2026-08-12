# apps/api/integrations/google_ads/references/ad_group.py

from typing import Literal

from pydantic import Field

from services.integrations.entity_references import ScopedEntityReference


class GoogleAdsAdGroupReference(ScopedEntityReference):
    entity_kind: Literal["google_ads_ad_group"] = "google_ads_ad_group"
    status: str | None = Field(default=None, max_length=64)
