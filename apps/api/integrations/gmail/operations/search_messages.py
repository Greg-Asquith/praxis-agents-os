# apps/api/integrations/gmail/operations/search_messages.py

"""Search Gmail messages and fetch bounded metadata."""

import asyncio
from typing import Any

from integrations.gmail.client import GmailClient
from integrations.gmail.operations.utils import extract_headers, untrusted

MAX_SEARCH_RESULTS = 25
_HEADER_NAMES = ("From", "To", "Subject", "Date")


async def search_messages(client: GmailClient, *, query: str, limit: int) -> dict[str, Any]:
    capped_limit = min(max(limit, 1), MAX_SEARCH_RESULTS)
    payload = await client.get(
        "users/me/messages",
        operation="search_messages",
        params={"q": query, "maxResults": capped_limit},
    )
    message_refs = payload.get("messages") if isinstance(payload, dict) else None
    if not isinstance(message_refs, list):
        message_refs = []
    message_ids = [
        str(item.get("id", ""))
        for item in message_refs[:capped_limit]
        if isinstance(item, dict) and item.get("id")
    ]
    messages = await asyncio.gather(
        *(_message_metadata(client, message_id) for message_id in message_ids)
    )
    return {"messages": list(messages), "total": len(messages)}


async def _message_metadata(client: GmailClient, message_id: str) -> dict[str, Any]:
    payload = await client.get(
        f"users/me/messages/{message_id}",
        operation="search_message_metadata",
        params={"format": "metadata", "metadataHeaders": list(_HEADER_NAMES)},
    )
    headers = extract_headers(payload)
    return {
        "message_id": message_id,
        "sender": untrusted(message_id, headers.get("from", "")),
        "to": untrusted(message_id, headers.get("to", "")),
        "subject": untrusted(message_id, headers.get("subject", "")),
        "date": untrusted(message_id, headers.get("date", "")),
        "snippet": untrusted(message_id, str(payload.get("snippet", ""))),
    }




