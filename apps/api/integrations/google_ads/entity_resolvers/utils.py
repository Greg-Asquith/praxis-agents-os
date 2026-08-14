# apps/api/integrations/google_ads/entity_resolvers/utils.py

"""Shared bounded paging and reference grouping for Google Ads entity resolvers."""

import asyncio
import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from services.integrations.context.domain import (
    IntegrationBinding,
    ResolvedActiveContext,
    ResolvedContextEntry,
)
from services.integrations.context.schemas import MAX_ACTIVE_CONTEXT_TARGETS
from services.integrations.entity_references import (
    EntityChoice,
    EntityResolverPage,
    ScopedEntityReference,
)


class _ResolverContext(Protocol):
    active_context: ResolvedActiveContext


MAX_EXACT_REFERENCES = 50
MAX_GOOGLE_ADS_ENTITY_ID = (1 << 63) - 1
MAX_GOOGLE_ADS_ENTITY_CURSOR_LENGTH = 128
_FINGERPRINT_HEX_LENGTH = 16
_CURSOR_PATTERN = re.compile(
    rf"1\.([0-9a-f]{{{_FINGERPRINT_HEX_LENGTH}}})\.([0-9]{{1,19}})\.([0-9a-f]{{32}})"
)


@dataclass(frozen=True)
class GoogleAdsEntityCursor:
    """Compact position in the global provider-ID/resource-ID tuple order."""

    fingerprint: str
    last_entity_id: int
    last_integration_resource_id: UUID


