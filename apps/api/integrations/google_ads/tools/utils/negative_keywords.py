# apps/api/integrations/google_ads/tools/utils/negative_keywords.py

"""Reusable validation and normalization for Google Ads negative keyword rows."""

from pydantic_ai import ModelRetry

from integrations.google_ads.tools.schemas.negative_keyword import (
    NegativeKeywordEntry,
    NegativeKeywordRemovalEntry,
)

type NegativeKeywordRow = NegativeKeywordEntry | NegativeKeywordRemovalEntry


def normalize_negative_keywords(
    keywords: list[NegativeKeywordRow],
) -> list[NegativeKeywordRow]:
    canonical = [
        keyword.model_copy(update={"text": " ".join(keyword.text.split())}) for keyword in keywords
    ]
    any_texts = {keyword.text.casefold() for keyword in canonical if keyword.match_type == "ANY"}
    normalized: list[NegativeKeywordRow] = []
    seen: set[tuple[str, str]] = set()
    for keyword in canonical:
        text = keyword.text
        if not text:
            continue
        if len(text) > 80:
            raise ModelRetry("Negative keywords must be 80 characters or fewer.")
        if len(text.split()) > 10:
            raise ModelRetry("Negative keywords must contain 10 words or fewer.")
        if keyword.match_type != "ANY" and text.casefold() in any_texts:
            continue
        key = (text.casefold(), keyword.match_type)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(keyword)
    if not normalized:
        raise ModelRetry("Provide at least one non-empty negative keyword.")
    return normalized
