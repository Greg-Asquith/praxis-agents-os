# apps/api/integrations/google_ads/operations/campaign_goals.py

"""Reads the conversion goals each campaign bids for, and builds the edits that change them."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .conversion_settings import goal_name
from .edits import FieldChange, SettingValues
from .utils import stream_rows

# The card's value for a campaign that bids for the account's goals, or for a custom goal.
ACCOUNT_GOALS = "account"
CUSTOM_GOAL = "custom"
_LEVEL_PATH = "goalConfigLevel"
_CUSTOM_PATH = "customConversionGoal"
_BIDDABLE_PATH = "biddable"
# A campaign has one goal per category and origin in its account; this only bounds the read.
_MAX_GOALS_PER_CAMPAIGN = 400

CUSTOM_GOAL_PROBLEM = (
    "This campaign bids for a custom goal, which can't change here. Change it in Google Ads."
)
NO_GOALS_PROBLEM = "Google Ads didn't return this campaign's conversion goals."


def _config_name(customer_id: str, campaign_id: str) -> str:
    return f"customers/{customer_id}/conversionGoalCampaignConfigs/{campaign_id}"


def _goal_prefix(customer_id: str, campaign_id: str) -> str:
    """The start of each of a campaign's goal names, which end `{category}~{origin}`."""
    return f"customers/{customer_id}/campaignConversionGoals/{campaign_id}~"


def level_edit(customer_id: str, campaign_id: str, requested: Any) -> FieldChange:
    """The edit that moves a campaign between the account's goals and its own."""
    return FieldChange(
        resource="conversionGoalCampaignConfig",
        resource_name=_config_name(customer_id, campaign_id),
        requested={_LEVEL_PATH: "CUSTOMER" if requested == ACCOUNT_GOALS else "CAMPAIGN"},
        compared=(_CUSTOM_PATH,),
        atomic_group=f"goals:{campaign_id}",
    )


@dataclass(frozen=True, slots=True)
class LiveCampaignGoals:
    """The goals one campaign bids for, and whether they're its own or the account's."""

    customer_id: str
    campaign_id: str
    # `CUSTOMER` while the campaign bids for the account's goals, `CAMPAIGN` for its own.
    level: str
    # A custom goal names conversion actions directly, so the goals here don't decide bidding.
    custom_goal: str | None
    # Whether each goal bids, by category and origin.
    biddable: Mapping[tuple[str, str], bool]

    def card(self) -> str | list[dict[str, str]]:
        """The setting in card terms: the account's goals, a custom goal, or the goals that bid."""
        if self.custom_goal:
            return CUSTOM_GOAL
        if self.level != "CAMPAIGN":
            return ACCOUNT_GOALS
        return [
            {"category": category, "origin": origin}
            for (category, origin), on in sorted(self.biddable.items())
            if on
        ]

    def options(self) -> list[dict[str, Any]]:
        """Every goal the campaign can bid for, named for the card, and whether it bids now."""
        return [
            {
                "category": category,
                "origin": origin,
                "name": goal_name(category, origin),
                "biddable": on,
            }
            for (category, origin), on in sorted(self.biddable.items())
        ]

    def values(self) -> dict[str, SettingValues]:
        """Each goal object's live values by resource name, as the edit seam compares them."""
        prefix = _goal_prefix(self.customer_id, self.campaign_id)
        values: dict[str, SettingValues] = {
            _config_name(self.customer_id, self.campaign_id): {
                _LEVEL_PATH: self.level,
                _CUSTOM_PATH: self.custom_goal,
            }
        }
        for (category, origin), on in self.biddable.items():
            values[f"{prefix}{category}~{origin}"] = {_BIDDABLE_PATH: on}
        return values

    def problem(self, requested: Any) -> str | None:
        """Why the campaign can't bid for the requested goals, if it can't."""
        if self.custom_goal:
            return CUSTOM_GOAL_PROBLEM
        if requested == ACCOUNT_GOALS:
            return None
        for goal in requested:
            if (goal["category"], goal["origin"]) not in self.biddable:
                name = goal_name(goal["category"], goal["origin"])
                return f"{name} isn't one of the account's conversion goals."
        return None

    def edits(self, requested: Any) -> list[FieldChange]:
        """The edits that leave the campaign bidding for the account's goals or exactly these.

        They share an atomic group, so a campaign never keeps only some of its goal changes.
        """
        level = level_edit(self.customer_id, self.campaign_id, requested)
        if requested == ACCOUNT_GOALS:
            return [level]
        chosen = {(goal["category"], goal["origin"]) for goal in requested}
        prefix = _goal_prefix(self.customer_id, self.campaign_id)
        return [
            level,
            *(
                FieldChange(
                    resource="campaignConversionGoal",
                    resource_name=f"{prefix}{category}~{origin}",
                    requested={_BIDDABLE_PATH: (category, origin) in chosen},
                    atomic_group=level.atomic_group,
                )
                for category, origin in sorted(self.biddable)
            ),
        ]


