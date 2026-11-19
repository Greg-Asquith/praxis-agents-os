# apps/api/integrations/gmail/tools/send_mail_merge.py

"""Gmail mail merge runtime tool."""

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

from ..operations.send_merge_message import GmailMergeSender
from .utils import GMAIL_WRITE_BINDING, gmail_available, gmail_client_for_principal


async def _open_test_sender(deps: RuntimeDeps, entry: ResolvedContextEntry) -> GmailMergeSender:
    client = await gmail_client_for_principal(
        deps.db, actor=deps.user, workspace=deps.workspace, entry=entry
    )
    return GmailMergeSender(client)


GMAIL_MAIL_MERGE = MailMergeToolProvider(
    provider_key="gmail",
    label="Gmail",
    binding=GMAIL_WRITE_BINDING,
    open_test_sender=_open_test_sender,
)


async def gmail_send_mail_merge(
    ctx: RunContext[RuntimeDeps],
    subject: MergeSubject,
    body_html: MergeBody,
    recipients: MergeRecipients,
    fallbacks: MergeFallbacks = None,
) -> dict[str, Any]:
    return await run_mail_merge_tool(
        GMAIL_MAIL_MERGE,
        ctx,
        subject=subject,
        body_html=body_html,
        recipients=recipients,
        fallbacks=fallbacks,
    )


DEFINITION = mail_merge_tool_definition(
    GMAIL_MAIL_MERGE,
    name="gmail_send_mail_merge",
    function=gmail_send_mail_merge,
    send_tool_name="gmail_send_message",
    availability_check=gmail_available,
)
