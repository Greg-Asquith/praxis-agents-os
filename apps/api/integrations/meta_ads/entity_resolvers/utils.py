# apps/api/integrations/meta_ads/entity_resolvers/utils.py

"""Shared Meta Ads object and asset search, and exact resolution within selected ad accounts."""

from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.entity_references import (
    EntityChoice,
    EntityResolverContext,
    EntityResolverPage,
    ScopedEntityReference,
)
from services.integrations.report_results import ReportResultBudget
from utils.metadata import metadata_str

from ..client import MetaAdsClient
from ..operations.list_objects import list_objects
from ..tools.schemas.objects import CLOSED_STATUSES, MetaAdsObject, MetaAdsObjectType
from ..tools.utils.bindings import META_ADS_BINDING
from ..tools.utils.client import meta_ads_client_for_principal

MAX_SEARCH_CHOICES = 100
MAX_EXACT_REFERENCES = 50

type ChoiceFn = Callable[[ResolvedContextEntry, MetaAdsObject, str], EntityChoice | None]
type AssetSearchFn = Callable[
    [MetaAdsClient, ResolvedContextEntry, ReportResultBudget],
    Awaitable[Sequence[ScopedEntityReference]],
]
type AssetResolveFn[T] = Callable[
    [MetaAdsClient, ResolvedContextEntry, ReportResultBudget, Sequence[T]],
    Awaitable[Sequence[T]],
]


def asset_read_args(entry: ResolvedContextEntry, budget: ReportResultBudget) -> dict[str, Any]:
    """Builds the account arguments every asset read takes."""
    return {"account_id": entry.external_id, "scope_label": entry.display_name, "budget": budget}


def account_currency(entry: ResolvedContextEntry) -> str:
    return metadata_str(entry.permissions_metadata.get("currency")) or ""


def is_open(item: MetaAdsObject) -> bool:
    return item.status not in CLOSED_STATUSES


def object_label(item: MetaAdsObject, fallback: str) -> str:
    return (item.name or "").strip()[:500] or fallback


def status_description(item: MetaAdsObject, fallback: str) -> str:
    return (item.status or fallback).replace("_", " ").capitalize()


async def search_objects(
    ctx: EntityResolverContext,
    search: str,
    *,
    object_type: MetaAdsObjectType,
    page_size: int,
    cursor: str | None,
    choice: ChoiceFn,
) -> EntityResolverPage:
    """Searches active and paused objects by name across the selected ad accounts."""
    start = _offset(cursor)
    limit = min(start + page_size + 1, MAX_SEARCH_CHOICES)

    async def search_entry(entry: ResolvedContextEntry) -> list[EntityChoice]:
        client = await meta_ads_client_for_principal(
            ctx.db, actor=ctx.actor, workspace=ctx.workspace, entry=entry
        )
        currency = account_currency(entry)
        result = await list_objects(
            client,
            account_id=entry.external_id,
            object_type=object_type,
            name_contains=search.strip() or None,
            limit=limit,
            currency=currency,
        )
        return _choices(entry, result.objects, currency, choice)

    # Serial: every account's credential lookup shares the request's one database session.
    choices: list[EntityChoice] = []
    for entry in ctx.active_context.compatible_entries(META_ADS_BINDING):
        if len(choices) >= MAX_SEARCH_CHOICES:
            break
        choices.extend(await search_entry(entry))
    choices = choices[:MAX_SEARCH_CHOICES]
    return EntityResolverPage(
        choices=tuple(choices[start : start + page_size]),
        next_cursor=str(start + page_size) if len(choices) > start + page_size else None,
    )


