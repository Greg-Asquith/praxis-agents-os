# apps/api/integrations/meta_ads/tools/schemas/base.py

"""Strict shared models and value types for Meta Ads tools."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

type MetaAdsId = Annotated[str, Field(pattern=r"^[0-9]+$", max_length=128)]
type MetaAdsMoney = Annotated[str, Field(max_length=520, pattern=r"^-?[0-9]+(?:\.[0-9]+)?$")]
type MetaAdsText = Annotated[str, Field(max_length=512)]


class MetaAdsStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
