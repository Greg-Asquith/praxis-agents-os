# apps/api/integrations/outlook_mail/tools/send_mail_merge.py

"""Outlook mail merge runtime tool."""

from typing import Any

from pydantic_ai import RunContext

from services.agents.runtime.context import RuntimeDeps
from services.integrations.context.domain import ResolvedContextEntry
from services.mail_merge import (
    MailMergeToolProvider,
    MergeBody,
    MergeFallbacks,
    MergeRecipients,
    MergeSubject,
    mail_merge_tool_definition,
    run_mail_merge_tool,
)

from ..operations.send_merge_message import OutlookMergeSender
from .utils import OUTLOOK_MAIL_WRITE_BINDING, mailbox_client_for_principal, outlook_mail_available


async def _open_test_sender(deps: RuntimeDeps, entry: ResolvedContextEntry) -> OutlookMergeSender:
    return OutlookMergeSender(
        await mailbox_client_for_principal(
            deps.db, actor=deps.user, workspace=deps.workspace, entry=entry, send_errors=True
        )
    )


OUTLOOK_MAIL_MERGE = MailMergeToolProvider(
    provider_key="outlook_mail",
    label="Outlook",
    binding=OUTLOOK_MAIL_WRITE_BINDING,
    open_test_sender=_open_test_sender,
)


async def outlook_mail_send_mail_merge(
    ctx: RunContext[RuntimeDeps],
    subject: MergeSubject,
    body_html: MergeBody,
    recipients: MergeRecipients,
    fallbacks: MergeFallbacks = None,
) -> dict[str, Any]:
    return await run_mail_merge_tool(
        OUTLOOK_MAIL_MERGE,
        ctx,
        subject=subject,
        body_html=body_html,
        recipients=recipients,
        fallbacks=fallbacks,
    )


DEFINITION = mail_merge_tool_definition(
    OUTLOOK_MAIL_MERGE,
    name="outlook_mail_send_mail_merge",
    function=outlook_mail_send_mail_merge,
    send_tool_name="outlook_mail_send_message",
    availability_check=outlook_mail_available,
)