def goals_from_values(
    customer_id: str, campaign_id: str, values: Mapping[str, Any]
) -> LiveCampaignGoals | None:
    """Rebuilds a campaign's goals from `LiveCampaignGoals.values`; None when they aren't there."""
    config = values.get(_config_name(customer_id, campaign_id))
    if not isinstance(config, Mapping):
        return None
    prefix = _goal_prefix(customer_id, campaign_id)
    biddable: dict[tuple[str, str], bool] = {}
    for name, item in values.items():
        if name.startswith(prefix) and isinstance(item, Mapping):
            category, _, origin = name[len(prefix) :].partition("~")
            biddable[category, origin] = item.get(_BIDDABLE_PATH) is True
    custom = config.get(_CUSTOM_PATH)
    return LiveCampaignGoals(
        customer_id=customer_id,
        campaign_id=campaign_id,
        level=str(config.get(_LEVEL_PATH) or ""),
        custom_goal=custom if isinstance(custom, str) and custom else None,
        biddable=biddable,
    )


async def read_campaign_goals(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    campaign_ids: Sequence[str],
) -> dict[str, LiveCampaignGoals]:
    """Returns each campaign's goals by campaign ID. Google makes them; they can only be updated.

    Campaigns Google returns no goal settings for are left out.
    """
    if not campaign_ids or not all(item.isdigit() for item in campaign_ids):
        raise ValueError("Google Ads campaign goal reads need campaign IDs")
    customer = normalize_customer_id(customer_id)
    ids = sorted(set(campaign_ids))
    where = f"WHERE campaign.id IN ({', '.join(ids)})"

    async def rows(query: str, max_rows: int) -> list[dict[str, Any]]:
        payload = await client.post(
            f"customers/{customer}/googleAds:searchStream",
            operation="read_campaign_goals",
            policy=IntegrationRequestPolicy.READ,
            login_customer_id=login_customer_id,
            json={"query": f"{query} {where}"},
        )
        return stream_rows(payload, max_rows=max_rows)

    configs = await rows(
        "SELECT campaign.id, conversion_goal_campaign_config.goal_config_level, "
        "conversion_goal_campaign_config.custom_conversion_goal "
        "FROM conversion_goal_campaign_config",
        len(ids),
    )
    goals = await rows(
        "SELECT campaign.id, campaign_conversion_goal.category, "
        "campaign_conversion_goal.origin, campaign_conversion_goal.biddable "
        "FROM campaign_conversion_goal",
        len(ids) * _MAX_GOALS_PER_CAMPAIGN,
    )
    biddable: dict[str, dict[tuple[str, str], bool]] = {}
    for row in goals:
        goal = row.get("campaignConversionGoal")
        category = goal.get("category") if isinstance(goal, Mapping) else None
        origin = goal.get("origin") if isinstance(goal, Mapping) else None
        if isinstance(category, str) and isinstance(origin, str):
            campaign_goals = biddable.setdefault(_campaign_id(row), {})
            campaign_goals[category, origin] = goal.get("biddable") is True
    live: dict[str, LiveCampaignGoals] = {}
    for row in configs:
        config = row.get("conversionGoalCampaignConfig")
        campaign_id = _campaign_id(row)
        if not isinstance(config, Mapping) or campaign_id not in ids:
            continue
        custom = config.get("customConversionGoal")
        live[campaign_id] = LiveCampaignGoals(
            customer_id=customer,
            campaign_id=campaign_id,
            level=str(config.get("goalConfigLevel") or ""),
            custom_goal=custom if isinstance(custom, str) and custom else None,
            biddable=biddable.get(campaign_id, {}),
        )
    return live


def _campaign_id(row: Mapping[str, Any]) -> str:
    campaign = row.get("campaign")
    return str(campaign.get("id", "")) if isinstance(campaign, Mapping) else ""
