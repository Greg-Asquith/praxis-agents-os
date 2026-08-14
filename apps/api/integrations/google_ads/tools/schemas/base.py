# apps/api/integrations/google_ads/tools/schemas/base.py

"""Shared strict base for Google Ads result contracts."""

from pydantic import BaseModel, ConfigDict


class GoogleAdsStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
