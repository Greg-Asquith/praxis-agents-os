# apps/api/integrations/google_ads/entity_resolvers/__init__.py

"""Google Ads entity resolvers."""

from .campaign import GOOGLE_ADS_CAMPAIGN_RESOLVER
from .shared_set import GOOGLE_ADS_SHARED_SET_RESOLVER

__all__ = ["GOOGLE_ADS_CAMPAIGN_RESOLVER", "GOOGLE_ADS_SHARED_SET_RESOLVER"]
