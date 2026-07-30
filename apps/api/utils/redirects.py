# apps/api/utils/redirects.py

"""Validation helpers for browser redirect targets."""

import unicodedata
from urllib.parse import urlparse


def safe_next_path(next_path: str | None) -> str | None:
    """Return a same-origin absolute path, or ``None`` for an unsafe target."""
    if not next_path:
        return None
    if "\\" in next_path or any(
        char.isspace() or unicodedata.category(char) == "Cc" for char in next_path
    ):
        return None
    if not next_path.startswith("/") or next_path.startswith("//"):
        return None

    parsed = urlparse(next_path)
    if parsed.scheme or parsed.netloc:
        return None
    return next_path
