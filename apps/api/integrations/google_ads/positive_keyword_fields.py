# apps/api/integrations/google_ads/positive_keyword_fields.py

"""Shared mutable-field contract for positive Google Ads keywords."""

from dataclasses import dataclass
from typing import Literal

type PositiveKeywordValueFamily = Literal[
    "status",
    "number",
    "money",
    "url_list",
    "text",
    "parameters",
]


@dataclass(frozen=True, slots=True)
class PositiveKeywordField:
    """One supported mutable positive-keyword field."""

    patch_name: str
    provider_name: str
    json_name: str
    value_family: PositiveKeywordValueFamily


POSITIVE_KEYWORD_FIELDS = (
    PositiveKeywordField("status", "status", "status", "status"),
    PositiveKeywordField(
        "bid_modifier",
        "bid_modifier",
        "bidModifier",
        "number",
    ),
    PositiveKeywordField(
        "cpc_bid",
        "cpc_bid_micros",
        "cpcBidMicros",
        "money",
    ),
    PositiveKeywordField(
        "final_urls",
        "final_urls",
        "finalUrls",
        "url_list",
    ),
    PositiveKeywordField(
        "final_mobile_urls",
        "final_mobile_urls",
        "finalMobileUrls",
        "url_list",
    ),
    PositiveKeywordField(
        "final_url_suffix",
        "final_url_suffix",
        "finalUrlSuffix",
        "text",
    ),
    PositiveKeywordField(
        "tracking_url_template",
        "tracking_url_template",
        "trackingUrlTemplate",
        "text",
    ),
    PositiveKeywordField(
        "url_custom_parameters",
        "url_custom_parameters",
        "urlCustomParameters",
        "parameters",
    ),
)

POSITIVE_KEYWORD_FIELD_BY_PATCH = {field.patch_name: field for field in POSITIVE_KEYWORD_FIELDS}
POSITIVE_KEYWORD_FIELD_BY_PROVIDER = {
    field.provider_name: field for field in POSITIVE_KEYWORD_FIELDS
}
POSITIVE_KEYWORD_MUTABLE_FIELD_PATHS = {
    field.provider_name: field.provider_name for field in POSITIVE_KEYWORD_FIELDS
}
