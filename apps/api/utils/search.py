# apps/api/utils/search.py

"""Helpers for user-entered text search."""


def contains_pattern(search: str) -> str:
    """Returns an `ILIKE` substring pattern that matches the text literally; use `escape="\\\\"`."""
    escaped = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
