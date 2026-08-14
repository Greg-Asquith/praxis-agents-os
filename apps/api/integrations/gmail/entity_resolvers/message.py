# apps/api/integrations/gmail/entity_resolvers/message.py

"""Gmail message lookup for shared runtime entity selectors."""

import asyncio
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from core.exceptions.integration import IntegrationNotFoundError
from integrations.gmail.operations.search_messages import get_message_metadata, search_messages
from integrations.gmail.references import GmailMessageReference
from integrations.gmail.tools.utils import GMAIL_BINDING, gmail_client_for_principal
from services.agents.runtime.untrusted import untrusted_content_text
from services.integrations.entity_references import (
    EntityChoice,
    EntityResolverDefinition,
    EntityResolverPage,
)

MAX_SEARCH_CHOICES = 25


def _offset(cursor: str | None) -> int:
    try:
        return max(int(cursor or "0"), 0)
    except ValueError:
        return 0


def _choice(entry, message: Mapping[str, Any]) -> EntityChoice:
    subject = untrusted_content_text(message.get("subject")) or "(no subject)"
    sender = untrusted_content_text(message.get("sender"))
    date = untrusted_content_text(message.get("date"))
    message_id = str(message.get("message_id", "")).strip()
    return EntityChoice.from_reference(
        GmailMessageReference(
            mailbox_id=entry.external_id,
            message_id=message_id,
            label=subject[:500],
            description=" · ".join(value for value in (sender, date) if value),
            scope_label=entry.display_name,
            sender=sender or None,
            date=date or None,
        ),
        icon="gmail",
    )


async def search_gmail_messages(ctx, search, _dependent_args, page_size, cursor):
    offset = _offset(cursor)
    request_limit = min(offset + page_size + 1, MAX_SEARCH_CHOICES)

    async def search_entry(entry) -> list[EntityChoice]:
        client = await gmail_client_for_principal(
            ctx.db,
            actor=ctx.actor,
            workspace=ctx.workspace,
            entry=entry,
        )
        result = await search_messages(
            client,
            query=search.strip() or "newer_than:30d",
            limit=request_limit,
        )
        return [
            _choice(entry, message)
            for message in result.get("messages", [])
            if isinstance(message, Mapping) and message.get("message_id")
        ]

    entries = ctx.active_context.compatible_entries(GMAIL_BINDING)
    choices = [
        choice
        for entry_choices in await asyncio.gather(*(search_entry(entry) for entry in entries))
        for choice in entry_choices
    ]
    bounded_choices = choices[:MAX_SEARCH_CHOICES]
    selected = bounded_choices[offset : offset + page_size]
    return EntityResolverPage(
        choices=tuple(selected),
        next_cursor=(
            str(offset + page_size) if len(bounded_choices) > offset + page_size else None
        ),
    )


async def resolve_gmail_messages(ctx, values: Sequence[Any], _dependent_args):
    entries_by_mailbox: dict[str, list[Any]] = defaultdict(list)
    for entry in ctx.active_context.compatible_entries(GMAIL_BINDING):
        entries_by_mailbox[entry.external_id].append(entry)
    grouped: dict[str, list[GmailMessageReference]] = defaultdict(list)
    for value in values:
        try:
            reference = GmailMessageReference.model_validate(value)
        except ValueError:
            continue
        matching = entries_by_mailbox.get(reference.mailbox_id, ())
        if len(matching) == 1:
            grouped[reference.mailbox_id].append(reference)

    choices: list[EntityChoice] = []
    for mailbox_id, references in grouped.items():
        entry = entries_by_mailbox[mailbox_id][0]
        client = await gmail_client_for_principal(
            ctx.db,
            actor=ctx.actor,
            workspace=ctx.workspace,
            entry=entry,
        )
        for reference in references[:25]:
            try:
                message = await get_message_metadata(client, reference.message_id)
            except IntegrationNotFoundError:
                # Messages can disappear between selection and exact hydration.
                # An omitted choice makes the stale reference unavailable without
                # turning the rest of the batch into a provider failure.
                continue
            choices.append(_choice(entry, message))
    return tuple(choices)


GMAIL_MESSAGE_RESOLVER = EntityResolverDefinition(
    entity_kind="gmail_message",
    reference_type=GmailMessageReference,
    search=search_gmail_messages,
    resolve=resolve_gmail_messages,
    max_page_size=20,
    requires_active_context=True,
    provider_key="gmail",
)
