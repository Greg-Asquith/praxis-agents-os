# apps/api/integrations/google_ads/tools/utils/ad_group_builds.py

"""Rules and evidence shared by the tools that build new Search ad groups."""

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from ...operations.search_ad_groups import AdGroupItem, SearchCampaignFacts

if TYPE_CHECKING:
    from ..schemas.ad_groups import GoogleAdsNewAdGroup

# Keeps a build at the object limit inside one audit event, whatever alphabet the keywords use.
MAX_AUDIT_ITEM_CHARS = 40
STRATEGY_NAMES = {
    "MANUAL_CPC": "Manual CPC",
    "ENHANCED_CPC": "Enhanced CPC",
    "MAXIMIZE_CONVERSIONS": "Maximise Conversions",
    "MAXIMIZE_CONVERSION_VALUE": "Maximise Conversion Value",
    "TARGET_CPA": "Target CPA",
    "TARGET_ROAS": "Target ROAS",
    "TARGET_SPEND": "Maximise Clicks",
    "TARGET_IMPRESSION_SHARE": "Target Impression Share",
}


def ad_group_problems(ad_group: "GoogleAdsNewAdGroup", facts: SearchCampaignFacts) -> list[str]:
    """Why Google would refuse or ignore this ad group's name or bids."""
    strategy = STRATEGY_NAMES.get(facts.strategy, "its own bidding")
    uses = f"the campaign uses {strategy}"
    problems = []
    if ad_group.name.casefold() in {name.casefold() for name in facts.ad_group_names}:
        problems.append(f"{ad_group.name}: the campaign already has an ad group with this name.")
    if ad_group.cpc_bid and not facts.accepts_cpc_bid:
        problems.append(f"{ad_group.name}: has a click bid, but {uses}.")
    if any(keyword.cpc_bid for keyword in ad_group.keywords) and not facts.accepts_cpc_bid:
        problems.append(f"{ad_group.name}: has keyword click bids, but {uses}.")
    if ad_group.target_cpa and not facts.accepts_target_cpa:
        problems.append(f"{ad_group.name}: has a target CPA that {strategy} doesn't use here.")
    if ad_group.target_roas is not None and not facts.accepts_target_roas:
        problems.append(f"{ad_group.name}: has a target ROAS that {strategy} doesn't use here.")
    return problems


def ad_group_item_fields(
    ad_groups: Sequence["GoogleAdsNewAdGroup"], source: AdGroupItem
) -> dict[str, Any]:
    """Names a rejected item by its content, because the card can reorder and cancel ad groups."""
    ad_group = ad_groups[source.ad_group]
    fields: dict[str, Any] = {"ad_group": ad_group.name, "kind": source.kind}
    if source.kind == "keyword":
        keyword = ad_group.keywords[source.position]
        fields |= {"text": keyword.text, "match_type": keyword.match_type}
    elif source.kind == "negative_keyword":
        negative = ad_group.negative_keywords[source.position]
        fields |= {"text": negative.text, "match_type": negative.match_type}
    elif source.kind == "ad":
        fields["ad"] = ad_group.ads[source.position].model_dump(mode="json")
    return fields
