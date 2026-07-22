# apps/api/integrations/airtable/operations/utils.py

"""Airtable record response helpers."""

from typing import Any

from services.agents.runtime.untrusted import UntrustedContent


def record_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"record_id": "", "created_time": "", "fields": {}}
    record_id = str(payload.get("id", "")).strip()
    fields = payload.get("fields")
    return {
        "record_id": record_id,
        "created_time": str(payload.get("createdTime", "")),
        "fields": _untrusted_value(fields if isinstance(fields, dict) else {}, record_id),
    }


def _untrusted_value(value: Any, record_id: str) -> Any:
    if isinstance(value, str):
        return UntrustedContent(
            source_kind="airtable_record",
            source_ref=record_id,
            content=value,
        )
    if isinstance(value, dict):
        return {key: _untrusted_value(item, record_id) for key, item in value.items()}
    if isinstance(value, list):
        return [_untrusted_value(item, record_id) for item in value]
    return value
