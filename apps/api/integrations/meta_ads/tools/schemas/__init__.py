# apps/api/integrations/meta_ads/tools/schemas/__init__.py

"""Meta Ads tool contracts."""

from .accounts import MetaAdsAccountData, MetaAdsAccountEntry, MetaAdsAccountsOutput
from .custom_conversions import (
    MetaAdsCustomConversion,
    MetaAdsCustomConversionsData,
    MetaAdsCustomConversionsEntry,
    MetaAdsCustomConversionsOutput,
)
from .insights import (
    MetaAdsInsightsData,
    MetaAdsInsightsEntry,
    MetaAdsInsightsFilter,
    MetaAdsInsightsInput,
    MetaAdsInsightsLevel,
    MetaAdsInsightsOutput,
)
from .objects import (
    MetaAdsObject,
    MetaAdsObjectBudget,
    MetaAdsObjectsData,
    MetaAdsObjectsEntry,
    MetaAdsObjectsInput,
    MetaAdsObjectsOutput,
)

__all__ = [
    "MetaAdsAccountData",
    "MetaAdsAccountEntry",
    "MetaAdsAccountsOutput",
    "MetaAdsCustomConversion",
    "MetaAdsCustomConversionsData",
    "MetaAdsCustomConversionsEntry",
    "MetaAdsCustomConversionsOutput",
    "MetaAdsInsightsData",
    "MetaAdsInsightsEntry",
    "MetaAdsInsightsFilter",
    "MetaAdsInsightsInput",
    "MetaAdsInsightsLevel",
    "MetaAdsInsightsOutput",
    "MetaAdsObject",
    "MetaAdsObjectBudget",
    "MetaAdsObjectsData",
    "MetaAdsObjectsEntry",
    "MetaAdsObjectsInput",
    "MetaAdsObjectsOutput",
]
