# apps/api/integrations/google_ads/entity_resolvers/utils.py

"""Shared input bounds and GAQL escaping for Google Ads entity resolvers."""

from collections.abc import Sequence


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
