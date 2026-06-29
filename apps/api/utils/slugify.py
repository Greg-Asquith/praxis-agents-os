# apps/api/utils/slugify.py

"""
Reusable slug utilities for IDs and URLs.

Policy: strict lowercase alphanumerics only.
"""

import re


def slugify(value: str, max_length: int = 100) -> str:
    """Generate a URL-safe slug with hyphens separating words.

    - Lowercases the value
    - Replaces non-alphanumeric characters with hyphens
    - Collapses multiple hyphens and trims from ends
    - Enforces `max_length` limit
    """
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower())
    slug = re.sub(r"-+", "-", slug)  # Collapse multiple hyphens
    slug = slug.strip("-")  # Remove leading/trailing hyphens
    if max_length > 0:
        slug = slug[:max_length].rstrip("-")
    return slug


def slugify_alnum(value: str, default: str = "org", max_length: int = 50) -> str:
    """Generate a slug containing only lowercase [a-z0-9].

    - Trims whitespace, lowercases
    - Removes any non-alphanumeric characters
    - Falls back to `default` if empty after cleaning
    - Enforces `max_length` limit
    """
    cleaned = re.sub(r"[^a-z0-9]+", "", (value or "").strip().lower())
    if not cleaned:
        cleaned = default
    if max_length > 0:
        cleaned = cleaned[:max_length]
    return cleaned
