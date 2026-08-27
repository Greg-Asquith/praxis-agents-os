# apps/api/integrations/google_ads/tools/utils/recommendations.py

"""Result projection helpers for Google Ads recommendation tools."""

import re
from collections.abc import Mapping
from typing import Any

_CAMPAIGN_RESOURCE_PATTERN = re.compile(r"^customers/\d{1,32}/campaigns/\d{1,32}$")


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
