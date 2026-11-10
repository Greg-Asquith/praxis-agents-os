# apps/api/integrations/google_ads/tools/utils/__init__.py

"""Stable exports for focused Google Ads runtime-tool helpers."""

from .bindings import (
    GOOGLE_ADS_BINDING,
    GOOGLE_ADS_WRITE_BINDING,
    RESULTS_FIELD,
    active_google_ads_entries,
)
from .client import google_ads_available, google_ads_client, google_ads_client_for_principal
from .routing import login_customer_id

__all__ = [
    "GOOGLE_ADS_BINDING",
    "GOOGLE_ADS_WRITE_BINDING",
    "RESULTS_FIELD",
    "active_google_ads_entries",
    "google_ads_available",
    "google_ads_client",
    "google_ads_client_for_principal",
    "login_customer_id",
]
