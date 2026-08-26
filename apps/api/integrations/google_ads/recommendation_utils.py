"""Shared parsing and projection helpers for Google Ads recommendations."""

import re
from collections.abc import Mapping
from typing import Any

_RECOMMENDATION_RESOURCE_PATTERN = re.compile(
    r"^customers/(?P<customer_id>\d{1,32})/recommendations/[A-Za-z0-9_.~-]{1,256}$"
)
_CAMPAIGN_RESOURCE_PATTERN = re.compile(
    r"^customers/(?P<customer_id>\d{1,32})/campaigns/(?P<campaign_id>\d{1,32})$"
)
_AD_GROUP_RESOURCE_PATTERN = re.compile(r"^customers/(?P<customer_id>\d{1,32})/adGroups/\d{1,32}$")


def recommendation_customer_id(resource_name: str) -> str | None:
    """Return the customer ID from one valid recommendation resource name."""
    match = _RECOMMENDATION_RESOURCE_PATTERN.fullmatch(resource_name)
    return match.group("customer_id") if match is not None else None


def ad_group_customer_id(resource_name: str) -> str | None:
    """Return the customer ID from one valid ad group resource name."""
    match = _AD_GROUP_RESOURCE_PATTERN.fullmatch(resource_name)
    return match.group("customer_id") if match is not None else None


def affected_campaigns(recommendation: Mapping[str, Any]) -> tuple[str, ...]:
    """Return unique valid campaign resource names in provider order."""
    values: list[str] = []
    campaign = recommendation.get("campaign")
    if isinstance(campaign, str) and campaign:
        values.append(campaign)
    campaigns = recommendation.get("campaigns")
    if isinstance(campaigns, list):
        values.extend(value for value in campaigns if isinstance(value, str) and value)
    return tuple(
        dict.fromkeys(value for value in values if _CAMPAIGN_RESOURCE_PATTERN.fullmatch(value))
    )


def affected_campaign_label(recommendation: Mapping[str, Any]) -> str | None:
    """Return the bounded campaign label attached by the recommendation query."""
    value = recommendation.get("affectedCampaignLabel")
    normalized = value.strip() if isinstance(value, str) else ""
    return normalized[:500] or None


def recommendation_type_label(value: str) -> str:
    """Format a provider recommendation enum as a compact display label."""
    return value.replace("_", " ").title()
