# apps/api/integrations/gmail/operations/utils.py

from typing import Any

from services.agents.runtime.untrusted import UntrustedContent


def extract_headers(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        return {}
    message_payload = payload.get("payload")
    raw_headers = message_payload.get("headers") if isinstance(message_payload, dict) else None
    if not isinstance(raw_headers, list):
        return {}
    return {
        str(item.get("name", "")).lower(): str(item.get("value", ""))
        for item in raw_headers
        if isinstance(item, dict) and item.get("name")
    }


def untrusted(message_id: str, content: str) -> UntrustedContent:
    return UntrustedContent(source_kind="gmail_message", source_ref=message_id, content=content)
