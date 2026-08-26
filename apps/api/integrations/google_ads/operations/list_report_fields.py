# apps/api/integrations/google_ads/operations/list_report_fields.py

"""List bounded Google Ads fields and compatibility for one report resource."""

import re
from collections.abc import Mapping
from typing import Any

from core.exceptions.integration import IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy

from ..client import GOOGLE_ADS_API_VERSION, GoogleAdsClient
from .get_report_field import parse_report_field, raise_for_missing_report_field

_RESOURCE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_COMPATIBILITY_LIMIT = 100
_OPERATION = "list_report_fields"
_LIKE_ESCAPES = {
    "\\": "\\\\",
    "'": "\\'",
    "[": "[[]",
    "]": "[]]",
    "%": "[%]",
    "_": "[_]",
}


async def list_report_fields(
    client: GoogleAdsClient,
    *,
    resource: str,
    search: str | None,
    limit: int,
) -> dict[str, Any]:
    normalized_resource = validate_report_resource(resource)
    normalized_search = normalize_report_field_search(search)
    validate_report_field_limit(limit)

    resource_payload = await client.get(
        f"googleAdsFields/{normalized_resource}",
        operation=_OPERATION,
        policy=IntegrationRequestPolicy.READ,
    )
    raise_for_missing_report_field(
        resource_payload,
        normalized_resource,
        operation=_OPERATION,
    )
    resource_field = parse_report_field(resource_payload, operation=_OPERATION)
    if resource_field["name"] != normalized_resource:
        raise IntegrationValidationError(
            f"Google Ads did not return report metadata for {normalized_resource}",
            provider_key="google_ads",
            operation=_OPERATION,
        )

    query = _field_query(
        normalized_resource,
        search=normalized_search,
        request_limit=limit + 1,
    )
    search_payload = await client.post(
        "googleAdsFields:search",
        operation=_OPERATION,
        policy=IntegrationRequestPolicy.READ,
        json={"query": query},
    )
    fields, field_count, fields_truncated = _parse_search_response(
        search_payload,
        limit=limit,
    )

    metrics = _matching_names(resource_field["metrics"], normalized_search)
    segments = _matching_names(resource_field["segments"], normalized_search)
    attribute_resources = resource_field["attribute_resources"]
    return {
        "api_version": GOOGLE_ADS_API_VERSION,
        "resource": normalized_resource,
        "attribute_resources": attribute_resources[:_COMPATIBILITY_LIMIT],
        "attribute_resource_count": len(attribute_resources),
        "metrics": metrics[:limit],
        "metric_count": len(metrics),
        "segments": segments[:limit],
        "segment_count": len(segments),
        "compatibility_truncated": len(attribute_resources) > _COMPATIBILITY_LIMIT,
        "fields": fields[:limit],
        "field_count": field_count,
        "truncated": fields_truncated or len(metrics) > limit or len(segments) > limit,
    }


def validate_report_resource(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("Google Ads report resource must be a string")
    normalized = value.strip()
    if len(normalized) > 128 or _RESOURCE_PATTERN.fullmatch(normalized) is None:
        raise ValueError(
            "Google Ads report resource must start with a letter and contain only "
            "lowercase letters, digits, and underscores"
        )
    return normalized


def normalize_report_field_search(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("Google Ads report field search must be a string")
    normalized = value.strip()
    if len(normalized) > 100:
        raise ValueError("Google Ads report field search must not exceed 100 characters")
    return normalized.casefold() or None


def validate_report_field_limit(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 100:
        raise ValueError("Google Ads report field limit must be between 1 and 100")


def _field_query(resource: str, *, search: str | None, request_limit: int) -> str:
    conditions = [f"name LIKE '{resource}.%'"]
    if search is not None:
        escaped = "".join(_LIKE_ESCAPES.get(character, character) for character in search)
        conditions.append(f"name LIKE '%{escaped}%'")
    return (
        "SELECT name, category, data_type, selectable, filterable, sortable, is_repeated "
        f"WHERE {' AND '.join(conditions)} ORDER BY name LIMIT {request_limit}"
    )


def _parse_search_response(
    payload: Any,
    *,
    limit: int,
) -> tuple[list[dict[str, Any]], int, bool]:
    if not isinstance(payload, Mapping):
        raise IntegrationValidationError(
            "Google Ads returned an invalid report field search response",
            provider_key="google_ads",
            operation=_OPERATION,
        )

    raw_results = payload.get("results", [])
    if not isinstance(raw_results, list):
        raise IntegrationValidationError(
            "Google Ads returned an invalid report field search response",
            provider_key="google_ads",
            operation=_OPERATION,
        )
    fields: list[dict[str, Any]] = []
    for item in raw_results:
        try:
            field = parse_report_field(item, operation=_OPERATION)
        except IntegrationValidationError:
            continue
        fields.append(
            {
                key: field[key]
                for key in (
                    "name",
                    "category",
                    "data_type",
                    "selectable",
                    "filterable",
                    "sortable",
                    "is_repeated",
                )
            }
        )
    fields.sort(key=lambda item: item["name"])

    total = _total_results_count(payload.get("totalResultsCount"))
    if total is None:
        next_page_token = payload.get("nextPageToken")
        if next_page_token is not None and not isinstance(next_page_token, str):
            raise IntegrationValidationError(
                "Google Ads returned an invalid report field search response",
                provider_key="google_ads",
                operation=_OPERATION,
            )
        return (
            fields,
            len(fields),
            len(raw_results) > limit or len(fields) > limit or bool(next_page_token),
        )
    return fields, total, total > limit


def _total_results_count(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return int(value)
    return None


def _matching_names(values: list[str], search: str | None) -> list[str]:
    if search is None:
        return values
    needle = search.casefold()
    return [value for value in values if needle in value.casefold()]
