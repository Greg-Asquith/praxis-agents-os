# apps/api/integrations/meta_ads/operations/edit_campaign.py

"""Rules, reads, and the Meta request body for changing the settings of existing campaigns."""

import json
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation

from services.integrations.http import IntegrationRequestPolicy

from ..client import MetaAdsClient, ad_account_path
from ..money import amount_to_minor, minor_to_amount
from ..throttle import ensure_account_available
from ..tools.schemas.budgets import BID_STRATEGIES
from ..tools.schemas.campaign_edits import (
    MAX_BID_AD_SETS,
    MetaAdsCampaignEdit,
    MetaAdsCampaignSetting,
)
from ..tools.schemas.objects import CLOSED_STATUSES, OBJECT_STATUSES, MetaAdsObject
from .create_ad_set import BID_AMOUNT_STRATEGIES, LEGACY_ADVANTAGE_TYPES
from .edit_ad_set import LEGACY_ADVANTAGE
from .list_objects import NO_SPEND_CAP, list_objects
from .values import invalid_response

_ROAS = BID_STRATEGIES["roas_goal"]
_STRATEGY_KEYS = {meta: key for key, meta in BID_STRATEGIES.items()}
# Meta asks for a bid on every ad set that isn't deleted, archived ones included.
_LIVE_AD_SET_STATUSES = [status for status in OBJECT_STATUSES["adset"] if status != "DELETED"]
NO_LIMIT_NOTE = (
    "This campaign has no spending limit after this change. It spends until its budget or end "
    "date stops it."
)
SHARING_NOTE = "Budget sharing can't be turned back on once it's off."
BID_STRATEGY_WARNING = (
    "This restarts learning in every ad set in the campaign. Results may swing for a few days."
)


def campaign_values(
    item: MetaAdsObject, bids: Mapping[str, str | None] | None = None
) -> dict[str, str | None]:
    """Reads each setting the way an edit names it; None means not set.

    `bids` holds the current bid of each ad set the edit names, by ad set ID.
    """
    sharing = item.share_between_ad_sets
    return {
        "name": item.name,
        "spend_limit": item.spend_limit,
        "bid_strategy": _STRATEGY_KEYS.get(item.bid_strategy or "", item.bid_strategy),
        "ad_set_bids": bid_text(bids) if bids is not None else None,
        "share_between_ad_sets": None if sharing is None else str(sharing).lower(),
    }


def bid_text(bids: Mapping[str, str | None]) -> str:
    """Writes ad set bids in one form, so the bids shown, sent, and read back compare."""
    return json.dumps(dict(sorted(bids.items())), separators=(",", ":"))


def requested_values(
    edit: MetaAdsCampaignEdit, currency: str
) -> dict[MetaAdsCampaignSetting, str | None]:
    """The values the edit asks for, as `campaign_values` reads them; removing asks for None."""
    values: dict[MetaAdsCampaignSetting, str | None] = {}
    if edit.name is not None:
        values["name"] = edit.name
    if edit.spend_limit is not None:
        values["spend_limit"] = None if edit.spend_limit == "remove" else edit.spend_limit
    if edit.bid_strategy is not None:
        values["bid_strategy"] = edit.bid_strategy
    if edit.ad_set_bids:
        values["ad_set_bids"] = bid_text(
            {bid.ad_set.adset_id: _amount(bid.bid_amount, currency) for bid in edit.ad_set_bids}
        )
    if edit.share_between_ad_sets is not None:
        values["share_between_ad_sets"] = "false"
    return values


def _amount(value: str, currency: str) -> str:
    """Writes an amount the way Meta's reads show it, so bids compare as text."""
    return format(minor_to_amount(amount_to_minor(value, currency), currency), "f")


