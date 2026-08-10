# apps/api/integrations/google_ads/entity_resolvers/campaign.py

"""Google Ads campaign lookup for shared runtime entity selectors."""

import asyncio
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from integrations.google_ads.operations.utils import escape_gaql_like_literal, stream_rows
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

from .utils import bounded_offset

MAX_SEARCH_CHOICES = 101


def _choice(entry, campaign: Mapping[str, Any]) -> EntityChoice | None:
    campaign_id = str(campaign.get("id", "")).strip()
    if not campaign_id.isdigit():
        return None
    name = str(campaign.get("name", "")).strip() or "(unnamed campaign)"
    status = str(campaign.get("status", "")).strip()
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


async def _query(ctx, entry, query: str) -> list[Mapping[str, Any]]:
    client = await google_ads_client_for_principal(
        ctx.db,
        actor=ctx.actor,
        workspace=ctx.workspace,
        entry=entry,
    )
    payload = await client.post(
        f"customers/{entry.external_id}/googleAds:searchStream",
        operation="resolve_campaign_references",
        login_customer_id=login_customer_id(entry),
        json={"query": query},
    )
    return [
        campaign
        for row in stream_rows(payload)
        if isinstance((campaign := row.get("campaign")), Mapping)
    ]


async def search_google_ads_campaigns(ctx, search, _dependent_args, page_size, cursor):
    offset = bounded_offset(cursor, upper_bound=MAX_SEARCH_CHOICES - 1)
    request_limit = min(offset + page_size + 1, MAX_SEARCH_CHOICES)
    where = (
        f" WHERE campaign.name LIKE '%{escape_gaql_like_literal(search.strip())}%'"
        if search.strip()
        else ""
    )
    query = (
        "SELECT campaign.id, campaign.name, campaign.status FROM campaign"  # noqa: S608 -- escaped literal
        f"{where} ORDER BY campaign.name LIMIT {request_limit}"
    )

    async def search_entry(entry) -> list[EntityChoice]:
        campaigns = await _query(ctx, entry, query)
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
    entries = {
        entry.integration_resource_id: entry
        for entry in ctx.active_context.compatible_entries(GOOGLE_ADS_BINDING)
    }
    grouped: dict[Any, list[GoogleAdsCampaignReference]] = defaultdict(list)
    for value in values:
        try:
            reference = GoogleAdsCampaignReference.model_validate(value)
        except ValueError:
            continue
        if reference.integration_resource_id in entries and reference.external_id.isdigit():
            grouped[reference.integration_resource_id].append(reference)

    choices: list[EntityChoice] = []
    for resource_id, references in grouped.items():
        entry = entries[resource_id]
        ids = sorted({reference.external_id for reference in references})[:50]
        query = (
            "SELECT campaign.id, campaign.name, campaign.status FROM campaign "  # noqa: S608 -- digit-only ids
            f"WHERE campaign.id IN ({', '.join(ids)}) LIMIT {len(ids)}"
        )
        campaigns = await _query(ctx, entry, query)
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
