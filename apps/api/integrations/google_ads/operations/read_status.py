# apps/api/integrations/google_ads/operations/read_status.py

"""Reads the live status of campaigns, ad groups, ads, keywords, and asset groups."""

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .list_ads import ad_display_name
from .utils import stream_rows

_RESOURCE_NAME = re.compile(
    r"customers/\d+/(?:campaigns|adGroups|assetGroups)/\d+"
    r"|customers/\d+/(?:adGroupAds|adGroupCriteria)/\d+~\d+"
)
_CAMPAIGN_FIELDS = ("campaign.id", "campaign.name", "campaign.status")
_AD_GROUP_FIELDS = ("ad_group.id", "ad_group.name", "ad_group.status")
# Each kind's GAQL resource, the row key Google returns it under, and the fields read.
_QUERIES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "campaign": ("campaign", "campaign", ("campaign.resource_name", *_CAMPAIGN_FIELDS)),
    "ad_group": (
        "ad_group",
        "adGroup",
        ("ad_group.resource_name", *_AD_GROUP_FIELDS, *_CAMPAIGN_FIELDS),
    ),
    "ad": (
        "ad_group_ad",
        "adGroupAd",
        (
            "ad_group_ad.resource_name",
            "ad_group_ad.status",
            "ad_group_ad.ad.id",
            "ad_group_ad.ad.name",
            "ad_group_ad.ad.responsive_search_ad.headlines",
            *_AD_GROUP_FIELDS,
            *_CAMPAIGN_FIELDS,
        ),
    ),
    "keyword": (
        "ad_group_criterion",
        "adGroupCriterion",
        (
            "ad_group_criterion.resource_name",
            "ad_group_criterion.status",
            "ad_group_criterion.type",
            "ad_group_criterion.negative",
            "ad_group_criterion.keyword.text",
            *_AD_GROUP_FIELDS,
            *_CAMPAIGN_FIELDS,
        ),
    ),
    "asset_group": (
        "asset_group",
        "assetGroup",
        (
            "asset_group.resource_name",
            "asset_group.name",
            "asset_group.status",
            *_CAMPAIGN_FIELDS,
        ),
    ),
}


@dataclass(frozen=True, slots=True)
class LiveStatus:
    """One object's status with its campaign's, and its ad group's for ads and keywords."""

    kind: str
    name: str
    status: str
    campaign_id: str
    campaign_name: str
    campaign_status: str | None
    ad_group_id: str | None = None
    ad_group_name: str | None = None
    ad_group_status: str | None = None


async def read_statuses(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    objects: Sequence[tuple[str, str]],
) -> dict[str, LiveStatus]:
    """Returns each `(kind, resource_name)` object's live status, keyed by resource name.

    Objects Google doesn't return, and keyword resources that aren't positive keywords, are
    left out. Removed objects are returned with status `REMOVED`.
    """
    prefix = f"customers/{normalize_customer_id(customer_id)}/"
    by_kind: dict[str, list[str]] = defaultdict(list)
    for kind, resource_name in objects:
        if (
            kind not in _QUERIES
            or _RESOURCE_NAME.fullmatch(resource_name) is None
            or not resource_name.startswith(prefix)
        ):
            raise ValueError("Google Ads status reads need a known kind and this account's objects")
        by_kind[kind].append(resource_name)
    # One kind at a time: concurrent requests would share the caller's database session.
    replies = [
        await _read_kind(client, customer_id, login_customer_id, kind, names)
        for kind, names in by_kind.items()
    ]
    return {name: status for reply in replies for name, status in reply.items()}


async def _read_kind(
    client: GoogleAdsClient,
    customer_id: str,
    login_customer_id: str,
    kind: str,
    resource_names: Sequence[str],
) -> dict[str, LiveStatus]:
    resource, row_key, fields = _QUERIES[kind]
    names = ", ".join(f"'{name}'" for name in sorted(set(resource_names)))
    query = (
        f"SELECT {', '.join(fields)} FROM {resource} "  # noqa: S608 -- validated resource names
        f"WHERE {resource}.resource_name IN ({names})"
    )
    payload = await client.post(
        f"customers/{normalize_customer_id(customer_id)}/googleAds:searchStream",
        operation="read_status",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={"query": query},
    )
    wanted = set(resource_names)
    statuses: dict[str, LiveStatus] = {}
    for row in stream_rows(payload, max_rows=len(wanted)):
        item = row.get(row_key)
        campaign = row.get("campaign")
        if not isinstance(item, Mapping) or not isinstance(campaign, Mapping):
            continue
        name = item.get("resourceName")
        status = item.get("status")
        if name not in wanted or not isinstance(status, str) or not _is_target(kind, item):
            continue
        ad_group = row.get("adGroup") if kind in {"ad", "keyword"} else None
        statuses[name] = LiveStatus(
            kind=kind,
            name=_display_name(kind, item, campaign),
            status=status,
            campaign_id=str(campaign.get("id", "")),
            campaign_name=str(campaign.get("name", "")),
            campaign_status=_text(campaign.get("status")),
            ad_group_id=_text(ad_group.get("id")) if isinstance(ad_group, Mapping) else None,
            ad_group_name=_text(ad_group.get("name")) if isinstance(ad_group, Mapping) else None,
            ad_group_status=_text(ad_group.get("status"))
            if isinstance(ad_group, Mapping)
            else None,
        )
    return statuses


def _is_target(kind: str, item: Mapping[str, Any]) -> bool:
    # Only positive keywords are keyword targets; negatives change in their own tool.
    return kind != "keyword" or (item.get("type") == "KEYWORD" and item.get("negative") is not True)


def _display_name(kind: str, item: Mapping[str, Any], campaign: Mapping[str, Any]) -> str:
    if kind == "campaign":
        return str(campaign.get("name") or "")
    if kind == "ad":
        ad = item.get("ad")
        return ad_display_name(ad) if isinstance(ad, Mapping) else ""
    if kind == "keyword":
        keyword = item.get("keyword")
        return str(keyword.get("text") or "") if isinstance(keyword, Mapping) else ""
    return str(item.get("name") or "")


def _text(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None
