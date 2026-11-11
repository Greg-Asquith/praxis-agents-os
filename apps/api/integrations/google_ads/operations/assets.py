# apps/api/integrations/google_ads/operations/assets.py

"""Reads sitelink and callout assets, where they're linked, and the campaigns and ad groups they serve in."""

import asyncio
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from core.exceptions.integration import IntegrationFailureDisposition, IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .utils import entity_id_boundary_filter, escape_gaql_like_literal, stream_rows

MAX_ASSET_LOOKUP = 101
# Google allows 20 sitelinks and 20 callouts a target; these only stop an unbounded read.
_MAX_LINKS = 20_000
_MAX_USES = 1_000
_TOO_MANY = "These campaigns use too many assets to check at once. Change fewer campaigns."
_TYPES = ("SITELINK", "CALLOUT")
_ASSET_FIELDS = (
    "asset.id, asset.type, asset.source, asset.final_urls, "
    "asset.sitelink_asset.link_text, asset.sitelink_asset.description1, "
    "asset.sitelink_asset.description2, asset.sitelink_asset.start_date, "
    "asset.sitelink_asset.end_date, asset.callout_asset.callout_text, "
    "asset.callout_asset.start_date, asset.callout_asset.end_date"
)
# Each asset type's editable fields, as edit seam paths, in the order the card shows them.
ASSET_PATHS: Mapping[str, tuple[str, ...]] = {
    "SITELINK": (
        "sitelinkAsset.linkText",
        "sitelinkAsset.description1",
        "sitelinkAsset.description2",
        "finalUrls",
        "sitelinkAsset.startDate",
        "sitelinkAsset.endDate",
    ),
    "CALLOUT": ("calloutAsset.calloutText", "calloutAsset.startDate", "calloutAsset.endDate"),
}
_LABEL_PATHS = {"SITELINK": "sitelinkAsset.linkText", "CALLOUT": "calloutAsset.calloutText"}


@dataclass(frozen=True, slots=True)
class LiveAsset:
    resource_name: str
    asset_type: str
    # `ADVERTISER`, or `AUTOMATICALLY_CREATED` for one Google made, which can't be edited.
    source: str
    # The editable fields by `ASSET_PATHS` path, with null for an unset field.
    values: Mapping[str, Any]

    @property
    def label(self) -> str:
        return str(self.values.get(_LABEL_PATHS.get(self.asset_type, "")) or self.resource_name)


@dataclass(frozen=True, slots=True)
class LiveLink:
    resource_name: str
    asset: LiveAsset


@dataclass(frozen=True, slots=True)
class LiveTarget:
    """A campaign or ad group that assets link to."""

    resource_name: str
    name: str
    status: str
    campaign_name: str | None = None


@dataclass(frozen=True, slots=True)
class LiveAssets:
    targets: Mapping[str, LiveTarget] = field(default_factory=dict)
    # Each target's sitelink and callout links, by target resource name.
    links: Mapping[str, tuple[LiveLink, ...]] = field(default_factory=dict)
    # The assets the request names, by resource name.
    assets: Mapping[str, LiveAsset] = field(default_factory=dict)
    # The campaigns and ad groups each named asset is linked to, by asset resource name.
    used_in: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def link(self, target: str, asset: str) -> str | None:
        return next(
            (
                item.resource_name
                for item in self.links.get(target, ())
                if item.asset.resource_name == asset
            ),
            None,
        )


