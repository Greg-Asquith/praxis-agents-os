# apps/api/integrations/notion/operations/utils.py

"""Notion response normalization and bounded value helpers."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import islice
from typing import Any, Literal, TypedDict
from uuid import UUID

from pydantic_core import to_jsonable_python

from core.exceptions.integration import (
    IntegrationFailureDisposition,
    IntegrationValidationError,
)
from services.agents.runtime.untrusted import UntrustedNode

MAX_RICH_TEXT_CHARS = 2_000
MAX_EMAIL_CHARS = 200
MAX_PHONE_NUMBER_CHARS = 200
MAX_PROPERTIES = 100
MAX_MULTI_SELECT_VALUES = 100
MAX_NOTION_PROVIDER_CURSOR_CHARS = 8_192
MAX_COMPACT_PROPERTIES_BYTES = 24 * 1024
MAX_NOTION_MUTATION_BODY_BYTES = 500_000


@dataclass(frozen=True)
class CompactPropertiesResult:
    values: dict[str, Any]
    truncated: bool


class PaginationEnvelope(TypedDict):
    results: list[Any]
    next_cursor: str | None
    has_more: bool
    request_status: dict[str, Any] | None


def pagination_envelope(payload: Any, *, operation: str) -> PaginationEnvelope:
    """Returns a validated, bounded Notion list envelope."""
    if not isinstance(payload, Mapping) or not isinstance(payload.get("results"), list):
        raise IntegrationValidationError(
            "Notion returned an invalid list response",
            provider_key="notion",
            operation=operation,
        )
    has_more = payload.get("has_more")
    if not isinstance(has_more, bool):
        raise IntegrationValidationError(
            "Notion returned an invalid pagination status",
            provider_key="notion",
            operation=operation,
        )
    cursor = payload.get("next_cursor")
    if cursor is not None and (
        not isinstance(cursor, str) or not cursor or len(cursor) > MAX_NOTION_PROVIDER_CURSOR_CHARS
    ):
        raise IntegrationValidationError(
            "Notion returned an invalid pagination cursor",
            provider_key="notion",
            operation=operation,
        )
    if has_more != (cursor is not None):
        raise IntegrationValidationError(
            "Notion returned inconsistent pagination fields",
            provider_key="notion",
            operation=operation,
        )
    request_status = payload.get("request_status")
    if request_status is not None and (
        not isinstance(request_status, Mapping)
        or request_status.get("type")
        not in {
            "complete",
            "incomplete",
        }
    ):
        raise IntegrationValidationError(
            "Notion returned an invalid request status",
            provider_key="notion",
            operation=operation,
        )
    return {
        "results": list(payload["results"]),
        "next_cursor": cursor,
        "has_more": has_more,
        "request_status": dict(request_status) if isinstance(request_status, Mapping) else None,
    }


def notion_id(payload: Mapping[str, Any]) -> str:
    return str(payload.get("id", "")).strip()


def page_title(payload: Mapping[str, Any]) -> str:
    properties = payload.get("properties")
    if not isinstance(properties, Mapping):
        return ""
    for value in properties.values():
        if isinstance(value, Mapping) and value.get("type") == "title":
            return rich_text(value.get("title"))
    return ""


def data_source_title(payload: Mapping[str, Any]) -> str:
    return rich_text(payload.get("title"))


def rich_text(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    return "".join(str(item.get("plain_text", "")) for item in value if isinstance(item, Mapping))[
        :MAX_RICH_TEXT_CHARS
    ]


def untrusted_text(content: str, *, source_kind: str, source_ref: str) -> UntrustedNode:
    return UntrustedNode(
        source_kind=source_kind,
        source_ref=source_ref,
        content=content,
    )


def normalized_search_result(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, Mapping):
        return None
    kind = payload.get("object")
    if kind not in {"page", "data_source"}:
        return None
    item_id = notion_id(payload)
    if not item_id:
        return None
    title = page_title(payload) if kind == "page" else data_source_title(payload)
    source_kind = "notion_page" if kind == "page" else "notion_data_source"
    return {
        "kind": kind,
        "id": item_id,
        "title": untrusted_text(title or "(untitled)", source_kind=source_kind, source_ref=item_id),
        "url": str(payload.get("url", ""))[:2_000],
        "last_edited_time": str(payload.get("last_edited_time", ""))[:100],
    }


def compact_properties(payload: Any, *, page_id: str) -> CompactPropertiesResult:
    if not isinstance(payload, Mapping):
        return CompactPropertiesResult(values={}, truncated=False)
    result: dict[str, Any] = {}
    truncated = len(payload) > MAX_PROPERTIES
    for raw_name, raw_property in islice(payload.items(), MAX_PROPERTIES):
        name = str(raw_name)[:500]
        if not name or not isinstance(raw_property, Mapping):
            continue
        property_type = str(raw_property.get("type", "unknown"))[:100]
        if property_type == "title":
            continue
        value = _compact_property(raw_property, property_type, page_id=page_id)
        candidate = {**result, name: value}
        if serialized_json_bytes(candidate) > MAX_COMPACT_PROPERTIES_BYTES:
            truncated = True
            continue
        result = candidate
    return CompactPropertiesResult(values=result, truncated=truncated)


def _compact_property(payload: Mapping[str, Any], property_type: str, *, page_id: str) -> Any:
    value = payload.get(property_type)
    if property_type in {"title", "rich_text"}:
        return _node(rich_text(value), page_id)
    if property_type == "number":
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    if property_type == "checkbox":
        return value if isinstance(value, bool) else None
    if property_type in {"url", "email", "phone_number"}:
        max_chars = {
            "url": MAX_RICH_TEXT_CHARS,
            "email": MAX_EMAIL_CHARS,
            "phone_number": MAX_PHONE_NUMBER_CHARS,
        }[property_type]
        return _node(str(value)[:max_chars], page_id) if value is not None else None
    if property_type in {"select", "status"}:
        return _named_value(value, page_id=page_id)
    if property_type == "formula":
        return _compact_formula(value, page_id=page_id)
    if property_type == "multi_select":
        if not isinstance(value, list):
            return []
        return [
            node
            for item in value[:MAX_MULTI_SELECT_VALUES]
            if (node := _named_value(item, page_id=page_id)) is not None
        ]
    if property_type == "date":
        return _compact_date(value, page_id=page_id)
    return {"type": property_type or "unknown"}


def _named_value(value: Any, *, page_id: str) -> UntrustedNode | None:
    if not isinstance(value, Mapping) or value.get("name") is None:
        return None
    return _node(str(value["name"])[:MAX_RICH_TEXT_CHARS], page_id)


def _compact_formula(value: Any, *, page_id: str) -> Any:
    if not isinstance(value, Mapping):
        return {"unsupported_formula_type": "unknown"}
    formula_type = value.get("type")
    result = value.get(formula_type) if isinstance(formula_type, str) else None
    if formula_type == "number":
        return result if isinstance(result, (int, float)) and not isinstance(result, bool) else None
    if formula_type == "string":
        return _node(result[:MAX_RICH_TEXT_CHARS], page_id) if isinstance(result, str) else None
    if formula_type == "boolean":
        return result if isinstance(result, bool) else None
    if formula_type == "date":
        return _compact_date(result, page_id=page_id)
    return {
        "unsupported_formula_type": formula_type[:100]
        if isinstance(formula_type, str)
        else "unknown"
    }


def _compact_date(value: Any, *, page_id: str) -> dict[str, UntrustedNode] | None:
    if not isinstance(value, Mapping):
        return None
    return {
        key: _node(str(value[key])[:MAX_RICH_TEXT_CHARS], page_id)
        for key in ("start", "end", "time_zone")
        if value.get(key) is not None
    }


def _node(content: str, page_id: str) -> UntrustedNode:
    return untrusted_text(
        content,
        source_kind="notion_data_source",
        source_ref=page_id,
    )


def bounded_utf8(value: str, *, max_bytes: int) -> tuple[str, int, bool]:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value, len(encoded), False
    bounded = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return bounded, len(bounded.encode("utf-8")), True


def serialized_json_bytes(value: Any) -> int:
    """Returns the compact JSON size used for provider result bounds."""
    jsonable = to_jsonable_python(value)
    return len(json.dumps(jsonable, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def validate_mutation_body_size(payload: Mapping[str, Any]) -> None:
    """Rejects a Notion mutation request that exceeds the provider payload limit."""
    if serialized_json_bytes(payload) > MAX_NOTION_MUTATION_BODY_BYTES:
        raise ValueError(
            f"Notion mutation request exceeds the {MAX_NOTION_MUTATION_BODY_BYTES}-byte limit"
        )


def normalized_page_mutation_response(
    payload: Any,
    *,
    operation: str,
    expected_id: str | None = None,
    forbidden_id: str | None = None,
    require_new_uuid: bool = False,
) -> dict[str, str]:
    """Returns safe fields from a verified synchronous page mutation response."""
    if not isinstance(payload, Mapping) or payload.get("object") != "page":
        raise _invalid_mutation_response(operation)
    page_id = payload.get("id")
    in_trash = payload.get("in_trash")
    last_edited_time = payload.get("last_edited_time")
    url = payload.get("url")
    if (
        not isinstance(page_id, str)
        or not page_id.strip()
        or not isinstance(in_trash, bool)
        or in_trash
        or not isinstance(last_edited_time, str)
        or not last_edited_time
        or not isinstance(url, str)
        or not url
    ):
        raise _invalid_mutation_response(operation)
    normalized_id = page_id.strip()
    if expected_id is not None and normalized_id != expected_id:
        raise _invalid_mutation_response(operation)
    if forbidden_id is not None and normalized_id == forbidden_id:
        raise _invalid_mutation_response(operation)
    if require_new_uuid:
        try:
            UUID(normalized_id)
        except ValueError as exc:
            raise _invalid_mutation_response(operation) from exc
    return {
        "id": normalized_id,
        "url": url[:2_000],
        "last_edited_time": last_edited_time[:100],
    }


def invalid_mutation_response(operation: str) -> IntegrationValidationError:
    """Builds an ambiguous error for a malformed successful mutation response."""
    return _invalid_mutation_response(operation)


def _invalid_mutation_response(operation: str) -> IntegrationValidationError:
    return IntegrationValidationError(
        "Notion returned an invalid mutation response",
        provider_key="notion",
        operation=operation,
        failure_disposition=IntegrationFailureDisposition.AMBIGUOUS,
    )


type NotionObjectKind = Literal["page", "data_source", "all"]
