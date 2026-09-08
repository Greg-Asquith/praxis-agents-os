# apps/api/tests/integrations/outlook_mail/support.py

"""Shared Outlook mailbox and run context fixtures."""

from types import SimpleNamespace
from uuid import uuid4

from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry


def entry(mailbox_id="mailbox"):
    return ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="outlook_mail",
        resource_type="outlook_mailbox",
        external_id=mailbox_id,
        display_name="dana@example.com",
        connection_id=uuid4(),
        connection_label="Outlook",
        connection_status="active",
        write_allowed=True,
        permissions_metadata={"time_zone": "GMT Standard Time"},
    )


def context(*entries, tool_name):
    return SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=entries),
            db=object(),
            user=object(),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4(), name="Mail agent"),
            run=SimpleNamespace(id=uuid4(), user_id=uuid4()),
        ),
        tool_name=tool_name,
        tool_call_id="call-1",
    )


def draft_payload(message_id="draft/=="):
    recipient = {"emailAddress": {"address": "dana@example.com", "name": "Dana"}}
    return {
        "id": message_id,
        "changeKey": "version-1",
        "isDraft": True,
        "subject": "Draft to send",
        "body": {"contentType": "html", "content": "<p>Reviewed draft</p>"},
        "toRecipients": [recipient],
        "ccRecipients": [],
        "bccRecipients": [],
        "replyTo": [],
        "from": recipient,
        "sender": recipient,
    }
