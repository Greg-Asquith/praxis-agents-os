# apps/api/integrations/meta_ads/entity_resolvers/__init__.py

"""Meta Ads entity resolvers."""

from .ad import META_ADS_AD_RESOLVER
from .ad_set import META_ADS_AD_SET_RESOLVER
from .campaign import META_ADS_CAMPAIGN_RESOLVER
from .instagram_account import META_ADS_INSTAGRAM_ACCOUNT_RESOLVER
from .media import META_ADS_MEDIA_RESOLVER
from .page import META_ADS_PAGE_RESOLVER

__all__ = [
    "META_ADS_AD_RESOLVER",
    "META_ADS_AD_SET_RESOLVER",
    "META_ADS_CAMPAIGN_RESOLVER",
    "META_ADS_INSTAGRAM_ACCOUNT_RESOLVER",
    "META_ADS_MEDIA_RESOLVER",
    "META_ADS_PAGE_RESOLVER",
]
