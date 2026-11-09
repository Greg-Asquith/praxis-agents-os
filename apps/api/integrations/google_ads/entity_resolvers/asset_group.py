# apps/api/integrations/google_ads/entity_resolvers/asset_group.py

"""Google Ads asset group lookup for shared runtime entity selectors."""

from collections.abc import Mapping, Sequence
from typing import Any

from integrations.google_ads.operations.list_asset_groups import (
    MAX_ASSET_GROUP_LOOKUP,
    list_asset_groups,
)
from integrations.google_ads.references import GoogleAdsAssetGroupReference
from integrations.google_ads.tools.utils import (
    GOOGLE_ADS_BINDING,
    google_ads_client_for_principal,
    login_customer_id,
)
from services.integrations.entity_references import EntityChoice, EntityResolverDefinition

from .utils import group_scoped_references, search_scoped_entities


def _choice(entry, row: Mapping[str, Any]) -> EntityChoice | None:
    asset_group, campaign = row.get("assetGroup"), row.get("campaign")
    if not isinstance(asset_group, Mapping) or not isinstance(campaign, Mapping):
        return None
    asset_group_id = str(asset_group.get("id", ""))
    campaign_id = str(campaign.get("id", ""))
    status = str(asset_group.get("status", "")).strip()
    if not asset_group_id.isdigit() or not campaign_id.isdigit() or status == "REMOVED":
        return None
    name = str(asset_group.get("name", "")).strip() or "(unnamed asset group)"
    return EntityChoice.from_reference(
        GoogleAdsAssetGroupReference(
            customer_id=entry.external_id,
            campaign_id=campaign_id,
            asset_group_id=asset_group_id,
            label=name[:500],
            description=status.title() if status else "Asset group",
            scope_label=str(campaign.get("name", "")).strip()[:500] or "(unnamed campaign)",
            status=status or None,
        ),
        icon="google_ads",
    )


async def _query(ctx, entry, **filters: Any) -> list[Mapping[str, Any]]:
    client = await google_ads_client_for_principal(
        ctx.db, actor=ctx.actor, workspace=ctx.workspace, entry=entry
    )
    return await list_asset_groups(
        client, customer_id=entry.external_id, login_customer_id=login_customer_id(entry), **filters
    )


async def search_google_ads_asset_groups(ctx, search, _dependent_args, page_size, cursor):
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


async def resolve_google_ads_asset_groups(ctx, values: Sequence[Any], _dependent_args):
    choices: list[EntityChoice] = []
    grouped = group_scoped_references(
        ctx,
        GOOGLE_ADS_BINDING,
        values,
        GoogleAdsAssetGroupReference,
        max_references=MAX_ASSET_GROUP_LOOKUP - 1,
    )
    for entry, references in grouped:
        ids = [reference.asset_group_id for reference in references]
        rows = await _query(ctx, entry, asset_group_ids=ids, limit=len(ids))
        choices.extend(choice for row in rows if (choice := _choice(entry, row)) is not None)
    return tuple(choices)


GOOGLE_ADS_ASSET_GROUP_RESOLVER = EntityResolverDefinition(
    entity_kind="google_ads_asset_group",
    reference_type=GoogleAdsAssetGroupReference,
    search=search_google_ads_asset_groups,
    resolve=resolve_google_ads_asset_groups,
    max_page_size=25,
    max_exact_values=MAX_ASSET_GROUP_LOOKUP - 1,
    requires_active_context=True,
    provider_key="google_ads",
)
