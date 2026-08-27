# apps/api/integrations/notion/entity_resolvers/utils.py

"""Shared Notion entity-resolver paging and scope helpers."""

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from core.exceptions.integration import IntegrationNotFoundError
from services.integrations.entity_references import (
    EntityChoice,
    EntityResolverPage,
    ScopedEntityReference,
)

from ..operations.search import search as search_notion
from ..tools.utils import NOTION_BINDING, notion_client_for_principal

MAX_SEARCH_CHOICES = 100


def offset(cursor: str | None) -> int:
    try:
        return min(max(int(cursor or "0"), 0), MAX_SEARCH_CHOICES)
    except ValueError:
        return 0


async def search_entities(
    ctx,
    query: str,
    *,
    kind: str,
    page_size: int,
    cursor: str | None,
    choice: Callable[[Any, Mapping[str, Any]], EntityChoice | None],
) -> EntityResolverPage:
    start = offset(cursor)
    request_limit = min(start + page_size + 1, MAX_SEARCH_CHOICES)

    async def search_entry(entry) -> list[EntityChoice]:
        client = await notion_client_for_principal(
            ctx.db,
            actor=ctx.actor,
            workspace=ctx.workspace,
            entry=entry,
        )
        result = await search_notion(
            client,
            query=query.strip() or None,
            kind=kind,
            limit=request_limit,
        )
        return [
            resolved
            for item in result["items"]
            if isinstance(item, Mapping) and (resolved := choice(entry, item)) is not None
        ]

    entries = ctx.active_context.compatible_entries(NOTION_BINDING)
    choices = [
        item
        for entry_choices in await asyncio.gather(*(search_entry(entry) for entry in entries))
        for item in entry_choices
    ][:MAX_SEARCH_CHOICES]
    selected = choices[start : start + page_size]
    return EntityResolverPage(
        choices=tuple(selected),
        next_cursor=str(start + page_size) if len(choices) > start + page_size else None,
    )


async def resolve_entities[ReferenceT: ScopedEntityReference](
    ctx,
    values: Sequence[Any],
    *,
    reference_type: type[ReferenceT],
    hydrate: Callable[[Any, ReferenceT], Awaitable[Mapping[str, Any]]],
    choice: Callable[[Any, Mapping[str, Any]], EntityChoice | None],
) -> tuple[EntityChoice, ...]:
    entries_by_scope: dict[str, list[Any]] = defaultdict(list)
    for entry in ctx.active_context.compatible_entries(NOTION_BINDING):
        entries_by_scope[entry.external_id].append(entry)
    grouped: dict[str, list[ReferenceT]] = defaultdict(list)
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
        client = await notion_client_for_principal(
            ctx.db,
            actor=ctx.actor,
            workspace=ctx.workspace,
            entry=entry,
        )
        for reference in references[:25]:
            try:
                payload = await hydrate(client, reference)
            except IntegrationNotFoundError:
                continue
            if resolved := choice(entry, payload):
                choices.append(resolved)
    return tuple(choices)
