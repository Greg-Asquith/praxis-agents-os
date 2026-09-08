# apps/api/integrations/outlook_mail/tools/send_message.py

"""Send Outlook email through the shared approval and audit runtime."""

from functools import partial

from pydantic import ValidationError
from pydantic_ai import ModelRetry, RunContext

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_EXTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_EXTERNAL_WRITE,
    TOOL_POLICY_APPROVAL,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.integrations.context.targeted import run_context_scope
from services.integrations.operations import run_audited_integration_operation
from services.integrations.previews.sanitize import sanitize_preview_html

from ..operations.create_draft import create_draft
from ..operations.send_message import send_message
from ..operations.utils import MailWriteState
from .mutations import (
    MailBody,
    OptionalRecipients,
    Recipients,
    SendMessageInput,
    Subject,
)
from .schemas import SendOutput
from .utils import (
    OUTLOOK_MAIL_WRITE_BINDING,
    RESULTS_FIELD,
    MailWriteCallbacks,
    PreparedMailWrite,
    bounded_output,
    mailbox_client,
    mutation_display_args,
    outlook_mail_available,
    pending_write_detail,
    single_mailbox_entry,
)


async def outlook_mail_send_message(
    ctx: RunContext[RuntimeDeps],
    to: Recipients,
    subject: Subject,
    body_html: MailBody,
    cc: OptionalRecipients | None = None,
    bcc: OptionalRecipients | None = None,
) -> dict:
    try:
        args = SendMessageInput(to=to, subject=subject, body_html=body_html, cc=cc, bcc=bcc)
    except ValidationError:
        raise ModelRetry("Review the Outlook message fields and their required values.") from None
    entry = single_mailbox_entry(ctx.deps, None)
    html = sanitize_preview_html(args.body_html)

    async def operation(entry):
        state = MailWriteState()

        async def prepare() -> PreparedMailWrite:
            client = await mailbox_client(ctx, entry)
            pending = pending_write_detail(
                entry,
                action="send",
                fields={
                    "recipient_count": len(args.to),
                    "cc_count": len(args.cc or []),
                    "bcc_count": len(args.bcc or []),
                },
                message_id=None,
            )

            async def mutate() -> None:
                await create_draft(
                    client,
                    state=state,
                    to=args.to,
                    subject=args.subject,
                    body_html=html,
                    cc=args.cc,
                    bcc=args.bcc,
                )
                await send_message(client, state=state)

            return PreparedMailWrite(pending, mutate)

        callbacks = MailWriteCallbacks(entry, state, prepare)
        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="outlook_mail_send_message",
            operation="send_message",
            execute=callbacks.execute,
            prepare_pending_operation=callbacks.prepare,
        )

    return bounded_output(
        await run_context_scope(
            ctx,
            binding=OUTLOOK_MAIL_WRITE_BINDING,
            provider_scope_id=entry.external_id,
            operation=operation,
        )
    )


DEFINITION = RuntimeToolDefinition(
    name="outlook_mail_send_message",
    function=outlook_mail_send_message,
    description=(
        "Sends a new email from the selected Outlook mailbox. Select exactly one mailbox. To send "
        "an existing draft, use outlook_mail_send_draft."
    ),
    provider="outlook_mail",
    label="Send Outlook email",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    supports_approval=True,
    takes_ctx=True,
    timeout=90,
    output_model=SendOutput,
    integration_binding=OUTLOOK_MAIL_WRITE_BINDING,
    availability_check=outlook_mail_available,
    approval_display_args=partial(mutation_display_args, SendMessageInput),
    presentation=ToolPresentation(
        icon="outlook_mail",
        running_label="Sending Outlook email",
        completed_label="Sent Outlook email",
        failed_label="Could not send Outlook email",
        approval_title="Send Outlook email",
        approve_label="Approve & Send",
        approval_prompt="The agent wants to send this email from the selected mailbox.",
        arg_fields=(
            ToolFieldPresentation(key="to", label="To", format="list", editable=True),
            ToolFieldPresentation(key="subject", label="Subject", format="text", editable=True),
            ToolFieldPresentation(key="body_html", label="Message", format="html", editable=True),
            ToolFieldPresentation(
                key="cc", label="Cc", format="list", editable=True, secondary=True
            ),
            ToolFieldPresentation(
                key="bcc", label="Bcc", format="list", editable=True, secondary=True
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
