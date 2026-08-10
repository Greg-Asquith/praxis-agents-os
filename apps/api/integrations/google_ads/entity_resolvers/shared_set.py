# apps/api/integrations/google_ads/entity_resolvers/shared_set.py

"""Google Ads negative keyword list lookup for runtime entity selectors."""

import asyncio
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
    EntityResolverPage,
)

from .utils import group_scoped_references, round_robin_window, unbounded_offset


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
            integration_resource_id=entry.integration_resource_id,
            external_id=shared_set_id,
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
        limit=limit,
    )


async def search_google_ads_shared_sets(ctx, search, _dependent_args, page_size, cursor):
    offset = unbounded_offset(cursor)

    async def search_entry(entry) -> list[EntityChoice]:
        shared_sets = await _query(
            ctx,
            entry,
            search=search.strip() or None,
            limit=None,
        )
        return [
            choice
            for shared_set in shared_sets
            if (choice := _choice(entry, shared_set)) is not None
        ]

    entries = ctx.active_context.compatible_entries(GOOGLE_ADS_BINDING)
    entry_choices = await asyncio.gather(*(search_entry(entry) for entry in entries))
    window = round_robin_window(entry_choices, offset=offset, limit=page_size + 1)
    selected = window[:page_size]
    return EntityResolverPage(
        choices=tuple(selected),
        next_cursor=str(offset + page_size) if len(window) > page_size else None,
    )


async def resolve_google_ads_shared_sets(ctx, values: Sequence[Any], _dependent_args):
    choices: list[EntityChoice] = []
    grouped = group_scoped_references(ctx, GOOGLE_ADS_BINDING, values, GoogleAdsSharedSetReference)
    for entry, references in grouped:
        ids = [reference.external_id for reference in references]
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
