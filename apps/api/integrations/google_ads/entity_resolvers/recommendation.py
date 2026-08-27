# apps/api/integrations/google_ads/entity_resolvers/recommendation.py

"""Google Ads recommendation lookup for shared runtime entity selectors."""

import asyncio
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from integrations.google_ads.operations.list_recommendations import list_recommendations
from integrations.google_ads.references import GoogleAdsRecommendationReference
from integrations.google_ads.tools.utils import (
    GOOGLE_ADS_BINDING,
    google_ads_client_for_principal,
    login_customer_id,
)
from services.integrations.context.schemas import MAX_ACTIVE_CONTEXT_TARGETS
from services.integrations.entity_references import (
    EntityChoice,
    EntityResolverDefinition,
    EntityResolverPage,
)

from .utils import MAX_GOOGLE_ADS_ENTITY_CURSOR_LENGTH, entity_search_fingerprint

_MAX_QUERY_ROWS = 10_000
_CURSOR_PATTERN = re.compile(r"3\.([0-9a-f]{16})\.(\d{1,6})")
_CAMPAIGN_RESOURCE_PATTERN = re.compile(r"^customers/\d{1,32}/campaigns/\d{1,32}$")


@dataclass(frozen=True)
class _RecommendationCursor:
    next_choice_index: int


def _affected_campaigns(recommendation: Mapping[str, Any]) -> tuple[str, ...]:
    values: list[str] = []
    campaign = recommendation.get("campaign")
    if isinstance(campaign, str) and campaign:
        values.append(campaign)
    campaigns = recommendation.get("campaigns")
    if isinstance(campaigns, list):
        values.extend(value for value in campaigns if isinstance(value, str) and value)
    return tuple(
        dict.fromkeys(value for value in values if _CAMPAIGN_RESOURCE_PATTERN.fullmatch(value))
    )


def _choice(entry, recommendation: Mapping[str, Any]) -> EntityChoice | None:
    resource_name = str(recommendation.get("resourceName", "")).strip()
    recommendation_type = str(recommendation.get("type", "")).strip()
    if not resource_name or not recommendation_type or recommendation.get("dismissed") is True:
        return None
    campaign_resources = _affected_campaigns(recommendation)
    description = (
        f"Affects {len(campaign_resources)} campaign{'s' if len(campaign_resources) != 1 else ''}"
        if campaign_resources
        else "Google Ads recommendation"
    )
    return EntityChoice.from_reference(
        GoogleAdsRecommendationReference(
            customer_id=entry.external_id,
            resource_name=resource_name,
            recommendation_type=recommendation_type,
            label=recommendation_type.replace("_", " ").title(),
            description=description,
            scope_label=entry.display_name,
        ),
        icon="google_ads",
    )


async def _query(
    ctx,
    entry,
    *,
    resource_names: Sequence[str] = (),
    include_dismissed: bool,
    limit: int,
) -> list[Mapping[str, Any]]:
    client = await google_ads_client_for_principal(
        ctx.db,
        actor=ctx.actor,
        workspace=ctx.workspace,
        entry=entry,
    )
    return await list_recommendations(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        resource_names=resource_names,
        include_dismissed=include_dismissed,
        limit=limit,
    )


async def search_google_ads_recommendations(ctx, search, _dependent_args, page_size, cursor):
    normalized_search = search.strip().casefold()
    entries = ctx.active_context.compatible_entries(GOOGLE_ADS_BINDING)[:MAX_ACTIVE_CONTEXT_TARGETS]
    resource_ids = tuple(entry.integration_resource_id for entry in entries)
    position = _decode_cursor(cursor, normalized_search, resource_ids)

    async def search_entry(entry_index, entry):
        rows = await _query(
            ctx,
            entry,
            include_dismissed=False,
            limit=_MAX_QUERY_ROWS,
        )
        choices = []
        for row_index, row in enumerate(
            sorted(rows, key=lambda row: str(row.get("resourceName", "")))
        ):
            choice = _choice(entry, row)
            if choice is not None and (
                not normalized_search
                or normalized_search in choice.label.casefold()
                or normalized_search in choice.description.casefold()
            ):
                choices.append(((row_index, entry_index), choice))
        return choices

    pages = await asyncio.gather(
        *(search_entry(entry_index, entry) for entry_index, entry in enumerate(entries))
    )
    ordered = sorted(item for choices in pages for item in choices)
    start = position.next_choice_index if position is not None else 0
    selected = ordered[start : start + page_size]
    next_position = start + len(selected) if start + len(selected) < len(ordered) else None
    return EntityResolverPage(
        choices=tuple(choice for _key, choice in selected),
        next_cursor=(
            _encode_cursor(normalized_search, resource_ids, next_position)
            if next_position is not None
            else None
        ),
    )


async def resolve_google_ads_recommendations(ctx, values: Sequence[Any], _dependent_args):
    entries_by_customer: dict[str, list[Any]] = defaultdict(list)
    for entry in ctx.active_context.compatible_entries(GOOGLE_ADS_BINDING)[
        :MAX_ACTIVE_CONTEXT_TARGETS
    ]:
        entries_by_customer[entry.external_id].append(entry)
    grouped: dict[str, dict[str, GoogleAdsRecommendationReference]] = defaultdict(dict)
    for value in values:
        try:
            reference = GoogleAdsRecommendationReference.model_validate(value)
        except ValueError:
            continue
        matching = entries_by_customer.get(reference.customer_id, ())
        if len(matching) == 1:
            grouped[reference.customer_id].setdefault(reference.resource_name, reference)

    choices: list[EntityChoice] = []
    for customer_id, references_by_name in grouped.items():
        entry = entries_by_customer[customer_id][0]
        rows = await _query(
            ctx,
            entry,
            resource_names=tuple(references_by_name)[:100],
            include_dismissed=False,
            limit=len(references_by_name),
        )
        choices.extend(choice for row in rows if (choice := _choice(entry, row)) is not None)
    return tuple(choices)


def _encode_cursor(
    search: str,
    resource_ids: Sequence[UUID],
    next_choice_index: int,
) -> str:
    encoded = f"3.{entity_search_fingerprint(search, resource_ids)}.{next_choice_index}"
    if len(encoded) > MAX_GOOGLE_ADS_ENTITY_CURSOR_LENGTH:
        raise ValueError("Google Ads recommendation cursor exceeds the generic cursor bound")
    return encoded


def _decode_cursor(
    cursor: str | None,
    search: str,
    resource_ids: Sequence[UUID],
) -> _RecommendationCursor | None:
    if not cursor or len(cursor) > MAX_GOOGLE_ADS_ENTITY_CURSOR_LENGTH:
        return None
    match = _CURSOR_PATTERN.fullmatch(cursor)
    if match is None:
        return None
    fingerprint, raw_next_choice_index = match.groups()
    next_choice_index = int(raw_next_choice_index)
    if (
        next_choice_index > MAX_ACTIVE_CONTEXT_TARGETS * _MAX_QUERY_ROWS
        or fingerprint != entity_search_fingerprint(search, resource_ids)
    ):
        return None
    return _RecommendationCursor(next_choice_index)


GOOGLE_ADS_RECOMMENDATION_RESOLVER = EntityResolverDefinition(
    entity_kind="google_ads_recommendation",
    reference_type=GoogleAdsRecommendationReference,
    search=search_google_ads_recommendations,
    resolve=resolve_google_ads_recommendations,
    max_page_size=25,
    requires_active_context=True,
    provider_key="google_ads",
)
