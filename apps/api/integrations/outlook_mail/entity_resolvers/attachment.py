# apps/api/integrations/outlook_mail/entity_resolvers/attachment.py

"""Hydrates attachment references returned by Outlook message reads."""

from urllib.parse import quote

from core.exceptions.integration import IntegrationNotFoundError
from services.integrations.entity_references import (
    EntityChoice,
    EntityResolverDefinition,
    EntityResolverPage,
)
from services.integrations.http import IntegrationRequestPolicy

from ..operations.utils import message_path, object_payload, text
from ..references import OutlookAttachmentReference
from ..tools.utils import OUTLOOK_MAIL_BINDING, mailbox_client_for_principal


async def search_attachments(_ctx, _search, _dependent_args, _page_size, _cursor):
    # Attachments are selected from a message read, not a mailbox-wide search.
    return EntityResolverPage(choices=())


async def resolve_attachments(ctx, values, _dependent_args):
    entries = ctx.active_context.compatible_entries(OUTLOOK_MAIL_BINDING)
    choices = []
    for value in values[:25]:
        try:
            reference = OutlookAttachmentReference.model_validate(value)
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
            attachment = object_payload(
                await client.get(
                    f"{message_path(reference.message_id)}/attachments/{quote(reference.attachment_id, safe='')}",
                    operation="resolve_attachment",
                    policy=IntegrationRequestPolicy.READ,
                    params={"$select": "id,name"},
                ),
                operation="resolve_attachment",
            )
        except IntegrationNotFoundError:
            continue
        if attachment.get("id") == reference.attachment_id:
            choices.append(
                EntityChoice.from_reference(
                    reference.model_copy(
                        update={
                            "label": text(attachment.get("name")) or "Outlook attachment",
                            "scope_label": entry.display_name[:500],
                        }
                    ),
                    icon="outlook_mail",
                )
            )
    return tuple(choices)


OUTLOOK_ATTACHMENT_RESOLVER = EntityResolverDefinition(
    entity_kind="outlook_attachment",
    reference_type=OutlookAttachmentReference,
    search=search_attachments,
    resolve=resolve_attachments,
    max_page_size=20,
    requires_active_context=True,
    provider_key="outlook_mail",
)
