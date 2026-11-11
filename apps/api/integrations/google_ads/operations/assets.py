# apps/api/integrations/google_ads/operations/assets.py

"""Reads ad assets, where they're linked, and the campaigns and ad groups they serve in."""

import asyncio
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from core.exceptions.integration import IntegrationFailureDisposition, IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .build import CampaignBuild
from .utils import entity_id_boundary_filter, escape_gaql_like_literal, stream_rows

if TYPE_CHECKING:
    from ..tools.schemas.assets import NewAsset

MAX_ASSET_LOOKUP = 101
# Google allows 20 sitelinks and 20 callouts a target; these only stop an unbounded read.
_MAX_LINKS = 20_000
_MAX_USES = 1_000
_TOO_MANY = "These campaigns use too many assets to check at once. Change fewer campaigns."
_TYPES = ("SITELINK", "CALLOUT", "STRUCTURED_SNIPPET", "CALL", "PRICE", "IMAGE")
# The field types assets of those types are linked with; an image shows as one of two.
_FIELD_TYPES = (
    "SITELINK",
    "CALLOUT",
    "STRUCTURED_SNIPPET",
    "CALL",
    "PRICE",
    "AD_IMAGE",
    "BUSINESS_LOGO",
)
_ASSET_FIELDS = (
    "asset.id, asset.type, asset.source, asset.name, asset.final_urls, "
    "asset.sitelink_asset.link_text, asset.sitelink_asset.description1, "
    "asset.sitelink_asset.description2, asset.sitelink_asset.start_date, "
    "asset.sitelink_asset.end_date, asset.callout_asset.callout_text, "
    "asset.callout_asset.start_date, asset.callout_asset.end_date, "
    "asset.structured_snippet_asset.header, asset.structured_snippet_asset.values, "
    "asset.call_asset.country_code, asset.call_asset.phone_number, "
    "asset.price_asset.type, asset.price_asset.price_qualifier, "
    "asset.price_asset.language_code, asset.price_asset.price_offerings, "
    "asset.image_asset.full_size.width_pixels, asset.image_asset.full_size.height_pixels"
)
# GAQL has no OR, so a text search runs one query per searchable field.
_SEARCH_FIELDS = (
    ("SITELINK", "asset.sitelink_asset.link_text"),
    ("CALLOUT", "asset.callout_asset.callout_text"),
    ("STRUCTURED_SNIPPET", "asset.structured_snippet_asset.header"),
    ("CALL", "asset.call_asset.phone_number"),
    ("IMAGE", "asset.name"),
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
    "STRUCTURED_SNIPPET": ("structuredSnippetAsset.header", "structuredSnippetAsset.values"),
    "CALL": ("callAsset.countryCode", "callAsset.phoneNumber"),
    "PRICE": (
        "priceAsset.type",
        "priceAsset.priceQualifier",
        "priceAsset.languageCode",
        "priceAsset.priceOfferings",
    ),
    # An image's content can't change, so it has no editable fields.
    "IMAGE": (),
}
_UNSET = (None, "UNSPECIFIED", "UNKNOWN")


@dataclass(frozen=True, slots=True)
class LiveAsset:
    resource_name: str
    asset_type: str
    # `ADVERTISER`, or `AUTOMATICALLY_CREATED` for one Google made, which can't be edited.
    source: str
    # The editable fields by `ASSET_PATHS` path, with null for an unset field.
    values: Mapping[str, Any]
    name: str | None = None
    # An image's width and height in pixels.
    size: tuple[int, int] | None = None

    @property
    def label(self) -> str:
        return asset_label(self.asset_type, self.values, self.name) or self.resource_name


@dataclass(frozen=True, slots=True)
class LiveLink:
    resource_name: str
    asset: LiveAsset
    # Google's field type, which is the asset's type except for images.
    field_type: str = ""


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
    # The named assets linked to the whole account, by resource name.
    account_level: frozenset[str] = frozenset()
    # The uses read reached its row limit, so `used_in` is incomplete.
    uses_truncated: bool = False

    def link(self, target: str, asset: str, field_type: str | None = None) -> str | None:
        """Finds the target's link to the asset, as that field type when one is given."""
        return next(
            (
                item.resource_name
                for item in self.links.get(target, ())
                if item.asset.resource_name == asset
                and field_type in (None, item.field_type or item.asset.asset_type)
            ),
            None,
        )


def asset_label(asset_type: str, values: Mapping[str, Any], name: str | None = None) -> str:
    """Names an asset by its content, such as a sitelink's link text or a call's number."""
    match asset_type:
        case "SITELINK":
            return str(values.get("sitelinkAsset.linkText") or "")
        case "CALLOUT":
            return str(values.get("calloutAsset.calloutText") or "")
        case "STRUCTURED_SNIPPET":
            items = values.get("structuredSnippetAsset.values") or []
            return (
                f"{values.get('structuredSnippetAsset.header') or ''}: {', '.join(map(str, items))}"
            )
        case "CALL":
            return str(values.get("callAsset.phoneNumber") or "")
        case "PRICE":
            offerings = values.get("priceAsset.priceOfferings") or []
            return ", ".join(str(item.get("header") or "") for item in offerings if item)
    return name or ""


