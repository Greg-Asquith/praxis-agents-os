# apps/api/integrations/google_ads/operations/get_report_field.py

"""Get metadata for one Google Ads report resource or field."""

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from core.exceptions.integration import IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy

from ..client import GOOGLE_ADS_API_VERSION, GoogleAdsClient

_FIELD_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*$")
_OPERATION = "get_report_field"


async def get_report_field(
    client: GoogleAdsClient,
    *,
    field_name: str,
) -> dict[str, Any]:
    normalized_name = validate_report_field_name(field_name)
    payload = await client.get(
        f"googleAdsFields/{quote(normalized_name, safe='')}",
        operation=_OPERATION,
        policy=IntegrationRequestPolicy.READ,
    )
    raise_for_missing_report_field(payload, normalized_name, operation=_OPERATION)
    field = parse_report_field(payload, operation=_OPERATION)
    if field["name"] != normalized_name:
        raise IntegrationValidationError(
            f"Google Ads did not return metadata for {normalized_name}",
            provider_key="google_ads",
            operation=_OPERATION,
        )

    return {
        "api_version": GOOGLE_ADS_API_VERSION,
        "name": field["name"],
        "category": field["category"],
        "data_type": field["data_type"],
        "selectable": field["selectable"],
        "filterable": field["filterable"],
        "sortable": field["sortable"],
        "is_repeated": field["is_repeated"],
        "type_url": field["type_url"],
        "enum_values": field["enum_values"],
        "selectable_with": field["selectable_with"],
        "attribute_resources": field["attribute_resources"],
        "metrics": field["metrics"],
        "segments": field["segments"],
    }


def validate_report_field_name(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("Google Ads report field name must be a string")
    normalized = value.strip()
    if len(normalized) > 256 or _FIELD_NAME_PATTERN.fullmatch(normalized) is None:
        raise ValueError(
            "Google Ads report field name must start with a letter and contain only "
            "lowercase letters, digits, underscores, and non-empty dot-separated segments"
        )
    return normalized


def parse_report_field(payload: Any, *, operation: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise _invalid_response(operation)

    name = _required_string(payload, "name", operation=operation)
    category = _required_string(payload, "category", operation=operation)
    data_type = _required_string(payload, "dataType", operation=operation)
    type_url = payload.get("typeUrl")
    if type_url is not None and not isinstance(type_url, str):
        raise _invalid_response(operation)

    return {
        "name": name,
        "category": category,
        "data_type": data_type,
        "selectable": _boolean(payload, "selectable", operation=operation),
        "filterable": _boolean(payload, "filterable", operation=operation),
        "sortable": _boolean(payload, "sortable", operation=operation),
        "is_repeated": _boolean(payload, "isRepeated", operation=operation),
        "type_url": type_url.strip() or None if type_url is not None else None,
        "enum_values": _name_array(payload, "enumValues", operation=operation),
        "selectable_with": _name_array(payload, "selectableWith", operation=operation),
        "attribute_resources": _name_array(payload, "attributeResources", operation=operation),
        "metrics": _name_array(payload, "metrics", operation=operation),
        "segments": _name_array(payload, "segments", operation=operation),
    }


def _required_string(payload: Mapping[str, Any], key: str, *, operation: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not (normalized := value.strip()):
        raise _invalid_response(operation)
    return normalized


def _boolean(payload: Mapping[str, Any], key: str, *, operation: str) -> bool:
    value = payload.get(key, False)
    if not isinstance(value, bool):
        raise _invalid_response(operation)
    return value


def _name_array(payload: Mapping[str, Any], key: str, *, operation: str) -> list[str]:
    value = payload.get(key, [])
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise _invalid_response(operation)
    return sorted(item.strip() for item in value)


def raise_for_missing_report_field(
    payload: Any,
    expected_name: str,
    *,
    operation: str,
) -> None:
    if not isinstance(payload, Mapping):
        return
    name = payload.get("name")
    if name is None or (isinstance(name, str) and not name.strip()):
        raise IntegrationValidationError(
            f"Google Ads did not return metadata for {expected_name}",
            provider_key="google_ads",
            operation=operation,
        )


def _invalid_response(operation: str) -> IntegrationValidationError:
    return IntegrationValidationError(
        "Google Ads returned an invalid report field response",
        provider_key="google_ads",
        operation=operation,
    )
