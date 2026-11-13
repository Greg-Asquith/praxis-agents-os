# apps/api/integrations/google_ads/operations/asset_group_state.py

"""Reads live asset groups: their settings, linked assets, search themes, and audience signals."""

import asyncio
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from core.exceptions.integration import IntegrationFailureDisposition, IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .criteria import AUDIENCE_FIELDS
from .utils import stream_rows

MAX_ASSET_GROUP_READ = 100
# A group holds at most about 130 links and 26 signals; these only stop an unbounded read.
_MAX_LINKS = 20_000
_MAX_SIGNALS = 5_000
_TOO_MANY = "These asset groups hold too much to check at once. Change fewer asset groups."
# Each audience segment's JSON field, back to the kind the tools name it by.
_SEGMENT_KINDS = {
    field: (kind, inner) for kind, (field, inner, _collection) in AUDIENCE_FIELDS.items()
}


@dataclass(frozen=True, slots=True)
class LiveGroupLink:
    """One asset an asset group links, as a field type such as `HEADLINE`."""

    resource_name: str
    asset_id: str
    field_type: str
    label: str
    # Set for a text asset, which tools name by its text.
    text: str | None = None
    # False for an asset Google made, which doesn't count towards the minimums.
    advertiser: bool = True


@dataclass(frozen=True, slots=True)
class LiveAudience:
    resource_name: str
    # `ASSET_GROUP` for an audience of one group's own; `CUSTOMER` for a shared one.
    scope: str
    dimensions: tuple[Mapping[str, Any], ...]

    @property
    def segments(self) -> tuple[tuple[str, str], ...]:
        """The `(kind, key)` of each audience in its segment dimensions."""
        keys = (
            segment_key(segment)
            for dimension in self.dimensions
            for segment in (dimension.get("audienceSegments") or {}).get("segments") or ()
        )
        return tuple(key for key in keys if key is not None)


def segment_key(segment: Mapping[str, Any]) -> tuple[str, str] | None:
    """Returns a segment's `(kind, key)`, such as `("user_list", "401")`, or None for others."""
    for name, (kind, inner) in _SEGMENT_KINDS.items():
        value = str((segment.get(name) or {}).get(inner) or "").rpartition("/")[2]
        if value.isdigit():
            return kind, value
    return None


@dataclass(frozen=True, slots=True)
class LiveAssetGroup:
    resource_name: str
    name: str
    status: str
    final_urls: tuple[str, ...]
    campaign_name: str
    channel: str
    campaign_status: str
    # True for a campaign with a Merchant Center feed, which can fill groups from it.
    retail: bool
    links: tuple[LiveGroupLink, ...] = ()
    # Each search theme's signal resource name and text.
    themes: tuple[tuple[str, str], ...] = ()
    # Each audience signal's resource name and the audience it names.
    audience_signals: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class LiveAssetGroups:
    groups: Mapping[str, LiveAssetGroup] = field(default_factory=dict)
    audiences: Mapping[str, LiveAudience] = field(default_factory=dict)


async def read_asset_groups(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    asset_group_ids: Sequence[str],
) -> LiveAssetGroups:
    """Returns the asset groups that exist, by resource name, with the audiences they signal.

    Raises:
        IntegrationValidationError: When the groups hold more than one read can check.
    """
    ids = sorted(set(asset_group_ids))
    if not ids:
        return LiveAssetGroups()
    if len(ids) > MAX_ASSET_GROUP_READ or any(not value.isdigit() for value in ids):
        raise ValueError("Google Ads asset group reads take at most 100 digit-only ids")
    reader = _Reader(client, normalize_customer_id(customer_id), login_customer_id)
    within = f"asset_group.id IN ({', '.join(ids)})"
    groups, links, signals = await asyncio.gather(
        reader.rows(
            "SELECT asset_group.id, asset_group.name, asset_group.status, asset_group.final_urls, "  # noqa: S608 -- digit-only ids
            "campaign.name, campaign.status, campaign.advertising_channel_type, "
            f"campaign.shopping_setting.merchant_id FROM asset_group WHERE {within}",
            max_rows=len(ids),
        ),
        reader.rows(
            "SELECT asset_group.id, asset_group_asset.resource_name, asset_group_asset.field_type, "  # noqa: S608 -- digit-only ids
            "asset_group_asset.source, asset.id, asset.name, asset.text_asset.text, "
            "asset.youtube_video_asset.youtube_video_title FROM asset_group_asset "
            f"WHERE {within} AND asset_group_asset.status != 'REMOVED'",
            max_rows=_MAX_LINKS,
        ),
        reader.rows(
            "SELECT asset_group.id, asset_group_signal.resource_name, "  # noqa: S608 -- digit-only ids
            "asset_group_signal.search_theme.text, asset_group_signal.audience.audience "
            f"FROM asset_group_signal WHERE {within}",
            max_rows=_MAX_SIGNALS,
        ),
    )
    return await _assemble(reader, groups, links, signals)


