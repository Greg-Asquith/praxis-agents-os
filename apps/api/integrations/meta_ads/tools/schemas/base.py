# apps/api/integrations/meta_ads/tools/schemas/base.py

"""Strict shared models for Meta Ads tools."""

from pydantic import BaseModel, ConfigDict


class MetaAdsStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
