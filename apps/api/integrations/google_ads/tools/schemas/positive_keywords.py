# apps/api/integrations/google_ads/tools/schemas/positive_keywords.py

"""Keyword text, bid, and URL types shared by the Google Ads keyword tools."""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import AfterValidator, Field

from .base import money_validator


def normalize_keyword_text(value: object) -> object:
    """Normalizes whitespace that Google Ads treats as equivalent."""
    return " ".join(value.split()) if isinstance(value, str) else value


def validate_keyword_word_count(value: str) -> str:
    if len(value.split()) > 10:
        raise ValueError("Google Ads keywords can contain at most 10 words")
    return value


GoogleAdsCpcBid = Annotated[
    str,
    Field(
        min_length=1,
        max_length=32,
        description=(
            "Optional cost-per-click bid in the Google Ads account currency, with up to "
            "six decimal places. Omit it to use the ad group's bid."
        ),
    ),
    money_validator("CPC bid"),
]


def _bounded_http_url(value: str) -> str:
    candidate = value.strip()
    if not re.fullmatch(r"https?://[^\s]+", candidate, flags=re.IGNORECASE):
        raise ValueError("Enter a complete HTTP or HTTPS URL.")
    return candidate


GoogleAdsFinalUrl = Annotated[
    str,
    Field(min_length=1, max_length=2048),
    AfterValidator(_bounded_http_url),
]
