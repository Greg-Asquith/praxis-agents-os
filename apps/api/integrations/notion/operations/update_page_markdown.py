# apps/api/integrations/notion/operations/update_page_markdown.py

"""Prepare an exact-text Notion page update against live page state."""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

import httpx2
from pydantic_ai import ModelRetry

from core.exceptions.integration import IntegrationError
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.http import IntegrationRequestPolicy

from ..client import NotionClient
from ..references import NotionPageReference
from .properties import NotionMutationTarget, get_page_mutation_target, validate_mutation_scope
from .utils import invalid_mutation_response, validate_mutation_body_size

NO_MATCH_ERROR_MESSAGE = "Notion couldn't find text matching one or more replacements."
MULTIPLE_MATCHES_ERROR_MESSAGE = (
    "Notion found multiple matches for a replacement that was limited to one match."
)
CONTENT_VALIDATION_ERROR_MESSAGE = "Notion rejected the page content update."


class NotionReplacementRecordLike(Protocol):
    """Describes one normalized exact-text replacement."""

    old_text: str
    new_text: str
    replace_all: str


@dataclass(frozen=True)
class UpdatePageMarkdownPreparation:
    """Carries the live page and normalized replacement records."""

    page: NotionMutationTarget
    replacements: tuple[NotionReplacementRecordLike, ...]


async def prepare_update_page_markdown(
    client: NotionClient,
    entry: ResolvedContextEntry,
    *,
    page: NotionPageReference,
    replacements: Sequence[NotionReplacementRecordLike],
) -> UpdatePageMarkdownPreparation:
    """Validates an exact-text update against the live target page."""
    validate_mutation_scope(entry, page.provider_scope_id, reference_label="page")
    if not replacements:
        raise ModelRetry("Add at least one exact-text replacement.")
    target = await get_page_mutation_target(client, page)
    return UpdatePageMarkdownPreparation(page=target, replacements=tuple(replacements))


def update_page_markdown_request_body(
    prepared: UpdatePageMarkdownPreparation,
) -> dict[str, Any]:
    """Builds the exact provider request body for prepared text replacements."""
    payload = {
        "type": "update_content",
        "update_content": {
            "content_updates": [
                {
                    "old_str": record.old_text,
                    "new_str": record.new_text,
                    "replace_all_matches": record.replace_all == "yes",
                }
                for record in prepared.replacements
            ]
        },
    }
    validate_mutation_body_size(payload)
    return payload


async def update_page_markdown(
    client: NotionClient,
    *,
    prepared: UpdatePageMarkdownPreparation,
) -> dict[str, Any]:
    """Applies exact-text replacements with one non-retried provider mutation."""
    page_id = prepared.page.external_id
    payload = await client.patch(
        f"pages/{quote(page_id, safe='')}/markdown",
        operation="update_page_markdown",
        policy=IntegrationRequestPolicy.MUTATION,
        json=update_page_markdown_request_body(prepared),
        validation_error_detail=_content_validation_error_detail,
    )
    if (
        not isinstance(payload, Mapping)
        or payload.get("object") != "page_markdown"
        or payload.get("id") != page_id
        or not isinstance(payload.get("markdown"), str)
        or not isinstance(payload.get("truncated"), bool)
        or not isinstance(payload.get("unknown_block_ids"), list)
    ):
        raise invalid_mutation_response("update_page_markdown")

    last_edited_time: str | None = None
    try:
        page_payload = await client.get(
            f"pages/{quote(page_id, safe='')}",
            operation="get_page_after_markdown_update",
            policy=IntegrationRequestPolicy.READ,
        )
    except (IntegrationError, asyncio.CancelledError):
        pass
    else:
        if (
            isinstance(page_payload, Mapping)
            and page_payload.get("object") == "page"
            and page_payload.get("id") == page_id
            and page_payload.get("in_trash") is False
            and isinstance(page_payload.get("last_edited_time"), str)
        ):
            last_edited_time = page_payload["last_edited_time"][:100]

    return {
        "id": page_id,
        "applied_replacements": len(prepared.replacements),
        "page_truncated": payload["truncated"],
        "last_edited_time": last_edited_time,
    }


def _content_validation_error_detail(response: httpx2.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return CONTENT_VALIDATION_ERROR_MESSAGE
    message = payload.get("message") if isinstance(payload, Mapping) else None
    normalized = " ".join(message.lower().split()) if isinstance(message, str) else ""
    if any(marker in normalized for marker in ("multiple match", "more than one")):
        return MULTIPLE_MATCHES_ERROR_MESSAGE
    if any(
        marker in normalized
        for marker in ("no match", "0 match", "not found", "could not find", "doesn't match")
    ):
        return NO_MATCH_ERROR_MESSAGE
    return CONTENT_VALIDATION_ERROR_MESSAGE
