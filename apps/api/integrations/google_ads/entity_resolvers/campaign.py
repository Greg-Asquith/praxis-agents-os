# apps/api/integrations/google_ads/entity_resolvers/campaign.py

"""Google Ads campaign lookup for shared runtime entity selectors."""

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

from integrations.google_ads.operations.list_campaigns import list_campaigns
from integrations.google_ads.references import GoogleAdsCampaignReference
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

from .utils import bounded_offset, group_scoped_references

MAX_SEARCH_CHOICES = 101


def _choice(entry, campaign: Mapping[str, Any]) -> EntityChoice | None:
    campaign_id = str(campaign.get("id", "")).strip()
    status = str(campaign.get("status", "")).strip()
    if not campaign_id.isdigit() or status == "REMOVED":
        return None
    name = str(campaign.get("name", "")).strip() or "(unnamed campaign)"
    return EntityChoice.from_reference(
        GoogleAdsCampaignReference(
            integration_resource_id=entry.integration_resource_id,
            external_id=campaign_id,
            label=name[:500],
            description=status.title() if status else "Campaign",
            scope_label=entry.display_name,
            status=status or None,
        ),
        icon="google_ads",
    )


async def _query(
    ctx,
    entry,
    *,
    campaign_ids: Sequence[str] = (),
    search: str | None = None,
    limit: int,
    exclude_removed: bool,
) -> list[Mapping[str, Any]]:
    client = await google_ads_client_for_principal(
        ctx.db,
        actor=ctx.actor,
        workspace=ctx.workspace,
        entry=entry,
    )
    return await list_campaigns(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        campaign_ids=campaign_ids,
        search=search,
        limit=limit,
        exclude_removed=exclude_removed,
    )


async def search_google_ads_campaigns(ctx, search, _dependent_args, page_size, cursor):
    offset = bounded_offset(cursor, upper_bound=MAX_SEARCH_CHOICES - 1)
    request_limit = min(offset + page_size + 1, MAX_SEARCH_CHOICES)

    async def search_entry(entry) -> list[EntityChoice]:
        campaigns = await _query(
            ctx,
            entry,
            search=search.strip() or None,
            limit=request_limit,
            exclude_removed=True,
        )
        return [
            choice for campaign in campaigns if (choice := _choice(entry, campaign)) is not None
        ]

    entries = ctx.active_context.compatible_entries(GOOGLE_ADS_BINDING)
    choices = [
        choice
        for entry_choices in await asyncio.gather(*(search_entry(entry) for entry in entries))
        for choice in entry_choices
    ]
    bounded_choices = choices[:MAX_SEARCH_CHOICES]
    selected = bounded_choices[offset : offset + page_size]
    return EntityResolverPage(
        choices=tuple(selected),
        next_cursor=(
            str(offset + page_size) if len(bounded_choices) > offset + page_size else None
        ),
    )


async def resolve_google_ads_campaigns(ctx, values: Sequence[Any], _dependent_args):
    choices: list[EntityChoice] = []
    grouped = group_scoped_references(ctx, GOOGLE_ADS_BINDING, values, GoogleAdsCampaignReference)
    for entry, references in grouped:
        ids = [reference.external_id for reference in references]
        campaigns = await _query(
            ctx,
            entry,
            campaign_ids=ids,
            limit=len(ids),
            exclude_removed=True,
        )
        choices.extend(
            choice for campaign in campaigns if (choice := _choice(entry, campaign)) is not None
        )
    return tuple(choices)


GOOGLE_ADS_CAMPAIGN_RESOLVER = EntityResolverDefinition(
    entity_kind="google_ads_campaign",
    reference_type=GoogleAdsCampaignReference,
    search=search_google_ads_campaigns,
    resolve=resolve_google_ads_campaigns,
    max_page_size=25,
    requires_active_context=True,
    provider_key="google_ads",
)
