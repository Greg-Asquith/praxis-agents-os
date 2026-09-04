# apps/api/integrations/google_ads/operations/url_custom_parameters.py

"""Canonical Google Ads URL custom-parameter validation."""

import re
from collections.abc import Mapping, Sequence

_CUSTOM_PARAMETER_NAME = re.compile(r"[A-Za-z0-9]+")
MAX_URL_CUSTOM_PARAMETERS = 8
MAX_URL_CUSTOM_PARAMETER_NAME_BYTES = 16
MAX_URL_CUSTOM_PARAMETER_VALUE_BYTES = 200


def validate_url_custom_parameter_items(
    items: Sequence[tuple[str, str]],
) -> tuple[tuple[str, str], ...]:
    """Validate and preserve provider URL custom-parameter items."""
    if len(items) > MAX_URL_CUSTOM_PARAMETERS:
        raise ValueError("Google Ads accepts at most 8 URL custom parameters per keyword.")
    normalized: list[tuple[str, str]] = []
    seen: set[str] = set()
    for key, value in items:
        if (
            not key
            or len(key.encode("utf-8")) > MAX_URL_CUSTOM_PARAMETER_NAME_BYTES
            or _CUSTOM_PARAMETER_NAME.fullmatch(key) is None
        ):
            raise ValueError("URL custom parameter names must use 1-16 ASCII letters or numbers.")
        folded_key = key.casefold()
        if folded_key in seen:
            raise ValueError("URL custom parameter names must be unique, ignoring case.")
        if len(value.encode("utf-8")) > MAX_URL_CUSTOM_PARAMETER_VALUE_BYTES:
            raise ValueError("URL custom parameter values can contain at most 200 UTF-8 bytes.")
        seen.add(folded_key)
        normalized.append((key, value))
    return tuple(normalized)


def validate_url_custom_parameters(
    parameters: Mapping[str, str] | None,
) -> dict[str, str] | None:
    """Validate a parameter mapping without changing its spelling or values."""
    if parameters is None:
        return None
    return dict(validate_url_custom_parameter_items(tuple(parameters.items())))
