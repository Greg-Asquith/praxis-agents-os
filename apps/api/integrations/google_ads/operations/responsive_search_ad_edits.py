# apps/api/integrations/google_ads/operations/responsive_search_ad_edits.py

"""Reads live responsive search ads and merges copy edits into them, in card and API terms."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TypedDict

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .list_ads import ad_display_name
from .utils import stream_rows

# Google's bounds for a responsive search ad.
HEADLINES = (3, 15)
DESCRIPTIONS = (2, 4)
RESPONSIVE_SEARCH_AD = "RESPONSIVE_SEARCH_AD"

# The paths the edit seam compares and masks, in Google's JSON names.
HEADLINES_PATH = "responsiveSearchAd.headlines"
DESCRIPTIONS_PATH = "responsiveSearchAd.descriptions"
PATH_PATHS = {"path1": "responsiveSearchAd.path1", "path2": "responsiveSearchAd.path2"}
FINAL_URLS_PATH = "finalUrls"

_AD_GROUP_AD = re.compile(r"customers/\d+/adGroupAds/\d+~\d+")
_FIELDS = (
    "ad_group_ad.resource_name",
    "ad_group_ad.status",
    "ad_group_ad.policy_summary.approval_status",
    "ad_group_ad.ad.resource_name",
    "ad_group_ad.ad.id",
    "ad_group_ad.ad.name",
    "ad_group_ad.ad.type",
    "ad_group_ad.ad.final_urls",
    "ad_group_ad.ad.responsive_search_ad.headlines",
    "ad_group_ad.ad.responsive_search_ad.descriptions",
    "ad_group_ad.ad.responsive_search_ad.path1",
    "ad_group_ad.ad.responsive_search_ad.path2",
    "ad_group.status",
    "ad_group.name",
    "campaign.status",
    "campaign.name",
)


class TextAsset(TypedDict):
    text: str
    pin: str | None


class AdCopy(TypedDict):
    """An ad's copy and links in card terms: no path is null, and one final URL."""

    headlines: list[TextAsset]
    descriptions: list[TextAsset]
    path1: str | None
    path2: str | None
    final_url: str | None


@dataclass(frozen=True, slots=True)
class LiveAd:
    """One ad as Google holds it, with its ad group and campaign for the card."""

    ad_resource_name: str
    type: str
    # REMOVED when the ad, its ad group, or its campaign is removed.
    status: str
    approval_status: str | None
    name: str
    ad_group_name: str
    campaign_name: str
    # Google's values by edit path, for the edit seam.
    values: Mapping[str, Any]

    def copy(self) -> AdCopy:
        return card_copy(self.values)


def card_copy(values: Mapping[str, Any]) -> AdCopy:
    """Converts an ad's values by edit path to card terms."""
    urls = values.get(FINAL_URLS_PATH) or []
    return {
        "headlines": [_card_asset(item) for item in values.get(HEADLINES_PATH) or ()],
        "descriptions": [_card_asset(item) for item in values.get(DESCRIPTIONS_PATH) or ()],
        "path1": values.get(PATH_PATHS["path1"]) or None,
        "path2": values.get(PATH_PATHS["path2"]) or None,
        "final_url": urls[0] if urls else None,
    }


def api_values(copy: AdCopy) -> dict[str, Any]:
    """Converts an ad's copy to Google's values by edit path; a null path clears it."""
    return {
        HEADLINES_PATH: [_api_asset(item) for item in copy["headlines"]],
        DESCRIPTIONS_PATH: [_api_asset(item) for item in copy["descriptions"]],
        PATH_PATHS["path1"]: copy["path1"],
        PATH_PATHS["path2"]: copy["path2"],
        FINAL_URLS_PATH: [copy["final_url"]] if copy["final_url"] else [],
    }


def _card_asset(item: Mapping[str, Any]) -> TextAsset:
    pin = item.get("pinnedField")
    return {
        "text": str(item.get("text") or ""),
        "pin": pin if isinstance(pin, str) and pin not in {"", "UNSPECIFIED"} else None,
    }


def _api_asset(item: TextAsset) -> dict[str, str]:
    return (
        {"text": item["text"], "pinnedField": item["pin"]}
        if item["pin"]
        else {"text": item["text"]}
    )


def merged_copy(current: AdCopy, change: Mapping[str, Any]) -> tuple[AdCopy, list[str]]:
    """Applies one entry's edits to the live copy, and says why the result can't be sent.

    An added headline or description takes the place of a removed one, in order, and the
    rest go at the end. A pin applies to the headline or description with that text.
    """
    problems: list[str] = []
    headlines = _merged_assets(
        "headline",
        current["headlines"],
        change.get("remove_headlines"),
        change.get("add_headlines"),
        problems,
    )
    descriptions = _merged_assets(
        "description",
        current["descriptions"],
        change.get("remove_descriptions"),
        change.get("add_descriptions"),
        problems,
    )
    for item in change.get("pins") or ():
        _pin(item["text"], item.get("pin"), headlines, descriptions, problems)
    for label, assets, (low, high) in (
        ("headlines", headlines, HEADLINES),
        ("descriptions", descriptions, DESCRIPTIONS),
    ):
        if not low <= len(assets) <= high:
            problems.append(f"An ad needs {low} to {high} {label}. This edit leaves {len(assets)}.")
    after: AdCopy = {
        "headlines": headlines,
        "descriptions": descriptions,
        "path1": _path(change, "path1", current),
        "path2": _path(change, "path2", current),
        "final_url": change.get("final_url") or current["final_url"],
    }
    if after["path2"] and not after["path1"]:
        problems.append("Set path 1 before path 2.")
    return after, problems