async def resolve_objects(
    ctx: EntityResolverContext,
    values: Sequence[Any],
    *,
    object_type: MetaAdsObjectType,
    reference_type: type[ScopedEntityReference],
    choice: ChoiceFn,
) -> tuple[EntityChoice, ...]:
    """Re-reads referenced objects through the edge of their own selected ad account.

    References to an account outside active context, or to an object Meta doesn't
    return from that account's edge, produce no choice.
    """
    entries_by_scope: dict[str, list[ResolvedContextEntry]] = defaultdict(list)
    for entry in ctx.active_context.compatible_entries(META_ADS_BINDING):
        entries_by_scope[entry.external_id].append(entry)
    grouped: dict[str, dict[str, ScopedEntityReference]] = defaultdict(dict)
    for value in values:
        try:
            reference = reference_type.model_validate(value)
        except ValueError:
            continue
        if len(entries_by_scope.get(reference.provider_scope_id, ())) == 1:
            grouped[reference.provider_scope_id].setdefault(reference.provider_entity_id, reference)

    choices: list[EntityChoice] = []
    for scope_id, references in grouped.items():
        entry = entries_by_scope[scope_id][0]
        ids = sorted(references)[:MAX_EXACT_REFERENCES]
        client = await meta_ads_client_for_principal(
            ctx.db, actor=ctx.actor, workspace=ctx.workspace, entry=entry
        )
        currency = account_currency(entry)
        result = await list_objects(
            client,
            account_id=entry.external_id,
            object_type=object_type,
            object_ids=ids,
            limit=len(ids),
            currency=currency,
        )
        choices.extend(_choices(entry, result.objects, currency, choice))
    return tuple(choices)


async def search_assets(
    ctx: EntityResolverContext,
    search: str,
    *,
    page_size: int,
    cursor: str | None,
    read: AssetSearchFn,
) -> EntityResolverPage:
    """Searches one kind of asset by label across the selected ad accounts."""
    start = _offset(cursor)
    needle = search.strip().casefold()
    choices: list[EntityChoice] = []
    # Serial: every account's credential lookup shares the request's one database session.
    for entry in ctx.active_context.compatible_entries(META_ADS_BINDING):
        if len(choices) >= MAX_SEARCH_CHOICES:
            break
        client = await meta_ads_client_for_principal(
            ctx.db, actor=ctx.actor, workspace=ctx.workspace, entry=entry
        )
        budget = ReportResultBudget("meta_ads", "search_assets")
        found = await read(client, entry, budget)
        choices.extend(
            EntityChoice.from_reference(reference, icon="meta_ads")
            for reference in found
            if needle in reference.label.casefold()
        )
    choices = choices[:MAX_SEARCH_CHOICES]
    return EntityResolverPage(
        choices=tuple(choices[start : start + page_size]),
        next_cursor=str(start + page_size) if len(choices) > start + page_size else None,
    )


async def resolve_assets[T: ScopedEntityReference](
    ctx: EntityResolverContext,
    values: Sequence[Any],
    *,
    reference_type: type[T],
    read: AssetResolveFn[T],
) -> tuple[EntityChoice, ...]:
    """Re-reads referenced assets through their own selected ad account.

    References to an account outside active context, or to an asset Meta doesn't
    return for that account, produce no choice.
    """
    entries_by_scope: dict[str, list[ResolvedContextEntry]] = defaultdict(list)
    for entry in ctx.active_context.compatible_entries(META_ADS_BINDING):
        entries_by_scope[entry.external_id].append(entry)
    grouped: dict[str, list[T]] = defaultdict(list)
    for value in values:
        try:
            reference = reference_type.model_validate(value)
        except ValueError:
            continue
        if len(entries_by_scope.get(reference.provider_scope_id, ())) == 1:
            grouped[reference.provider_scope_id].append(reference)
    choices: list[EntityChoice] = []
    for scope_id, references in grouped.items():
        entry = entries_by_scope[scope_id][0]
        client = await meta_ads_client_for_principal(
            ctx.db, actor=ctx.actor, workspace=ctx.workspace, entry=entry
        )
        budget = ReportResultBudget("meta_ads", "resolve_assets")
        wanted = {reference.identity() for reference in references[:MAX_EXACT_REFERENCES]}
        found = await read(client, entry, budget, references[:MAX_EXACT_REFERENCES])
        choices.extend(
            EntityChoice.from_reference(reference, icon="meta_ads")
            for reference in found
            if reference.identity() in wanted
        )
    return tuple(choices)


def _choices(
    entry: ResolvedContextEntry, items: Sequence[MetaAdsObject], currency: str, choice: ChoiceFn
) -> list[EntityChoice]:
    return [
        resolved
        for item in items
        if is_open(item) and (resolved := choice(entry, item, currency)) is not None
    ]


def _offset(cursor: str | None) -> int:
    try:
        return min(max(int(cursor or "0"), 0), MAX_SEARCH_CHOICES)
    except ValueError:
        return 0
