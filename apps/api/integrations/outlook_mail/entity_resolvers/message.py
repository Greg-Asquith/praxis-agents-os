# apps/api/integrations/outlook_mail/entity_resolvers/message.py

"""Resolves Outlook message choices within the active mailbox context."""

from collections import Counter

from core.exceptions.integration import IntegrationNotFoundError
from services.integrations.entity_references import (
    EntityChoice,
    EntityResolverDefinition,
    EntityResolverPage,
)
from services.integrations.http import IntegrationRequestPolicy

from ..operations.utils import message_path, object_payload, text
from ..references import OutlookMessageReference
from ..tools.utils import OUTLOOK_MAIL_BINDING, mailbox_client_for_principal


def _choice(entry, message: dict) -> EntityChoice:
    return EntityChoice.from_reference(
        OutlookMessageReference(
            mailbox_id=entry.external_id,
            message_id=message["id"],
            label=text(message.get("subject")) or "(no subject)",
            description=text(message.get("receivedDateTime"), 100) or None,
            scope_label=entry.display_name[:500],
        ),
        icon="outlook_mail",
    )


async def search_messages(ctx, search, _dependent_args, page_size, cursor):
    try:
        offset = max(0, min(int(cursor or "0"), 25))
    except ValueError:
        offset = 0
    choices = []
    entries = ctx.active_context.compatible_entries(OUTLOOK_MAIL_BINDING)
    mailbox_counts = Counter(entry.external_id for entry in entries)
    for entry in entries:
        if mailbox_counts[entry.external_id] != 1:
            continue
        if len(choices) >= 25:
            break
        client = await mailbox_client_for_principal(
            ctx.db, actor=ctx.actor, workspace=ctx.workspace, entry=entry
        )
        params = {
            "$select": "id,subject,from,receivedDateTime",
            "$orderby": "receivedDateTime desc",
            "$top": 25,
        }
        if search.strip():
            escaped = search.strip()[:500].replace("'", "''")
            params["$filter"] = (
                f"receivedDateTime ge 0001-01-01T00:00:00Z and contains(subject,'{escaped}')"
            )
        messages = await client.paginate(
            "/me/mailFolders/inbox/messages",
            operation="resolve_message",
            params=params,
            max_items=25 - len(choices),
            max_pages=5,
        )
        choices.extend(
            _choice(entry, message) for message in messages if text(message.get("id"), 512)
        )
    return EntityResolverPage(
        choices=tuple(choices[offset : offset + page_size]),
        next_cursor=str(offset + page_size) if len(choices) > offset + page_size else None,
    )


async def resolve_messages(ctx, values, _dependent_args):
    entries = ctx.active_context.compatible_entries(OUTLOOK_MAIL_BINDING)
    choices = []
    for value in values[:25]:
        try:
            reference = OutlookMessageReference.model_validate(value)
        except ValueError:
            continue
        matching = [entry for entry in entries if entry.external_id == reference.mailbox_id]
        if len(matching) != 1:
            continue
        entry = matching[0]
        client = await mailbox_client_for_principal(
            ctx.db, actor=ctx.actor, workspace=ctx.workspace, entry=entry
        )
        try:
            message = object_payload(
                await client.get(
                    message_path(reference.message_id),
                    operation="resolve_message",
                    policy=IntegrationRequestPolicy.READ,
                    params={"$select": "id,subject,from,receivedDateTime"},
                ),
                operation="resolve_message",
            )
        except IntegrationNotFoundError:
            continue
        if message.get("id") == reference.message_id:
            choices.append(_choice(entry, message))
    return tuple(choices)


OUTLOOK_MESSAGE_RESOLVER = EntityResolverDefinition(
    entity_kind="outlook_message",
    reference_type=OutlookMessageReference,
    search=search_messages,
    resolve=resolve_messages,
    max_page_size=20,
    requires_active_context=True,
    provider_key="outlook_mail",
)