async def _assemble(
    reader: "_Reader",
    groups: list[dict[str, Any]],
    links: list[dict[str, Any]],
    signals: list[dict[str, Any]],
) -> LiveAssetGroups:
    prefix = f"customers/{reader.customer_id}"
    linked: dict[str, list[LiveGroupLink]] = defaultdict(list)
    for row in links:
        link = _link(row)
        if link is not None:
            linked[f"{prefix}/assetGroups/{(row.get('assetGroup') or {}).get('id')}"].append(link)
    themes: dict[str, list[tuple[str, str]]] = defaultdict(list)
    audiences: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for row in signals:
        signal = row.get("assetGroupSignal") or {}
        name = signal.get("resourceName")
        group = f"{prefix}/assetGroups/{(row.get('assetGroup') or {}).get('id')}"
        theme = (signal.get("searchTheme") or {}).get("text")
        audience = (signal.get("audience") or {}).get("audience")
        if isinstance(name, str) and isinstance(theme, str):
            themes[group].append((name, theme))
        elif isinstance(name, str) and isinstance(audience, str):
            audiences[group].append((name, audience))
    live: dict[str, LiveAssetGroup] = {}
    for row in groups:
        group, campaign = row.get("assetGroup") or {}, row.get("campaign") or {}
        name = f"{prefix}/assetGroups/{group.get('id')}"
        merchant = str((campaign.get("shoppingSetting") or {}).get("merchantId") or "")
        live[name] = LiveAssetGroup(
            resource_name=name,
            name=str(group.get("name") or f"Asset group {group.get('id')}"),
            status=str(group.get("status") or ""),
            final_urls=tuple(str(url) for url in group.get("finalUrls") or ()),
            campaign_name=str(campaign.get("name") or ""),
            channel=str(campaign.get("advertisingChannelType") or ""),
            campaign_status=str(campaign.get("status") or ""),
            retail=merchant.isdigit() and merchant != "0",
            links=tuple(linked[name]),
            themes=tuple(themes[name]),
            audience_signals=tuple(audiences[name]),
        )
    named = sorted({audience for items in audiences.values() for _, audience in items})
    return LiveAssetGroups(groups=live, audiences=await _audiences(reader, named))


def _link(row: Mapping[str, Any]) -> LiveGroupLink | None:
    link, asset = row.get("assetGroupAsset") or {}, row.get("asset") or {}
    name, field_type = link.get("resourceName"), link.get("fieldType")
    asset_id = str(asset.get("id") or "")
    if not isinstance(name, str) or not isinstance(field_type, str) or not asset_id.isdigit():
        return None
    text = (asset.get("textAsset") or {}).get("text")
    title = (asset.get("youtubeVideoAsset") or {}).get("youtubeVideoTitle")
    label = text or title or asset.get("name") or f"Asset {asset_id}"
    return LiveGroupLink(
        resource_name=name,
        asset_id=asset_id,
        field_type=field_type,
        label=str(label),
        text=text if isinstance(text, str) else None,
        advertiser=link.get("source") in (None, "ADVERTISER"),
    )


async def _audiences(reader: "_Reader", names: Sequence[str]) -> dict[str, LiveAudience]:
    ids = [name.rpartition("/")[2] for name in names if name.rpartition("/")[2].isdigit()]
    if not ids:
        return {}
    rows = await reader.rows(
        "SELECT audience.resource_name, audience.scope, audience.dimensions FROM audience "  # noqa: S608 -- digit-only ids
        f"WHERE audience.id IN ({', '.join(ids)})",
        max_rows=len(ids),
    )
    audiences = {}
    for row in rows:
        audience = row.get("audience") or {}
        name = audience.get("resourceName")
        if isinstance(name, str):
            dimensions = audience.get("dimensions") or ()
            audiences[name] = LiveAudience(
                resource_name=name,
                scope=str(audience.get("scope") or ""),
                dimensions=tuple(item for item in dimensions if isinstance(item, Mapping)),
            )
    return audiences


@dataclass(frozen=True, slots=True)
class _Reader:
    client: GoogleAdsClient
    customer_id: str
    login_customer_id: str

    async def rows(self, query: str, *, max_rows: int) -> list[dict[str, Any]]:
        payload = await self.client.post(
            f"customers/{self.customer_id}/googleAds:searchStream",
            operation="read_asset_groups",
            policy=IntegrationRequestPolicy.READ,
            login_customer_id=self.login_customer_id,
            json={"query": query},
        )
        rows = stream_rows(payload, max_rows=max_rows + 1)
        if len(rows) > max_rows:
            raise IntegrationValidationError(
                _TOO_MANY,
                provider_key="google_ads",
                failure_disposition=IntegrationFailureDisposition.NOT_DISPATCHED,
            )
        return rows
