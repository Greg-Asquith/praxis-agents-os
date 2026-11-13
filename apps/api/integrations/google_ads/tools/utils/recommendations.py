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


# Per type: Google's detail message, the setting, and the detail's current and recommended fields.
_CHANGES: dict[str, tuple[str, str, str, str]] = {
    "RAISE_TARGET_CPA_PERFORMANCE_BID_TOO_LOW": (
        "raiseTargetCpaPerformanceBidTooLowRecommendation",
        "target_cpa",
        "currentAverageTargetCpaMicros",
        "recommendedTargetMultiplier",
    ),
    "LOWER_TARGET_ROAS_PERFORMANCE_BID_TOO_LOW": (
        "lowerTargetRoasPerformanceBidTooLowRecommendation",
        "target_roas",
        "currentAverageTargetRoas",
        "recommendedTargetMultiplier",
    ),
    "RAISE_BUDGET_PERFORMANCE_TOO_LOW": (
        "raiseBudgetPerformanceTooLowRecommendation",
        "daily_budget",
        "currentBudgetAmountMicros",
        "recommendedBudgetAmountMicros",
    ),
}
_REQUESTED_FIELDS = {
    "target_cpa": "target_cpa_multiplier",
    "target_roas": "target_roas_multiplier",
    "daily_budget": "new_budget_amount_micros",
}
_MICROS_PER_UNIT = 1_000_000


def recommendation_change(
    recommendation: Mapping[str, Any], parameter: Any = None, *, currency: str | None
) -> dict[str, Any] | None:
    """Returns the setting a bid or budget recommendation changes, now and after applying.

    Money is in units of `currency`, the account's, and target ROAS is a ratio. `after` is
    the value `parameter` asks for, or Google's recommended value without one. None for a
    type that doesn't change one setting, or when Google leaves a value out.
    """
    fields = _CHANGES.get(str(recommendation.get("type")))
    if fields is None:
        return None
    detail_key, setting, now_key, recommended_key = fields
    detail = recommendation.get(detail_key)
    if not isinstance(detail, Mapping):
        return None
    try:
        now = float(detail[now_key])
        requested = getattr(parameter, _REQUESTED_FIELDS[setting], None)
        proposed = float(detail[recommended_key] if requested is None else requested)
    except (KeyError, TypeError, ValueError):
        return None
    if setting == "daily_budget":
        return {
            "setting": setting,
            "now": now / _MICROS_PER_UNIT,
            "after": proposed / _MICROS_PER_UNIT,
            "currency": currency,
        }
    # Google recommends and takes a multiplier on the current target, not a new target.
    if setting == "target_cpa":
        now /= _MICROS_PER_UNIT
        return {"setting": setting, "now": now, "after": now * proposed, "currency": currency}
    return {"setting": setting, "now": now, "after": now * proposed, "currency": None}
