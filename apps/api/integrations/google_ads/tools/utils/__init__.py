# apps/api/integrations/google_ads/tools/utils/__init__.py

"""Stable exports for focused Google Ads runtime-tool helpers."""

from .bindings import (
    GOOGLE_ADS_BINDING,
    GOOGLE_ADS_WRITE_BINDING,
    RESULTS_FIELD,
    active_google_ads_entries,
)
from .client import google_ads_available, google_ads_client, google_ads_client_for_principal
from .positive_keyword_results import (
    MAX_POSITIVE_KEYWORD_PUBLIC_RESULT_CHARS,
    bounded_positive_keyword_result,
    display_positive_keyword_result,
)
from .positive_keyword_update_results import (
    MAX_POSITIVE_KEYWORD_UPDATE_PUBLIC_RESULT_CHARS,
    bounded_positive_keyword_update_result,
    display_positive_keyword_update_result,
)
from .routing import login_customer_id

__all__ = [
    "GOOGLE_ADS_BINDING",
    "GOOGLE_ADS_WRITE_BINDING",
    "MAX_POSITIVE_KEYWORD_PUBLIC_RESULT_CHARS",
    "MAX_POSITIVE_KEYWORD_UPDATE_PUBLIC_RESULT_CHARS",
    "RESULTS_FIELD",
    "active_google_ads_entries",
    "bounded_positive_keyword_result",
    "bounded_positive_keyword_update_result",
    "display_positive_keyword_result",
    "display_positive_keyword_update_result",
    "google_ads_available",
    "google_ads_client",
    "google_ads_client_for_principal",
    "login_customer_id",
]