def _merged_assets(
    noun: str,
    live: Sequence[TextAsset],
    removed: Sequence[str] | None,
    added: Sequence[Mapping[str, Any]] | None,
    problems: list[str],
) -> list[TextAsset]:
    gone = list(removed or ())
    live_texts = [item["text"] for item in live]
    problems.extend(
        f"This ad has no {noun} “{text}” to remove." for text in gone if text not in live_texts
    )
    queue: list[TextAsset] = [
        {"text": item["text"], "pin": item.get("pin")} for item in added or ()
    ]
    merged: list[TextAsset] = []
    for item in live:
        if item["text"] not in gone:
            merged.append({"text": item["text"], "pin": item["pin"]})
        elif queue:
            merged.append(queue.pop(0))
    merged.extend(queue)
    kept = {text for text in live_texts if text not in gone}
    texts = [item["text"] for item in merged]
    problems.extend(
        f"This ad already has the {noun} “{text}”."
        if text in kept
        else f"The {noun} “{text}” is added twice."
        for text in dict.fromkeys(text for text in texts if texts.count(text) > 1)
    )
    return merged


def _pin(
    text: str,
    pin: str | None,
    headlines: list[TextAsset],
    descriptions: list[TextAsset],
    problems: list[str],
) -> None:
    """Pins or unpins the asset with this text; no pin applies to a headline or description."""
    if pin is None:
        lists, noun = [headlines, descriptions], "headline or description"
    elif pin.startswith("HEADLINE"):
        lists, noun = [headlines], "headline"
    else:
        lists, noun = [descriptions], "description"
    found = [item for assets in lists for item in assets if item["text"] == text]
    if not found:
        problems.append(f"This ad has no {noun} “{text}” to pin.")
    for item in found:
        item["pin"] = pin


def _path(change: Mapping[str, Any], key: str, current: AdCopy) -> str | None:
    if key not in change:
        return current[key]  # type: ignore[literal-required]
    return change[key] or None


async def read_responsive_search_ads(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    resource_names: Sequence[str],
) -> dict[str, LiveAd]:
    """Returns each ad, removed ones included, keyed by its `adGroupAds` resource name."""
    prefix = f"customers/{normalize_customer_id(customer_id)}/"
    wanted = sorted(set(resource_names))
    if any(_AD_GROUP_AD.fullmatch(name) is None or not name.startswith(prefix) for name in wanted):
        raise ValueError("Google Ads ad reads need this account's ad resource names")
    if not wanted:
        return {}
    names = ", ".join(f"'{name}'" for name in wanted)
    payload = await client.post(
        f"customers/{normalize_customer_id(customer_id)}/googleAds:searchStream",
        operation="read_responsive_search_ads",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={
            "query": (
                f"SELECT {', '.join(_FIELDS)} FROM ad_group_ad "  # noqa: S608 -- validated resource names
                f"WHERE ad_group_ad.resource_name IN ({names})"
            )
        },
    )
    ads: dict[str, LiveAd] = {}
    for row in stream_rows(payload, max_rows=len(wanted)):
        item = row.get("adGroupAd")
        if not isinstance(item, Mapping) or item.get("resourceName") not in wanted:
            continue
        ads[str(item["resourceName"])] = _live_ad(item, row)
    return ads


def _live_ad(item: Mapping[str, Any], row: Mapping[str, Any]) -> LiveAd:
    ad = _mapping(item.get("ad"))
    responsive = _mapping(ad.get("responsiveSearchAd"))
    ad_group, campaign = _mapping(row.get("adGroup")), _mapping(row.get("campaign"))
    statuses = {item.get("status"), ad_group.get("status"), campaign.get("status")}
    return LiveAd(
        ad_resource_name=str(ad.get("resourceName") or ""),
        type=str(ad.get("type") or ""),
        status="REMOVED" if "REMOVED" in statuses else str(item.get("status") or ""),
        approval_status=_mapping(item.get("policySummary")).get("approvalStatus"),
        name=ad_display_name(ad),
        ad_group_name=str(ad_group.get("name") or ""),
        campaign_name=str(campaign.get("name") or ""),
        values={
            HEADLINES_PATH: [_api_asset(_card_asset(h)) for h in responsive.get("headlines") or ()],
            DESCRIPTIONS_PATH: [
                _api_asset(_card_asset(d)) for d in responsive.get("descriptions") or ()
            ],
            PATH_PATHS["path1"]: responsive.get("path1") or None,
            PATH_PATHS["path2"]: responsive.get("path2") or None,
            FINAL_URLS_PATH: list(ad.get("finalUrls") or ()),
        },
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}