def price_offering_value(offering: Any) -> dict[str, Any] | None:
    """Returns a price offering in the one shape both the request and Google's read compare in."""
    if not isinstance(offering, Mapping):
        return None
    price = offering.get("price") if isinstance(offering.get("price"), Mapping) else {}
    value: dict[str, Any] = {
        "header": offering.get("header"),
        "description": offering.get("description"),
        "price": {
            "currencyCode": price.get("currencyCode"),
            "amountMicros": str(price.get("amountMicros") or "0"),
        },
        "finalUrl": offering.get("finalUrl"),
    }
    if offering.get("unit") not in (None, "UNSPECIFIED", "UNKNOWN"):
        value["unit"] = offering["unit"]
    return value


def _live_value(path: str, value: Any) -> Any:
    """Puts a value Google returns into the shape the request compares it in."""
    if path == "priceAsset.priceOfferings":
        return [price_offering_value(item) for item in value] if isinstance(value, list) else []
    if path == "priceAsset.priceQualifier":
        return None if value in _UNSET else value
    return list(value) if isinstance(value, list) else value


def asset_values(asset: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """Returns an asset row's type and its editable fields by `ASSET_PATHS` path."""
    asset_type = str(asset.get("type") or "")
    values: dict[str, Any] = {}
    for path in ASSET_PATHS.get(asset_type, ()):
        value: Any = asset
        for part in path.split("."):
            value = value.get(part) if isinstance(value, Mapping) else None
        values[path] = _live_value(path, value)
    return asset_type, values


def new_asset_body(asset: "NewAsset") -> dict[str, Any]:
    """The create body for a new asset; unset fields are left out."""
    body: dict[str, Any] = {}
    for path, value in asset.values_by_path().items():
        if value is None:
            continue
        *parents, leaf = path.split(".")
        node = body
        for part in parents:
            node = node.setdefault(part, {})
        node[leaf] = value
    return body


def link_new_asset(
    build: CampaignBuild,
    asset: "NewAsset",
    *,
    link: Literal["campaignAsset", "adGroupAsset"],
    owner: str,
    asset_source: Any,
    link_source: Any,
) -> None:
    """Links a new asset to a campaign or ad group, creating the asset once per build."""
    name = build.create_once(
        asset.key, "asset", new_asset_body(asset), label=asset.label, source=asset_source
    )
    owner_field = "campaign" if link == "campaignAsset" else "adGroup"
    build.create(
        link,
        {owner_field: owner, "asset": name, "fieldType": asset.asset_type},
        label=asset.label,
        source=link_source,
    )


def _image_size(asset: Mapping[str, Any]) -> tuple[int, int] | None:
    full = (asset.get("imageAsset") or {}).get("fullSize") or {}
    try:
        width, height = int(full.get("widthPixels") or 0), int(full.get("heightPixels") or 0)
    except (TypeError, ValueError):
        return None
    return (width, height) if width > 0 and height > 0 else None


def _live_asset(customer: str, row: Mapping[str, Any]) -> LiveAsset | None:
    asset = row.get("asset")
    if not isinstance(asset, Mapping) or not str(asset.get("id", "")).isdigit():
        return None
    asset_type, values = asset_values(asset)
    name = asset.get("name")
    return LiveAsset(
        f"customers/{customer}/assets/{asset['id']}",
        asset_type,
        str(asset.get("source") or "ADVERTISER"),
        values,
        str(name) if name else None,
        _image_size(asset),
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
    """Returns linkable assets in ID order, searched by their text or, for images, their name."""
    customer = normalize_customer_id(customer_id)
    if limit < 1 or limit > MAX_ASSET_LOOKUP:
        raise ValueError("Google Ads asset lookup limit must be between 1 and 101")
    ids = sorted(set(asset_ids))
    if any(not value.isdigit() for value in ids) or len(ids) > MAX_ASSET_LOOKUP:
        raise ValueError("Google Ads asset lookup takes at most 101 digit-only ids")
    filters = []
    if ids:
        filters.append(f"asset.id IN ({', '.join(ids)})")
    if boundary := entity_id_boundary_filter(
        "asset.id", minimum_id=minimum_id, inclusive=minimum_id_inclusive
    ):
        filters.append(boundary)
    text = escape_gaql_like_literal(search.strip()) if search and search.strip() else None
    queries = (
        [[f"asset.type = '{kind}'", f"{path} LIKE '%{text}%'"] for kind, path in _SEARCH_FIELDS]
        if text
        else [[f"asset.type IN ({', '.join(_TYPES)})"]]
    )

    async def query(conditions: list[str]) -> list[LiveAsset]:
        payload = await client.post(
            f"customers/{customer}/googleAds:searchStream",
            operation="list_assets",
            policy=IntegrationRequestPolicy.READ,
            login_customer_id=login_customer_id,
            json={
                "query": f"SELECT {_ASSET_FIELDS} FROM asset "  # noqa: S608 -- fixed types and paths, digit-only ids, escaped search
                f"WHERE {' AND '.join([*conditions, *filters])} ORDER BY asset.id LIMIT {limit}"
            },
        )
        return [
            asset
            for row in stream_rows(payload, max_rows=limit)
            if (asset := _live_asset(customer, row)) is not None
        ]

    found = {
        asset.resource_name: asset
        for assets in await asyncio.gather(*(query(conditions) for conditions in queries))
        for asset in assets
    }
    return sorted(found.values(), key=lambda asset: int(asset.resource_name.rsplit("/", 1)[1]))[
        :limit
    ]


async def read_assets(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    campaign_ids: Sequence[str],
    ad_group_ids: Sequence[str],
    asset_ids: Sequence[str],
    with_uses: bool = True,
) -> LiveAssets:
    """Reads the targets, their asset links, and the named assets with their uses.

    Args:
        with_uses: False skips where the named assets are used, which only the card shows.

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
        read.uses(assets if with_uses else ()),
    )
    campaign_targets, ad_group_targets, campaign_links, ad_group_links, named, uses = results
    used_in, account_level, uses_truncated = uses
    links: dict[str, tuple[LiveLink, ...]] = {**campaign_links, **ad_group_links}
    linked = {item.asset.resource_name: item.asset for items in links.values() for item in items}
    return LiveAssets(
        targets={**campaign_targets, **ad_group_targets},
        links=links,
        assets={**linked, **named},
        used_in=used_in,
        account_level=account_level,
        uses_truncated=uses_truncated,
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
            f"SELECT {resource}_asset.resource_name, {resource}_asset.field_type, "  # noqa: S608 -- fixed resources and digit-only ids
            f"{resource}.id, {_ASSET_FIELDS} "
            f"FROM {resource}_asset WHERE {resource}.id IN ({', '.join(ids)}) "
            f"AND {resource}_asset.field_type IN ({', '.join(_FIELD_TYPES)}) "
            f"AND {resource}_asset.status != 'REMOVED'",
            f"read_{resource}_asset_links",
            _MAX_LINKS,
        )
        key, collection = (
            ("campaign", "campaigns") if resource == "campaign" else ("adGroup", "adGroups")
        )
        links: dict[str, list[LiveLink]] = defaultdict(list)
        for row in rows:
            item = row.get(f"{key}Asset") or {}
            link = item.get("resourceName")
            asset = _live_asset(self.customer, row)
            if isinstance(link, str) and asset is not None:
                owner = self._name(collection, (row.get(key) or {}).get("id"))
                field_type = str(item.get("fieldType") or asset.asset_type)
                links[owner].append(LiveLink(link, asset, field_type))
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

    async def uses(
        self, ids: Sequence[str]
    ) -> tuple[dict[str, tuple[str, ...]], frozenset[str], bool]:
        """Reads where the assets are linked.

        Returns:
            The live campaigns and ad groups each asset is linked to, the assets linked to the
            whole account, and whether a read reached its row limit.
        """
        if not ids:
            return {}, frozenset(), False
        asset_filter = f"asset.id IN ({', '.join(ids)})"
        live_owner = {
            "campaign": "campaign.status != 'REMOVED'",
            "ad_group": "ad_group.status != 'REMOVED' AND campaign.status != 'REMOVED'",
        }
        campaigns, ad_groups, account = await asyncio.gather(
            *(
                self._rows(
                    f"SELECT asset.id, {resource}.name FROM {resource}_asset "  # noqa: S608 -- fixed resources and digit-only ids
                    f"WHERE {asset_filter} AND {resource}_asset.status != 'REMOVED' "
                    f"AND {live_owner[resource]}",
                    f"read_{resource}_asset_uses",
                    _MAX_USES,
                    strict=False,
                )
                for resource in ("campaign", "ad_group")
            ),
            self._rows(
                f"SELECT asset.id FROM customer_asset WHERE {asset_filter} "  # noqa: S608 -- digit-only ids
                "AND customer_asset.status != 'REMOVED'",
                "read_customer_asset_uses",
                _MAX_USES,
                strict=False,
            ),
        )
        uses: dict[str, list[str]] = defaultdict(list)
        for key, rows in (("campaign", campaigns), ("adGroup", ad_groups)):
            for row in rows:
                asset_id = (row.get("asset") or {}).get("id")
                name = (row.get(key) or {}).get("name")
                if asset_id and name:
                    uses[self._name("assets", asset_id)].append(str(name))
        account_level = frozenset(
            self._name("assets", asset_id)
            for row in account
            if (asset_id := (row.get("asset") or {}).get("id"))
        )
        truncated = len(campaigns) >= _MAX_USES or len(ad_groups) >= _MAX_USES
        return {asset: tuple(names) for asset, names in uses.items()}, account_level, truncated
