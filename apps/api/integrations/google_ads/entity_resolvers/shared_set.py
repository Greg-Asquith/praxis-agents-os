# apps/api/integrations/google_ads/entity_resolvers/shared_set.py

"""Google Ads negative keyword list lookup for runtime entity selectors."""

from collections.abc import Mapping, Sequence
from typing import Any

from integrations.google_ads.operations.list_shared_sets import list_shared_sets
from integrations.google_ads.references import GoogleAdsSharedSetReference
from integrations.google_ads.tools.utils import (
    GOOGLE_ADS_BINDING,
    google_ads_client_for_principal,
    login_customer_id,
)
from services.integrations.entity_references import (
    EntityChoice,
    EntityResolverDefinition,
)

from .utils import group_scoped_references, search_scoped_entities


def _choice(entry, shared_set: Mapping[str, Any]) -> EntityChoice | None:
    shared_set_id = str(shared_set.get("id", "")).strip()
    if not shared_set_id.isdigit():
        return None
    name = str(shared_set.get("name", "")).strip() or "(unnamed list)"
    raw_member_count = shared_set.get("memberCount")
    try:
        member_count = int(raw_member_count) if raw_member_count is not None else None
    except (TypeError, ValueError):
        member_count = None
    if member_count is not None and member_count < 0:
        member_count = None
    return EntityChoice.from_reference(
        GoogleAdsSharedSetReference(
            customer_id=entry.external_id,
            shared_set_id=shared_set_id,
            label=name[:500],
            description=(
                f"{member_count} negative keyword{'s' if member_count != 1 else ''}"
                if member_count is not None
                else "Negative keyword list"
            ),
            scope_label=entry.display_name,
            member_count=member_count,
        ),
        icon="google_ads",
    )


async def _query(
    ctx,
    entry,
    *,
    shared_set_ids: Sequence[str] = (),
    search: str | None = None,
    minimum_id: int | None = None,
    minimum_id_inclusive: bool = False,
    limit: int,
) -> list[Mapping[str, Any]]:
    client = await google_ads_client_for_principal(
        ctx.db,
        actor=ctx.actor,
        workspace=ctx.workspace,
        entry=entry,
    )
    return await list_shared_sets(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        shared_set_type="NEGATIVE_KEYWORDS",
        shared_set_ids=shared_set_ids,
        search=search,
        minimum_id=minimum_id,
        minimum_id_inclusive=minimum_id_inclusive,
        limit=limit,
    )


async def search_google_ads_shared_sets(ctx, search, _dependent_args, page_size, cursor):
    normalized_search = search.strip()

    async def query_entry(entry, minimum_id, inclusive, limit):
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


async def resolve_google_ads_shared_sets(ctx, values: Sequence[Any], _dependent_args):
    choices: list[EntityChoice] = []
    grouped = group_scoped_references(ctx, GOOGLE_ADS_BINDING, values, GoogleAdsSharedSetReference)
    for entry, references in grouped:
        ids = [reference.shared_set_id for reference in references]
        shared_sets = await _query(ctx, entry, shared_set_ids=ids, limit=len(ids))
        choices.extend(
            choice
            for shared_set in shared_sets
            if (choice := _choice(entry, shared_set)) is not None
        )
    return tuple(choices)


GOOGLE_ADS_SHARED_SET_RESOLVER = EntityResolverDefinition(
    entity_kind="google_ads_shared_set",
    reference_type=GoogleAdsSharedSetReference,
    search=search_google_ads_shared_sets,
    resolve=resolve_google_ads_shared_sets,
    max_page_size=25,
    requires_active_context=True,
    provider_key="google_ads",
)
