# apps/api/integrations/google_ads/references/__init__.py

from .ad_group import GoogleAdsAdGroupReference
from .campaign import GoogleAdsCampaignReference
from .recommendation import GoogleAdsRecommendationReference
from .shared_set import GoogleAdsSharedSetReference

__all__ = [
    "GoogleAdsAdGroupReference",
    "GoogleAdsCampaignReference",
    "GoogleAdsRecommendationReference",
    "GoogleAdsSharedSetReference",
]
