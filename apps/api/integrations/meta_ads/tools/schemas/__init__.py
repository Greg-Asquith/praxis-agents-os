# apps/api/integrations/meta_ads/tools/schemas/__init__.py

"""Meta Ads tool contracts."""

from .accounts import MetaAdsAccountData, MetaAdsAccountEntry, MetaAdsAccountsOutput
from .activities import (
    MetaAdsActivitiesData,
    MetaAdsActivitiesEntry,
    MetaAdsActivitiesInput,
    MetaAdsActivitiesOutput,
    MetaAdsActivity,
)
from .conversions import (
    MetaAdsConversion,
    MetaAdsConversionsData,
    MetaAdsConversionsEntry,
    MetaAdsConversionsOutput,
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
    MetaAdsObjectsData,
    MetaAdsObjectsEntry,
    MetaAdsObjectsInput,
    MetaAdsObjectsOutput,
)

__all__ = [
    "MetaAdsAccountData",
    "MetaAdsAccountEntry",
    "MetaAdsAccountsOutput",
    "MetaAdsActivitiesData",
    "MetaAdsActivitiesEntry",
    "MetaAdsActivitiesInput",
    "MetaAdsActivitiesOutput",
    "MetaAdsActivity",
    "MetaAdsConversion",
    "MetaAdsConversionsData",
    "MetaAdsConversionsEntry",
    "MetaAdsConversionsOutput",
    "MetaAdsInsightsData",
    "MetaAdsInsightsEntry",
    "MetaAdsInsightsFilter",
    "MetaAdsInsightsInput",
    "MetaAdsInsightsLevel",
    "MetaAdsInsightsOutput",
    "MetaAdsObject",
    "MetaAdsObjectsData",
    "MetaAdsObjectsEntry",
    "MetaAdsObjectsInput",
    "MetaAdsObjectsOutput",
]
