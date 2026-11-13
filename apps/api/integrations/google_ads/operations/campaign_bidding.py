# apps/api/integrations/google_ads/operations/campaign_bidding.py

"""A campaign's bidding in card and API terms, and what a bidding change sends and affects."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .utils import stream_rows

# Card terms: `{"strategy": ..., ...}` with only that strategy's own fields. Money is a decimal
# string in the account currency, target ROAS a ratio (3.5 is 350%), and impression share a
# whole percentage. `TARGET_CPA`, `TARGET_ROAS`, and `OTHER` (with Google's `type`) are only
# ever read; a request can also be `TARGETS`, changing targets on the current strategy.
type Bidding = dict[str, Any]

STANDARD_STRATEGIES = (
    "MANUAL_CPC",
    "MAXIMIZE_CLICKS",
    "MAXIMIZE_CONVERSIONS",
    "MAXIMIZE_CONVERSION_VALUE",
    "TARGET_IMPRESSION_SHARE",
)
STRATEGY_NAMES = {
    "MANUAL_CPC": "Manual CPC",
    "MAXIMIZE_CLICKS": "Maximise Clicks",
    "MAXIMIZE_CONVERSIONS": "Maximise Conversions",
    "MAXIMIZE_CONVERSION_VALUE": "Maximise Conversion Value",
    "TARGET_IMPRESSION_SHARE": "Target Impression Share",
    "TARGET_CPA": "Target CPA",
    "TARGET_ROAS": "Target ROAS",
    "PORTFOLIO": "Portfolio strategies",
}
# The campaign field for each strategy (members of Google's bidding oneof), and the fields
# inside it that a card value holds, in Google's JSON names.
_MESSAGES = {
    "MANUAL_CPC": ("manualCpc", ()),
    "MAXIMIZE_CLICKS": ("targetSpend", ("cpcBidCeilingMicros",)),
    "MAXIMIZE_CONVERSIONS": ("maximizeConversions", ("targetCpaMicros",)),
    "MAXIMIZE_CONVERSION_VALUE": ("maximizeConversionValue", ("targetRoas",)),
    "TARGET_IMPRESSION_SHARE": (
        "targetImpressionShare",
        ("location", "locationFractionMicros", "cpcBidCeilingMicros"),
    ),
    "TARGET_CPA": ("targetCpa", ("targetCpaMicros",)),
    "TARGET_ROAS": ("targetRoas", ("targetRoas",)),
}
# Google's `bidding_strategy_type` for each strategy a card names.
_TYPES = {
    "MANUAL_CPC": "MANUAL_CPC",
    "MAXIMIZE_CLICKS": "TARGET_SPEND",
    "MAXIMIZE_CONVERSIONS": "MAXIMIZE_CONVERSIONS",
    "MAXIMIZE_CONVERSION_VALUE": "MAXIMIZE_CONVERSION_VALUE",
    "TARGET_IMPRESSION_SHARE": "TARGET_IMPRESSION_SHARE",
    "TARGET_CPA": "TARGET_CPA",
    "TARGET_ROAS": "TARGET_ROAS",
}
_STRATEGIES = {value: key for key, value in _TYPES.items()}
# Where Google offers each standard strategy, from the v26 bidding strategy types table.
_CHANNELS = {
    "MANUAL_CPC": frozenset({"SEARCH", "DISPLAY", "SHOPPING"}),
    "MAXIMIZE_CLICKS": frozenset({"SEARCH", "DISPLAY", "SHOPPING"}),
    "MAXIMIZE_CONVERSIONS": frozenset(
        {"SEARCH", "DISPLAY", "VIDEO", "DEMAND_GEN", "PERFORMANCE_MAX", "MULTI_CHANNEL"}
    ),
    "MAXIMIZE_CONVERSION_VALUE": frozenset(
        {"SEARCH", "DISPLAY", "SHOPPING", "DEMAND_GEN", "PERFORMANCE_MAX"}
    ),
    "TARGET_IMPRESSION_SHARE": frozenset({"SEARCH"}),
    "PORTFOLIO": frozenset({"SEARCH", "DISPLAY", "SHOPPING", "PERFORMANCE_MAX"}),
}
_CHANNEL_NAMES = {
    "DEMAND_GEN": "Demand Gen",
    "MULTI_CHANNEL": "App",
    "PERFORMANCE_MAX": "Performance Max",
}
# Which current strategies each target in a `TARGETS` request changes.
_TARGET_STRATEGIES = {
    "target_cpa": frozenset({"MAXIMIZE_CONVERSIONS", "TARGET_CPA"}),
    "target_roas": frozenset({"MAXIMIZE_CONVERSION_VALUE", "TARGET_ROAS"}),
    "max_cpc": frozenset({"MAXIMIZE_CLICKS", "TARGET_IMPRESSION_SHARE"}),
}
_TARGET_NEEDS = {
    "target_cpa": "Target CPA needs Maximise Conversions.",
    "target_roas": "Target ROAS needs Maximise Conversion Value.",
    "max_cpc": "A maximum click bid needs Maximise Clicks or Target Impression Share.",
}
_CHANGE_OR_CANCEL = " Change the strategy or cancel this change."
_PORTFOLIO_TARGETS = (
    "This campaign uses a portfolio strategy, so its targets change on the strategy, not here."
)
_CONVERSION_STRATEGIES = frozenset(
    {"MAXIMIZE_CONVERSIONS", "MAXIMIZE_CONVERSION_VALUE", "TARGET_CPA", "TARGET_ROAS"}
)
_MANUAL = frozenset({"MANUAL_CPC"})
_MAX_AD_GROUPS_READ = 10_000
_MAX_NAMED = 5

# What a campaign read selects so `bidding_values` can describe its bidding.
BIDDING_FIELDS = (
    "campaign.bidding_strategy_type",
    "campaign.bidding_strategy",
    "campaign.manual_cpc.enhanced_cpc_enabled",
    "campaign.target_spend.cpc_bid_ceiling_micros",
    "campaign.maximize_conversions.target_cpa_micros",
    "campaign.maximize_conversion_value.target_roas",
    "campaign.target_impression_share.location",
    "campaign.target_impression_share.location_fraction_micros",
    "campaign.target_impression_share.cpc_bid_ceiling_micros",
    "campaign.target_cpa.target_cpa_micros",
    "campaign.target_roas.target_roas",
)
# Read-only paths a bidding change is approved against but never sends, so a strategy changed
# by someone else since approval is refused rather than replaced.
BIDDING_GUARDS = ("biddingStrategyType", "biddingStrategy")


def money(micros: Any) -> str | None:
    """Micros as a canonical decimal string, or None for none or zero."""
    try:
        value = int(micros)
    except (TypeError, ValueError):
        return None
    return format(Decimal(value) / Decimal(1_000_000), "f") if value > 0 else None


def micros(value: str) -> str:
    """A canonical decimal amount as Google's int64 micros string."""
    return str(int(Decimal(value) * Decimal(1_000_000)))