def edit_problems(
    edit: MetaAdsCampaignEdit,
    campaign: MetaAdsObject,
    ad_sets: Sequence[MetaAdsObject],
    *,
    currency: str,
    spent: str | None,
    minimum_spend_limit: str | None,
) -> list[str]:
    """Lists the Meta rules this edit breaks for the campaign and its ad sets as they are now."""
    if campaign.smart_promotion_type in LEGACY_ADVANTAGE_TYPES:
        return [LEGACY_ADVANTAGE]
    if campaign.status in CLOSED_STATUSES and set(edit.settings) - {"name"}:
        return ["This campaign is archived or deleted, so only its name can change."]
    amounts = [bid.bid_amount for bid in edit.ad_set_bids]
    if edit.spend_limit not in (None, "remove"):
        amounts.append(edit.spend_limit)
    try:
        for amount in amounts:
            amount_to_minor(amount, currency)
    except ValueError:
        return [f"Use whole {currency} amounts."]
    problems = _spend_limit_problems(edit, currency, spent, minimum_spend_limit)
    problems.extend(_bid_problems(edit, campaign, ad_sets))
    if edit.share_between_ad_sets is not None and campaign.budget is not None:
        problems.append(
            "This campaign holds the budget, so its ad sets don't share theirs. Leave "
            "share_between_ad_sets out."
        )
    return problems


def _spend_limit_problems(
    edit: MetaAdsCampaignEdit, currency: str, spent: str | None, minimum: str | None
) -> list[str]:
    limit = edit.spend_limit
    if limit is None or limit == "remove":
        return []
    if spent is not None and Decimal(limit) <= Decimal(spent):
        return [
            f"This campaign has spent {spent} {currency} so far, so set a spending limit above "
            "that."
        ]
    if minimum is not None and Decimal(limit) < Decimal(minimum):
        return [f"The smallest spending limit for this ad account is {minimum} {currency}."]
    return []


def _bid_problems(
    edit: MetaAdsCampaignEdit, campaign: MetaAdsObject, ad_sets: Sequence[MetaAdsObject]
) -> list[str]:
    if edit.bid_strategy is None:
        return []
    if campaign.budget is None:
        return [
            "This campaign's ad sets hold their own budgets, so each one sets its bid strategy. "
            "Change it with meta_ads_update_ad_sets."
        ]
    strategy = BID_STRATEGIES[edit.bid_strategy]
    if campaign.bid_strategy == _ROAS and strategy != _ROAS:
        return [
            "Meta doesn't let a campaign leave a return on ad spend goal. Copy the campaign or "
            "create a new one with another bid strategy."
        ]
    if strategy == _ROAS and campaign.bid_strategy != _ROAS:
        return ["Moving a campaign to a return on ad spend goal isn't available here yet."]
    if len(ad_sets) > MAX_BID_AD_SETS:
        return [
            f"This campaign has more than {MAX_BID_AD_SETS} ad sets, so Meta doesn't let its bid "
            "strategy change."
        ]
    named = {bid.ad_set.adset_id for bid in edit.ad_set_bids}
    if strategy not in BID_AMOUNT_STRATEGIES:
        if named:
            return ["This bid strategy doesn't take ad set bids, so leave ad_set_bids out."]
        return []
    if missing := [item.name or item.id for item in ad_sets if item.id not in named]:
        return [f"This bid strategy needs a bid on every ad set. Add one for {', '.join(missing)}."]
    if named - {item.id for item in ad_sets}:
        return ["Some ad_set_bids name ad sets that aren't in this campaign."]
    return []


def edit_body(edit: MetaAdsCampaignEdit, *, currency: str) -> dict[str, str]:
    """Builds the update Meta receives, with money in minor units."""
    body: dict[str, str] = {}
    if edit.name is not None:
        body["name"] = edit.name
    if (limit := edit.spend_limit) is not None:
        body["spend_cap"] = str(
            NO_SPEND_CAP if limit == "remove" else amount_to_minor(limit, currency)
        )
    if edit.bid_strategy is not None:
        body["bid_strategy"] = BID_STRATEGIES[edit.bid_strategy]
    if edit.ad_set_bids:
        body["adset_bid_amounts"] = json.dumps(
            {
                bid.ad_set.adset_id: amount_to_minor(bid.bid_amount, currency)
                for bid in edit.ad_set_bids
            }
        )
    if edit.share_between_ad_sets is not None:
        body["is_adset_budget_sharing_enabled"] = "false"
    return body


