# apps/api/integrations/gmail/operations/resolve_label_names.py

"""Resolve Gmail label IDs to operator-facing names."""

from contextlib import suppress
from typing import Any

from integrations.gmail.client import GmailClient

# System labels an operator recognizes; category/read-state noise stays out.
_SYSTEM_LABELS = {
    "INBOX": "Inbox",
    "STARRED": "Starred",
    "IMPORTANT": "Important",
    "SENT": "Sent",
    "DRAFT": "Draft",
    "SPAM": "Spam",
    "TRASH": "Trash",
}


async def resolve_label_names(client: GmailClient, *, label_ids: Any) -> list[str]:
    if not isinstance(label_ids, list) or not label_ids:
        return []

    names_by_id: dict[str, str] = {}
    # Label names are display enrichment; a lookup failure must not sink callers.
    with suppress(Exception):
        listing = await client.get(
            "users/me/labels",
            operation="resolve_label_names",
        )
        raw_labels = listing.get("labels") if isinstance(listing, dict) else None
        if isinstance(raw_labels, list):
            for label in raw_labels:
                if not isinstance(label, dict):
                    continue
                label_id = label.get("id")
                name = label.get("name")
                if (
                    label.get("type") == "user"
                    and isinstance(label_id, str)
                    and isinstance(name, str)
                ):
                    names_by_id[label_id] = name

    resolved: list[str] = []
    for label_id in label_ids:
        if not isinstance(label_id, str):
            continue
        if label_id in _SYSTEM_LABELS:
            resolved.append(_SYSTEM_LABELS[label_id])
        elif label_id in names_by_id:
            resolved.append(names_by_id[label_id])
    return resolved