def ratio(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _message(
    campaign: Mapping[str, Any], name: str, fields: Sequence[str]
) -> dict[str, Any] | None:
    """One oneof member with only the fields a card holds; zero targets count as unset."""
    raw = campaign.get(name)
    if not isinstance(raw, Mapping):
        return None
    message: dict[str, Any] = {}
    for field in fields:
        value = raw.get(field)
        if field == "location":
            if isinstance(value, str) and value:
                message[field] = value
        elif field == "targetRoas":
            if (target := ratio(value)) is not None:
                message[field] = target
        elif (amount := money(value)) is not None:
            message[field] = micros(amount)
    return message


def bidding_values(campaign: Mapping[str, Any]) -> dict[str, Any]:
    """Each bidding path's live value: the strategy's whole field, and each field inside it."""
    values: dict[str, Any] = {
        "biddingStrategyType": campaign.get("biddingStrategyType") or None,
        "biddingStrategy": campaign.get("biddingStrategy") or None,
    }
    for name, fields in _MESSAGES.values():
        message = _message(campaign, name, fields)
        values[name] = message
        for field in fields:
            values[f"{name}.{field}"] = message.get(field) if message else None
    return values


def card_bidding(values: Mapping[str, Any]) -> Bidding:
    """The campaign's bidding in card terms, from `bidding_values`."""
    portfolio = values.get("biddingStrategy")
    if isinstance(portfolio, str) and portfolio:
        return {"strategy": "PORTFOLIO", "portfolio": portfolio}
    kind = str(values.get("biddingStrategyType") or "")
    strategy = _STRATEGIES.get(kind)
    if strategy is None:
        return {"strategy": "OTHER", "type": kind or None}
    name, _fields = _MESSAGES[strategy]
    message = values.get(name) if isinstance(values.get(name), Mapping) else {}
    if strategy == "MAXIMIZE_CLICKS":
        return {"strategy": strategy, "max_cpc": money(message.get("cpcBidCeilingMicros"))}
    if strategy in {"MAXIMIZE_CONVERSIONS", "TARGET_CPA"}:
        return {"strategy": strategy, "target_cpa": money(message.get("targetCpaMicros"))}
    if strategy in {"MAXIMIZE_CONVERSION_VALUE", "TARGET_ROAS"}:
        return {"strategy": strategy, "target_roas": ratio(message.get("targetRoas"))}
    if strategy == "TARGET_IMPRESSION_SHARE":
        fraction = message.get("locationFractionMicros")
        return {
            "strategy": strategy,
            "location": message.get("location"),
            "share_percent": int(fraction) // 10_000 if fraction else None,
            "max_cpc": money(message.get("cpcBidCeilingMicros")),
        }
    return {"strategy": strategy}


def resolved_bidding(requested: Bidding, current: Bidding) -> tuple[Bidding, str | None]:
    """A request as the strategy it leaves the campaign on, and why it can't apply, if so.

    A `TARGETS` request keeps the current strategy and changes only the targets it names.
    """
    if requested.get("strategy") != "TARGETS":
        return requested, None
    if current.get("strategy") == "PORTFOLIO":
        return current, _PORTFOLIO_TARGETS
    resolved = dict(current)
    for target, strategies in _TARGET_STRATEGIES.items():
        if target not in requested:
            continue
        if current.get("strategy") not in strategies:
            return current, _TARGET_NEEDS[target] + _CHANGE_OR_CANCEL
        resolved[target] = requested[target]
    return resolved, None


def strategy_problem(bidding: Bidding, channel: str) -> str | None:
    """Refuses a strategy Google doesn't offer on the campaign's channel."""
    strategy = str(bidding.get("strategy"))
    channels = _CHANNELS.get(strategy)
    if channels is None or channel in channels:
        return None
    place = _CHANNEL_NAMES.get(channel, channel.replace("_", " ").title())
    return f"Google Ads doesn't offer {STRATEGY_NAMES[strategy]} on {place} campaigns."


def bidding_paths(requested: Bidding, current: Bidding) -> dict[str, Any]:
    """What a resolved bidding request sends, by path, in Google's terms.

    Google refuses a mask naming a strategy field that has subfields set, so a change names
    each field inside the strategy. Staying on the same strategy names every field, so the edit
    seam sends only the targets that differ and clears a removed one. Moving to another
    strategy names the fields it sets, or the bare strategy field when it sets none, such as
    Manual CPC. Either move takes the campaign off its current strategy, portfolio included.
    """
    strategy = str(requested["strategy"])
    if strategy == "PORTFOLIO":
        return {"biddingStrategy": requested["portfolio"]}
    name, fields = _MESSAGES[strategy]
    message = _message({name: _api_message(requested)}, name, fields) or {}
    if strategy == current.get("strategy") and fields:
        return {f"{name}.{field}": message.get(field) for field in fields}
    if not message:
        return {name: {}}
    return {f"{name}.{field}": value for field, value in message.items()}


def _api_message(bidding: Bidding) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if bidding.get("target_cpa"):
        fields["targetCpaMicros"] = micros(bidding["target_cpa"])
    if bidding.get("target_roas") is not None:
        fields["targetRoas"] = bidding["target_roas"]
    if bidding.get("max_cpc"):
        fields["cpcBidCeilingMicros"] = micros(bidding["max_cpc"])
    if bidding.get("location"):
        fields["location"] = bidding["location"]
    if bidding.get("share_percent") is not None:
        fields["locationFractionMicros"] = str(int(bidding["share_percent"]) * 10_000)
    return fields


def changes_strategy(requested: Bidding, current: Bidding) -> bool:
    """Whether the change moves to another strategy, which restarts Google's learning."""
    if requested.get("strategy") == "PORTFOLIO" or current.get("strategy") == "PORTFOLIO":
        return requested.get("portfolio") != current.get("portfolio")
    return requested.get("strategy") != current.get("strategy")


def needs_conversions(bidding: Bidding, portfolio_type: str | None = None) -> bool:
    strategy = bidding.get("strategy")
    if strategy == "PORTFOLIO":
        return _STRATEGIES.get(portfolio_type or "") in _CONVERSION_STRATEGIES
    return strategy in _CONVERSION_STRATEGIES


# An ad group bid field: its default CPC bid, or its target CPA or target ROAS override.
type AdGroupBid = Literal["cpc_bid", "target_cpa", "target_roas"]
_MANUAL_TYPES = frozenset({"MANUAL_CPC", "ENHANCED_CPC"})


def ad_group_bids_used(
    strategy_type: str, *, portfolio: bool, has_target_cpa: bool, has_target_roas: bool
) -> frozenset[AdGroupBid]:
    """Returns the ad group bid fields Google uses under a campaign's bidding.

    Only manual bidding uses CPC bids. A portfolio's own targets aren't read, so a target CPA
    override under a Maximise Conversions portfolio is left to Google, which refuses a target
    ROAS override under any portfolio.
    """
    used: set[AdGroupBid] = set()
    if strategy_type in _MANUAL_TYPES and not portfolio:
        used.add("cpc_bid")
    if strategy_type == "TARGET_CPA" or (
        strategy_type == "MAXIMIZE_CONVERSIONS" and (portfolio or has_target_cpa)
    ):
        used.add("target_cpa")
    if not portfolio and (
        strategy_type == "TARGET_ROAS"
        or (strategy_type == "MAXIMIZE_CONVERSION_VALUE" and has_target_roas)
    ):
        used.add("target_roas")
    return frozenset(used)


@dataclass(frozen=True, slots=True)
class AdGroupBids:
    """A campaign's live ad groups with their own bids or targets."""

    # Ad groups with their own target CPA or target ROAS.
    targets: tuple[str, ...] = ()
    # Ad groups with a CPC bid, which only manual bidding uses.
    cpc_bids: tuple[str, ...] = ()


def bidding_notes(
    requested: Bidding,
    current: Bidding,
    *,
    ad_groups: AdGroupBids,
    conversions: float | None,
    portfolio_type: str | None = None,
) -> list[str]:
    """What a strategy change does to the campaign's ad groups, and its recent conversions."""
    notes: list[str] = []
    if conversions is not None and needs_conversions(requested, portfolio_type):
        count = f"{conversions:,.1f}".removesuffix(".0")
        noun = "conversion" if count == "1" else "conversions"
        notes.append(f"{count} {noun} in the last 30 days.")
    if ad_groups.targets:
        verb = "has its" if len(ad_groups.targets) == 1 else "have their"
        notes.append(
            f"{_count(ad_groups.targets)} {verb} own targets: {_names(ad_groups.targets)}."
        )
    was_manual = current.get("strategy") in _MANUAL
    if ad_groups.cpc_bids and was_manual and requested.get("strategy") not in _MANUAL:
        notes.append(
            f"Google sets bids itself, so the CPC bids on {_count(ad_groups.cpc_bids)} stop "
            "being used."
        )
    if ad_groups.cpc_bids and not was_manual and requested.get("strategy") in _MANUAL:
        notes.append(
            f"Manual CPC bids each ad group's own CPC bid. Check them on "
            f"{_count(ad_groups.cpc_bids)}: {_names(ad_groups.cpc_bids)}."
        )
    return notes


def _count(names: Sequence[str]) -> str:
    return f"{len(names):,} ad group{'' if len(names) == 1 else 's'}"


def _names(names: Sequence[str]) -> str:
    shown = ", ".join(names[:_MAX_NAMED])
    more = len(names) - _MAX_NAMED
    return f"{shown}, and {more:,} more" if more > 0 else shown


async def read_ad_group_bids(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    campaign_ids: Sequence[str],
) -> dict[str, AdGroupBids]:
    """Returns each campaign's ad groups with their own bids or targets, by campaign ID."""
    if not campaign_ids or not all(item.isdigit() for item in campaign_ids):
        raise ValueError("Google Ads ad group bid reads need campaign IDs")
    ids = ", ".join(sorted(set(campaign_ids)))
    payload = await client.post(
        f"customers/{normalize_customer_id(customer_id)}/googleAds:searchStream",
        operation="read_ad_group_bids",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={
            "query": (
                "SELECT campaign.id, ad_group.name, ad_group.cpc_bid_micros, "  # noqa: S608 -- digits only
                "ad_group.target_cpa_micros, ad_group.target_roas FROM ad_group "
                f"WHERE campaign.id IN ({ids}) AND ad_group.status != 'REMOVED' "
                f"ORDER BY ad_group.id LIMIT {_MAX_AD_GROUPS_READ}"
            )
        },
    )
    targets: dict[str, list[str]] = {}
    cpc_bids: dict[str, list[str]] = {}
    for row in stream_rows(payload, max_rows=_MAX_AD_GROUPS_READ):
        campaign, ad_group = row.get("campaign"), row.get("adGroup")
        if not isinstance(campaign, Mapping) or not isinstance(ad_group, Mapping):
            continue
        key, name = str(campaign.get("id", "")), str(ad_group.get("name") or "Unnamed ad group")
        if money(ad_group.get("targetCpaMicros")) or ratio(ad_group.get("targetRoas")):
            targets.setdefault(key, []).append(name)
        if money(ad_group.get("cpcBidMicros")):
            cpc_bids.setdefault(key, []).append(name)
    return {
        key: AdGroupBids(tuple(targets.get(key, ())), tuple(cpc_bids.get(key, ())))
        for key in {*targets, *cpc_bids}
    }


async def read_conversions(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    campaign_ids: Sequence[str],
) -> dict[str, float]:
    """Returns each campaign's conversions over the last 30 days, by campaign ID."""
    if not campaign_ids or not all(item.isdigit() for item in campaign_ids):
        raise ValueError("Google Ads conversion reads need campaign IDs")
    ids = ", ".join(sorted(set(campaign_ids)))
    payload = await client.post(
        f"customers/{normalize_customer_id(customer_id)}/googleAds:searchStream",
        operation="read_campaign_conversions",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={
            "query": (
                "SELECT campaign.id, metrics.conversions FROM campaign "  # noqa: S608 -- digits only
                f"WHERE campaign.id IN ({ids}) AND segments.date DURING LAST_30_DAYS"
            )
        },
    )
    conversions: dict[str, float] = {}
    for row in stream_rows(payload, max_rows=len(set(campaign_ids))):
        campaign, metrics = row.get("campaign"), row.get("metrics")
        if isinstance(campaign, Mapping) and isinstance(metrics, Mapping):
            conversions[str(campaign.get("id", ""))] = ratio(metrics.get("conversions")) or 0.0
    return conversions
