# apps/api/integrations/google_ads/tools/verifiers/utils.py

"""Shared validation helpers for Google Ads execution verifiers."""

from collections.abc import Mapping, Sequence

from pydantic_ai import ModelRetry


def validated_ids(values: Sequence[str], *, invalid_message: str) -> tuple[str, ...]:
    normalized = tuple(sorted(set(values)))
    if not normalized or any(not value.isdigit() for value in normalized):
        raise ModelRetry(invalid_message)
    return normalized


def mapping_ids(values: Sequence[Mapping[str, object]]) -> set[str]:
    return {str(value.get("id", "")) for value in values}