def asset_values(asset: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """Returns an asset row's type and its editable fields by `ASSET_PATHS` path."""
    asset_type = str(asset.get("type") or "")
    values: dict[str, Any] = {}
    for path in ASSET_PATHS.get(asset_type, ()):
        value: Any = asset
        for part in path.split("."):
            value = value.get(part) if isinstance(value, Mapping) else None
        values[path] = list(value) if isinstance(value, list) else value
    return asset_type, values


def _live_asset(customer: str, row: Mapping[str, Any]) -> LiveAsset | None:
    asset = row.get("asset")
    if not isinstance(asset, Mapping) or not str(asset.get("id", "")).isdigit():
        return None
    asset_type, values = asset_values(asset)
    return LiveAsset(
        f"customers/{customer}/assets/{asset['id']}",
        asset_type,
        str(asset.get("source") or "ADVERTISER"),
        values,
    )


async def list_assets(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    asset_ids: Sequence[str] = (),
    search: str | None = None,
    minimum_id: int | None = None,
    minimum_id_inclusive: bool = False,
    limit: int,
) -> list[LiveAsset]:
    """Returns sitelink and callout assets in ID order, searched by their text."""
    customer = normalize_customer_id(customer_id)
    if limit < 1 or limit > MAX_ASSET_LOOKUP:
        raise ValueError("Google Ads asset lookup limit must be between 1 and 101")
    ids = sorted(set(asset_ids))
    if any(not value.isdigit() for value in ids) or len(ids) > MAX_ASSET_LOOKUP:
        raise ValueError("Google Ads asset lookup takes at most 101 digit-only ids")
    filters = [f"asset.type IN ({', '.join(_TYPES)})"]
    if ids:
        filters.append(f"asset.id IN ({', '.join(ids)})")
    if search and search.strip():
        text = escape_gaql_like_literal(search.strip())
        filters.append(
            f"(asset.sitelink_asset.link_text LIKE '%{text}%' "
            f"OR asset.callout_asset.callout_text LIKE '%{text}%')"
        )
    if boundary := entity_id_boundary_filter(
        "asset.id", minimum_id=minimum_id, inclusive=minimum_id_inclusive
    ):
        filters.append(boundary)
    payload = await client.post(
        f"customers/{customer}/googleAds:searchStream",
        operation="list_assets",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={
            "query": f"SELECT {_ASSET_FIELDS} FROM asset "  # noqa: S608 -- fixed types, digit-only ids, escaped search
            f"WHERE {' AND '.join(filters)} ORDER BY asset.id LIMIT {limit}"
        },
    )
    return [
        asset
        for row in stream_rows(payload, max_rows=limit)
        if (asset := _live_asset(customer, row)) is not None
    ]


async def read_assets(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    campaign_ids: Sequence[str],
    ad_group_ids: Sequence[str],
    asset_ids: Sequence[str],
) -> LiveAssets:
    """Reads the targets, their sitelink and callout links, and the named assets with their uses.

    Raises:
        IntegrationValidationError: When the targets hold too many links to read at once.
    """
    if any(not value.isdigit() for value in (*campaign_ids, *ad_group_ids, *asset_ids)):
        raise ValueError("Google Ads ids must contain only digits")
    read = _Reader(client, normalize_customer_id(customer_id), login_customer_id)
    campaigns = sorted(set(campaign_ids))
    ad_groups = sorted(set(ad_group_ids))
    assets = sorted(set(asset_ids))
    results = await asyncio.gather(
        read.targets("campaign", campaigns),
        read.targets("ad_group", ad_groups),
        read.links("campaign", campaigns),
        read.links("ad_group", ad_groups),
        read.assets(assets),
        read.uses(assets),
    )
    campaign_targets, ad_group_targets, campaign_links, ad_group_links, named, uses = results
    links: dict[str, tuple[LiveLink, ...]] = {**campaign_links, **ad_group_links}
    linked = {item.asset.resource_name: item.asset for items in links.values() for item in items}
    return LiveAssets(
        targets={**campaign_targets, **ad_group_targets},
        links=links,
        assets={**linked, **named},
        used_in=uses,
    )


@dataclass(frozen=True, slots=True)
class _Reader:
    client: GoogleAdsClient
    customer: str
    login_customer_id: str

    async def _rows(
        self, query: str, operation: str, max_rows: int, *, strict: bool = True
    ) -> list[dict[str, Any]]:
        payload = await self.client.post(
            f"customers/{self.customer}/googleAds:searchStream",
            operation=operation,
            policy=IntegrationRequestPolicy.READ,
            login_customer_id=self.login_customer_id,
            json={"query": query},
        )
        rows = stream_rows(payload, max_rows=max_rows)
        if strict and len(rows) >= max_rows:
            raise IntegrationValidationError(
                _TOO_MANY,
                provider_key="google_ads",
                failure_disposition=IntegrationFailureDisposition.NOT_DISPATCHED,
            )
        return rows

    def _name(self, collection: str, value: Any) -> str:
        return f"customers/{self.customer}/{collection}/{value}"

    async def targets(self, resource: str, ids: Sequence[str]) -> dict[str, LiveTarget]:
        if not ids:
            return {}
        campaign = ", campaign.name" if resource == "ad_group" else ""
        rows = await self._rows(
            f"SELECT {resource}.id, {resource}.name, {resource}.status{campaign} "  # noqa: S608 -- fixed resources and digit-only ids
            f"FROM {resource} WHERE {resource}.id IN ({', '.join(ids)})",
            f"read_asset_{resource}s",
            len(ids) + 1,
        )
        key, collection = (
            ("campaign", "campaigns") if resource == "campaign" else ("adGroup", "adGroups")
        )
        targets = {}
        for row in rows:
            item = row.get(key) or {}
            name = self._name(collection, item.get("id"))
            parent = (row.get("campaign") or {}).get("name") if resource == "ad_group" else None
            targets[name] = LiveTarget(
                name,
                str(item.get("name") or name),
                str(item.get("status") or "UNKNOWN"),
                str(parent) if parent else None,
            )
        return targets

    async def links(self, resource: str, ids: Sequence[str]) -> dict[str, tuple[LiveLink, ...]]:
        if not ids:
            return {}
        rows = await self._rows(
            f"SELECT {resource}_asset.resource_name, {resource}.id, {_ASSET_FIELDS} "  # noqa: S608 -- fixed resources and digit-only ids
            f"FROM {resource}_asset WHERE {resource}.id IN ({', '.join(ids)}) "
            f"AND {resource}_asset.field_type IN ({', '.join(_TYPES)}) "
            f"AND {resource}_asset.status != 'REMOVED'",
            f"read_{resource}_asset_links",
            _MAX_LINKS,
        )
        key, collection = (
            ("campaign", "campaigns") if resource == "campaign" else ("adGroup", "adGroups")
        )
        links: dict[str, list[LiveLink]] = defaultdict(list)
        for row in rows:
            link = (row.get(f"{key}Asset") or {}).get("resourceName")
            asset = _live_asset(self.customer, row)
            if isinstance(link, str) and asset is not None:
                owner = self._name(collection, (row.get(key) or {}).get("id"))
                links[owner].append(LiveLink(link, asset))
        return {owner: tuple(items) for owner, items in links.items()}

    async def assets(self, ids: Sequence[str]) -> dict[str, LiveAsset]:
        if not ids:
            return {}
        rows = await self._rows(
            f"SELECT {_ASSET_FIELDS} FROM asset WHERE asset.id IN ({', '.join(ids)})",  # noqa: S608 -- digit-only ids
            "read_assets",
            len(ids) + 1,
        )
        return {
            asset.resource_name: asset
            for row in rows
            if (asset := _live_asset(self.customer, row)) is not None
        }

    async def uses(self, ids: Sequence[str]) -> dict[str, tuple[str, ...]]:
        """Names each campaign and ad group the assets are linked to."""
        if not ids:
            return {}
        results = await asyncio.gather(
            *(
                self._rows(
                    f"SELECT asset.id, {resource}.name FROM {resource}_asset "  # noqa: S608 -- fixed resources and digit-only ids
                    f"WHERE asset.id IN ({', '.join(ids)}) "
                    f"AND {resource}_asset.status != 'REMOVED'",
                    f"read_{resource}_asset_uses",
                    _MAX_USES,
                    # The card names the first uses only.
                    strict=False,
                )
                for resource in ("campaign", "ad_group")
            )
        )
        uses: dict[str, list[str]] = defaultdict(list)
        for key, rows in zip(("campaign", "adGroup"), results, strict=True):
            for row in rows:
                asset_id = (row.get("asset") or {}).get("id")
                name = (row.get(key) or {}).get("name")
                if asset_id and name:
                    uses[self._name("assets", asset_id)].append(str(name))
        return {asset: tuple(names) for asset, names in uses.items()}
