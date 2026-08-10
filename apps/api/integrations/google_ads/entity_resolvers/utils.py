# apps/api/integrations/google_ads/entity_resolvers/utils.py

"""Shared input bounds and reference grouping for Google Ads entity resolvers."""

from collections.abc import Sequence
from typing import Any, Protocol
from uuid import UUID

from services.integrations.context.domain import (
    IntegrationBinding,
    ResolvedActiveContext,
    ResolvedContextEntry,
)
from services.integrations.entity_references import ScopedEntityReference


class _ResolverContext(Protocol):
    active_context: ResolvedActiveContext


MAX_EXACT_REFERENCES = 50


def group_scoped_references[ReferenceT: ScopedEntityReference](
    ctx: _ResolverContext,
    binding: IntegrationBinding,
    values: Sequence[Any],
    reference_type: type[ReferenceT],
) -> tuple[tuple[ResolvedContextEntry, tuple[ReferenceT, ...]], ...]:
    """Validate and group exact references in compatible context-entry order."""
    entries = ctx.active_context.compatible_entries(binding)
    grouped: dict[UUID, dict[str, ReferenceT]] = {
        entry.integration_resource_id: {} for entry in entries
    }
    for value in values:
        try:
            reference = reference_type.model_validate(value)
        except ValueError:
            continue
        references = grouped.get(reference.integration_resource_id)
        if references is None or not reference.external_id.isdigit():
            continue
        references.setdefault(reference.external_id, reference)

    return tuple(
        (
            entry,
            tuple(grouped[entry.integration_resource_id][external_id] for external_id in ids),
        )
        for entry in entries
        if (ids := sorted(grouped[entry.integration_resource_id])[:MAX_EXACT_REFERENCES])
    )


def bounded_offset(cursor: str | None, *, upper_bound: int) -> int:
    try:
        return min(max(int(cursor or "0"), 0), upper_bound)
    except ValueError:
        return 0


def unbounded_offset(cursor: str | None) -> int:
    """Decode an opaque non-negative offset, restarting safely when invalid."""
    try:
        return max(int(cursor or "0"), 0)
    except ValueError:
        return 0


def round_robin_window[T](
    groups: Sequence[Sequence[T]], *, offset: int, limit: int
) -> tuple[T, ...]:
    """Return a bounded window from a stable round-robin merge."""
    if limit < 1:
        return ()

    selected: list[T] = []
    merged_index = 0
    row_index = 0
    while len(selected) < limit:
        found = False
        for group in groups:
            if row_index >= len(group):
                continue
            found = True
            if merged_index >= offset:
                selected.append(group[row_index])
                if len(selected) == limit:
                    break
            merged_index += 1
        if not found:
            break
        row_index += 1
    return tuple(selected)