def edit_notes(edit: MetaAdsCampaignEdit, campaign: MetaAdsObject) -> tuple[list[str], list[str]]:
    """Returns the warnings and notes the card shows for one campaign edit."""
    warnings: list[str] = []
    notes: list[str] = []
    if edit.bid_strategy is not None and BID_STRATEGIES[edit.bid_strategy] != campaign.bid_strategy:
        warnings.append(BID_STRATEGY_WARNING)
    if edit.spend_limit == "remove":
        notes.append(NO_LIMIT_NOTE)
    if edit.share_between_ad_sets is not None:
        notes.append(SHARING_NOTE)
    return warnings, notes


def evidence_values(values: Mapping[str, str | None], currency: str) -> dict[str, object]:
    """Records money in minor units, so the audit trail matches what Meta receives."""
    evidence: dict[str, object] = {}
    for key, value in values.items():
        if key == "spend_limit" and value is not None:
            evidence[key] = str(amount_to_minor(value, currency))
        elif key == "ad_set_bids" and value is not None:
            evidence[key] = {
                adset_id: None if bid is None else str(amount_to_minor(bid, currency))
                for adset_id, bid in json.loads(value).items()
            }
        else:
            evidence[key] = value
    return evidence


async def read_ad_sets(
    client: MetaAdsClient, *, account_id: str, currency: str, campaign_ids: Sequence[str]
) -> dict[str, list[MetaAdsObject]]:
    """Lists each campaign's ad sets that aren't deleted, by campaign ID."""
    found: dict[str, list[MetaAdsObject]] = {key: [] for key in campaign_ids}
    for start in range(0, len(campaign_ids), 50):
        ad_sets = await list_objects(
            client,
            account_id=account_id,
            object_type="adset",
            campaign_ids=list(campaign_ids[start : start + 50]),
            statuses=_LIVE_AD_SET_STATUSES,
            limit=500,
            currency=currency,
        )
        for item in ad_sets.objects:
            if item.campaign_id in found:
                found[item.campaign_id].append(item)
    return found


async def read_lifetime_spend(
    client: MetaAdsClient, *, account_id: str, campaign_ids: Sequence[str], operation: str
) -> dict[str, str]:
    """Returns what each campaign has spent over its life, in the account currency."""
    spent = dict.fromkeys(campaign_ids, "0")
    for start in range(0, len(campaign_ids), 50):
        chunk = list(campaign_ids[start : start + 50])
        ensure_account_available(account_id, operation=operation)
        payload = await client.graph_get(
            f"{ad_account_path(account_id)}/insights",
            params={
                "level": "campaign",
                "fields": "campaign_id,spend",
                "date_preset": "maximum",
                "filtering": json.dumps(
                    [{"field": "campaign.id", "operator": "IN", "value": chunk}]
                ),
                "limit": str(len(chunk)),
            },
            operation=operation,
            policy=IntegrationRequestPolicy.READ,
            usage_account_id=account_id,
        )
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise invalid_response("Meta Ads returned invalid spend.", operation=operation)
        for row in rows:
            key = row.get("campaign_id") if isinstance(row, dict) else None
            if key in spent:
                spent[key] = _spend(row.get("spend"), operation)
    return spent


def _spend(value: object, operation: str) -> str:
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise invalid_response("Meta Ads returned invalid spend.", operation=operation) from None
    if not amount.is_finite() or amount < 0:
        raise invalid_response("Meta Ads returned invalid spend.", operation=operation)
    return format(amount, "f")