def entity_search_fingerprint(search: str, integration_resource_ids: Sequence[UUID]) -> str:
    """Bind a cursor to the effective search and ordered active resources."""
    payload = json.dumps(
        [search.strip(), [resource_id.hex for resource_id in integration_resource_ids]],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()[:_FINGERPRINT_HEX_LENGTH]


def encode_entity_cursor(cursor: GoogleAdsEntityCursor) -> str:
    """Encode a validated version-1 cursor within the generic 128-char bound."""
    if re.fullmatch(rf"[0-9a-f]{{{_FINGERPRINT_HEX_LENGTH}}}", cursor.fingerprint) is None:
        raise ValueError("Google Ads entity cursor fingerprint is invalid")
    if cursor.last_entity_id < 0 or cursor.last_entity_id > MAX_GOOGLE_ADS_ENTITY_ID:
        raise ValueError("Google Ads entity cursor id is outside the int64 range")
    encoded = (
        f"1.{cursor.fingerprint}.{cursor.last_entity_id}.{cursor.last_integration_resource_id.hex}"
    )
    if len(encoded) > MAX_GOOGLE_ADS_ENTITY_CURSOR_LENGTH:
        raise ValueError("Google Ads entity cursor exceeds the generic cursor bound")
    return encoded


def decode_entity_cursor(
    cursor: str | None,
    *,
    search: str,
    integration_resource_ids: Sequence[UUID],
) -> GoogleAdsEntityCursor | None:
    """Decode a current-context cursor, restarting safely for stale or invalid input."""
    if not cursor or len(cursor) > MAX_GOOGLE_ADS_ENTITY_CURSOR_LENGTH:
        return None
    match = _CURSOR_PATTERN.fullmatch(cursor)
    if match is None:
        return None
    fingerprint, raw_entity_id, raw_resource_id = match.groups()
    entity_id = int(raw_entity_id)
    if entity_id > MAX_GOOGLE_ADS_ENTITY_ID:
        return None
    resource_id = UUID(hex=raw_resource_id)
    if resource_id not in integration_resource_ids:
        return None
    expected_fingerprint = entity_search_fingerprint(search, integration_resource_ids)
    if fingerprint != expected_fingerprint:
        return None
    return GoogleAdsEntityCursor(
        fingerprint=fingerprint,
        last_entity_id=entity_id,
        last_integration_resource_id=resource_id,
    )


async def search_scoped_entities(
    ctx: _ResolverContext,
    binding: IntegrationBinding,
    *,
    search: str,
    page_size: int,
    cursor: str | None,
    query_entry: Callable[
        [ResolvedContextEntry, int | None, bool, int],
        Awaitable[Sequence[Mapping[str, Any]]],
    ],
    choice_for_row: Callable[[ResolvedContextEntry, Mapping[str, Any]], EntityChoice | None],
) -> EntityResolverPage:
    """Query bounded account windows and merge them in global tuple order."""
    if page_size < 1:
        raise ValueError("Google Ads entity page size must be positive")
    entries = ctx.active_context.compatible_entries(binding)[:MAX_ACTIVE_CONTEXT_TARGETS]
    resource_ids = tuple(entry.integration_resource_id for entry in entries)
    position = decode_entity_cursor(
        cursor,
        search=search,
        integration_resource_ids=resource_ids,
    )

    async def query_bounded_entry(
        entry: ResolvedContextEntry,
    ) -> tuple[tuple[tuple[int, str], EntityChoice], ...]:
        minimum_id = position.last_entity_id if position is not None else None
        inclusive = bool(
            position is not None
            and str(entry.integration_resource_id) > str(position.last_integration_resource_id)
        )
        rows = await query_entry(entry, minimum_id, inclusive, page_size + 1)
        choices: list[tuple[tuple[int, str], EntityChoice]] = []
        for row in rows:
            choice = choice_for_row(entry, row)
            external_id = _google_ads_choice_entity_id(choice) if choice is not None else None
            if choice is None or not isinstance(external_id, str) or not external_id.isdigit():
                continue
            entity_id = int(external_id)
            if entity_id > MAX_GOOGLE_ADS_ENTITY_ID:
                continue
            if minimum_id is not None and (
                entity_id < minimum_id or (entity_id == minimum_id and not inclusive)
            ):
                continue
            key = (entity_id, str(entry.integration_resource_id))
            choices.append((key, choice))
        return tuple(choices)

    grouped = await asyncio.gather(*(query_bounded_entry(entry) for entry in entries))
    merged: dict[tuple[int, str], EntityChoice] = {}
    for entry_choices in grouped:
        for key, choice in entry_choices:
            merged.setdefault(key, choice)
    ordered = sorted(merged.items())
    selected = ordered[:page_size]
    next_cursor = None
    if len(ordered) > page_size and selected:
        (last_entity_id, last_resource_id), _choice = selected[-1]
        next_cursor = encode_entity_cursor(
            GoogleAdsEntityCursor(
                fingerprint=entity_search_fingerprint(search, resource_ids),
                last_entity_id=last_entity_id,
                last_integration_resource_id=UUID(last_resource_id),
            )
        )
    return EntityResolverPage(
        choices=tuple(choice for _key, choice in selected),
        next_cursor=next_cursor,
    )


def _google_ads_choice_entity_id(choice: EntityChoice) -> str | None:
    """Read the provider-specific entity id from one Google Ads public choice."""
    key_by_kind = {
        "google_ads_ad_group": "ad_group_id",
        "google_ads_campaign": "campaign_id",
        "google_ads_shared_set": "shared_set_id",
    }
    key = key_by_kind.get(str(choice.value.get("entity_kind")))
    value = choice.value.get(key) if key is not None else None
    return value if isinstance(value, str) else None


def group_scoped_references[ReferenceT: ScopedEntityReference](
    ctx: _ResolverContext,
    binding: IntegrationBinding,
    values: Sequence[Any],
    reference_type: type[ReferenceT],
) -> tuple[tuple[ResolvedContextEntry, tuple[ReferenceT, ...]], ...]:
    """Validate and group exact references in compatible context-entry order."""
    entries = ctx.active_context.compatible_entries(binding)
    entries_by_scope: dict[str, list[ResolvedContextEntry]] = {}
    for entry in entries:
        entries_by_scope.setdefault(entry.external_id, []).append(entry)
    grouped: dict[UUID, dict[str, ReferenceT]] = {}
    entry_by_resource_id: dict[UUID, ResolvedContextEntry] = {}
    for scope_entries in entries_by_scope.values():
        if len(scope_entries) != 1:
            continue
        entry = scope_entries[0]
        grouped[entry.integration_resource_id] = {}
        entry_by_resource_id[entry.integration_resource_id] = entry
    for value in values:
        try:
            reference = reference_type.model_validate(value)
        except ValueError:
            continue
        scope_entries = entries_by_scope.get(reference.provider_scope_id, ())
        if len(scope_entries) != 1 or not reference.provider_entity_id.isdigit():
            continue
        references = grouped[scope_entries[0].integration_resource_id]
        references.setdefault(reference.provider_entity_id, reference)

    return tuple(
        (
            entry_by_resource_id[entry.integration_resource_id],
            tuple(grouped[entry.integration_resource_id][external_id] for external_id in ids),
        )
        for entry in entries
        if (ids := sorted(grouped.get(entry.integration_resource_id, {}))[:MAX_EXACT_REFERENCES])
    )
