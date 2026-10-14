# apps/api/integrations/meta_ads/goals.py

"""Ad set goals as plain keys, each mapped to the one combination of Meta settings it means."""

from dataclasses import dataclass
from typing import Literal, get_args

type MetaAdsGoal = Literal[
    "reach",
    "impressions",
    "ad_recall_lift",
    "link_clicks",
    "landing_page_views",
    "post_engagement",
    "page_likes",
    "app_installs",
    "website_conversions",
]
type MetaAdsGoalAsset = Literal["page", "pixel", "app"]
# Which of Meta's minimum_budgets applies to the goal's daily budget.
type MetaAdsMinimumKind = Literal["imp", "high_freq", "low_freq"]
type MetaAdsConversionEvent = Literal[
    "PURCHASE",
    "LEAD",
    "COMPLETE_REGISTRATION",
    "ADD_TO_CART",
    "INITIATED_CHECKOUT",
    "CONTENT_VIEW",
    "SEARCH",
    "SUBSCRIBE",
    "START_TRIAL",
    "CONTACT",
]

GOAL_KEYS: tuple[MetaAdsGoal, ...] = get_args(MetaAdsGoal.__value__)


@dataclass(frozen=True, slots=True)
class GoalRow:
    objective: str
    optimization_goal: str
    destination_type: str | None
    # The asset Meta needs as the promoted object, if any.
    asset: MetaAdsGoalAsset | None
    minimum: MetaAdsMinimumKind
    # Whether "pay per click" can bill on link clicks instead of impressions.
    clicks_billing: bool = False


# Rows confirmed in Meta's objective mapping table. Step 0 dry runs add the reported ones.
GOALS: dict[MetaAdsGoal, GoalRow] = {
    "reach": GoalRow("OUTCOME_AWARENESS", "REACH", None, "page", "imp"),
    "impressions": GoalRow("OUTCOME_AWARENESS", "IMPRESSIONS", None, "page", "imp"),
    "ad_recall_lift": GoalRow("OUTCOME_AWARENESS", "AD_RECALL_LIFT", None, "page", "imp"),
    "link_clicks": GoalRow(
        "OUTCOME_TRAFFIC", "LINK_CLICKS", None, None, "high_freq", clicks_billing=True
    ),
    "landing_page_views": GoalRow("OUTCOME_TRAFFIC", "LANDING_PAGE_VIEWS", None, None, "high_freq"),
    "post_engagement": GoalRow(
        "OUTCOME_ENGAGEMENT", "POST_ENGAGEMENT", "ON_POST", None, "high_freq"
    ),
    "page_likes": GoalRow("OUTCOME_ENGAGEMENT", "PAGE_LIKES", "ON_PAGE", "page", "high_freq"),
    "app_installs": GoalRow("OUTCOME_APP_PROMOTION", "APP_INSTALLS", None, "app", "low_freq"),
    "website_conversions": GoalRow(
        "OUTCOME_SALES", "OFFSITE_CONVERSIONS", "WEBSITE", "pixel", "low_freq"
    ),
}


def goal_for(
    objective: str | None, optimization_goal: str | None, destination_type: str | None
) -> MetaAdsGoal | None:
    """Names the goal an existing ad set's settings match, or None for settings outside the table."""
    for key, row in GOALS.items():
        if (row.objective, row.optimization_goal) != (objective, optimization_goal):
            continue
        # Meta reads an ad set sent without a destination back as UNDEFINED or WEBSITE.
        if destination_type == row.destination_type or (
            row.destination_type is None and destination_type in (None, "UNDEFINED", "WEBSITE")
        ):
            return key
    return None
