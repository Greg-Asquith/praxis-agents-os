# apps/api/integrations/google_ads/tools/utils/negative_keywords.py

"""Reusable validation and normalization for Google Ads negative keyword rows."""

from pydantic_ai import ModelRetry

from integrations.google_ads.tools.schemas.negative_keyword import NegativeKeywordEntry


def normalize_negative_keywords(
    keywords: list[NegativeKeywordEntry],
) -> list[NegativeKeywordEntry]:
    normalized: list[NegativeKeywordEntry] = []
    seen: set[tuple[str, str]] = set()
    for keyword in keywords:
        text = " ".join(keyword.text.split())
        if not text:
            continue
        if len(text) > 80:
            raise ModelRetry("Negative keywords must be 80 characters or fewer.")
        if len(text.split()) > 10:
            raise ModelRetry("Negative keywords must contain 10 words or fewer.")
        key = (text.casefold(), keyword.match_type)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(NegativeKeywordEntry(text=text, match_type=keyword.match_type))
    if not normalized:
        raise ModelRetry("Provide at least one non-empty negative keyword.")
    return normalized
