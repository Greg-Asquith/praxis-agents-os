# apps/api/integrations/google_ads/entity_resolvers/__init__.py

"""Google Ads entity resolvers."""

from .ad_group import GOOGLE_ADS_AD_GROUP_RESOLVER
from .campaign import GOOGLE_ADS_CAMPAIGN_RESOLVER
from .campaign_budget import GOOGLE_ADS_CAMPAIGN_BUDGET_RESOLVER
from .recommendation import GOOGLE_ADS_RECOMMENDATION_RESOLVER
from .shared_set import GOOGLE_ADS_SHARED_SET_RESOLVER

__all__ = [
    "GOOGLE_ADS_AD_GROUP_RESOLVER",
    "GOOGLE_ADS_CAMPAIGN_BUDGET_RESOLVER",
    "GOOGLE_ADS_CAMPAIGN_RESOLVER",
    "GOOGLE_ADS_RECOMMENDATION_RESOLVER",
    "GOOGLE_ADS_SHARED_SET_RESOLVER",
]
