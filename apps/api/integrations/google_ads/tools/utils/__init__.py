# apps/api/integrations/google_ads/tools/utils/__init__.py

"""Stable exports for focused Google Ads runtime-tool helpers."""

from .bindings import GOOGLE_ADS_BINDING, GOOGLE_ADS_WRITE_BINDING, RESULTS_FIELD
from .campaign_negative_keywords import (
    MAX_CAMPAIGN_NEGATIVE_PUBLIC_RESULT_CHARS,
    run_campaign_negative_keyword_tool,
)
from .client import google_ads_available, google_ads_client, google_ads_client_for_principal
from .fan_out import fan_out_tool_return
from .negative_keyword_results import (
    MAX_NEGATIVE_KEYWORD_PUBLIC_RESULT_CHARS,
    MAX_NEGATIVE_KEYWORD_RESULT_CHARS,
    bounded_negative_keyword_removal_result,
    bounded_negative_keyword_result,
    complete_negative_keyword_removal_result,
    complete_negative_keyword_result,
)
from .negative_keywords import normalize_negative_keywords
from .routing import login_customer_id

__all__ = [
    "GOOGLE_ADS_BINDING",
    "GOOGLE_ADS_WRITE_BINDING",
    "MAX_CAMPAIGN_NEGATIVE_PUBLIC_RESULT_CHARS",
    "MAX_NEGATIVE_KEYWORD_PUBLIC_RESULT_CHARS",
    "MAX_NEGATIVE_KEYWORD_RESULT_CHARS",
    "RESULTS_FIELD",
    "bounded_negative_keyword_removal_result",
    "bounded_negative_keyword_result",
    "complete_negative_keyword_removal_result",
    "complete_negative_keyword_result",
    "fan_out_tool_return",
    "google_ads_available",
    "google_ads_client",
    "google_ads_client_for_principal",
    "login_customer_id",
    "normalize_negative_keywords",
    "run_campaign_negative_keyword_tool",
]
