# apps/api/integrations/gmail/operations/count_thread_messages.py

"""Count the messages in a Gmail thread."""

from contextlib import suppress
from typing import Any

from integrations.gmail.client import GmailClient


async def count_thread_messages(client: GmailClient, *, thread_id: Any) -> int | None:
    if not isinstance(thread_id, str) or not thread_id:
        return None

    # Thread metadata is display enrichment; a lookup failure must not sink callers.
    with suppress(Exception):
        thread = await client.get(
            f"users/me/threads/{thread_id}",
            operation="count_thread_messages",
            params={"format": "minimal"},
        )
        messages = thread.get("messages") if isinstance(thread, dict) else None
        if isinstance(messages, list):
            return len(messages)
    return None
