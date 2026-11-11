# apps/api/integrations/google_ads/entity_resolvers/asset.py

"""Google Ads ad asset lookup for runtime entity selectors."""

from collections.abc import Sequence
from typing import Any

from integrations.google_ads.operations.assets import MAX_ASSET_LOOKUP, LiveAsset, list_assets
from integrations.google_ads.references import GoogleAdsAssetReference
from integrations.google_ads.tools.utils import (
    GOOGLE_ADS_BINDING,
    google_ads_client_for_principal,
    login_customer_id,
)
from services.integrations.entity_references import EntityChoice, EntityResolverDefinition

from .utils import group_scoped_references, search_scoped_entities

_TYPE_LABELS = {
    "SITELINK": "Sitelink",
    "CALLOUT": "Callout",
    "STRUCTURED_SNIPPET": "Structured snippet",
    "CALL": "Call",
    "PRICE": "Price",
    "IMAGE": "Image",
}


def _choice(entry, asset: LiveAsset) -> EntityChoice | None:
    if asset.asset_type not in _TYPE_LABELS:
        return None
    description = _TYPE_LABELS[asset.asset_type]
    if asset.size:
        description = f"{description}, {asset.size[0]} by {asset.size[1]}"
    if asset.source == "AUTOMATICALLY_CREATED":
        description = f"{description} made by Google"
    return EntityChoice.from_reference(
        GoogleAdsAssetReference(
            customer_id=entry.external_id,
            asset_id=asset.resource_name.rsplit("/", 1)[1],
            asset_type=asset.asset_type,
            label=asset.label[:500],
            description=description,
            scope_label=entry.display_name[:500],
        ),
        icon="google_ads",
    )


async def _query(ctx, entry, **filters: Any) -> list[LiveAsset]:
    client = await google_ads_client_for_principal(
        ctx.db, actor=ctx.actor, workspace=ctx.workspace, entry=entry
    )
    return await list_assets(
        client, customer_id=entry.external_id, login_customer_id=login_customer_id(entry), **filters
    )


async def search_google_ads_assets(ctx, search, _dependent_args, page_size, cursor):
    normalized_search = search.strip()

    async def query_entry(entry, minimum_id, _minimum_secondary_id, inclusive, limit):
        return await _query(
            ctx,
            entry,
            search=normalized_search or None,
            minimum_id=minimum_id,
            minimum_id_inclusive=inclusive,
            limit=limit,
        )

    return await search_scoped_entities(
        ctx,
        GOOGLE_ADS_BINDING,
        search=normalized_search,
        page_size=page_size,
        cursor=cursor,
        query_entry=query_entry,
        choice_for_row=_choice,
    )


async def resolve_google_ads_assets(ctx, values: Sequence[Any], _dependent_args):
    choices: list[EntityChoice] = []
    grouped = group_scoped_references(
        ctx,
        GOOGLE_ADS_BINDING,
        values,
        GoogleAdsAssetReference,
        max_references=MAX_ASSET_LOOKUP - 1,
    )
    for entry, references in grouped:
        ids = [reference.asset_id for reference in references]
        assets = await _query(ctx, entry, asset_ids=ids, limit=len(ids))
        choices.extend(choice for asset in assets if (choice := _choice(entry, asset)) is not None)
    return tuple(choices)


GOOGLE_ADS_ASSET_RESOLVER = EntityResolverDefinition(
    entity_kind="google_ads_asset",
    reference_type=GoogleAdsAssetReference,
    search=search_google_ads_assets,
    resolve=resolve_google_ads_assets,
    max_page_size=25,
    max_exact_values=MAX_ASSET_LOOKUP - 1,
    requires_active_context=True,
    provider_key="google_ads",
)
