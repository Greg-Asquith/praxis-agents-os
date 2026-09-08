# apps/api/integrations/outlook_mail/tools/reply_to_message.py

"""Reply in Outlook through the shared approval and audit runtime."""

from functools import partial
from typing import Annotated

from pydantic import Field, ValidationError
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

from ..operations.create_reply_draft import create_reply_draft
from ..operations.send_message import send_message
from ..operations.utils import MailWriteState, reject_draft_attachments
from ..references import OutlookMessageReference
from .mutations import MailBody, ReplyInput
from .schemas import ReplyOutput
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


async def outlook_mail_reply_to_message(
    ctx: RunContext[RuntimeDeps],
    message: Annotated[OutlookMessageReference, Field(description="Message to reply to.")],
    body_html: MailBody,
    reply_all: Annotated[bool, Field(strict=True)] = False,
) -> dict:
    try:
        args = ReplyInput(message=message, body_html=body_html, reply_all=reply_all)
    except ValidationError:
        raise ModelRetry("Review the Outlook message fields and their required values.") from None
    entry = single_mailbox_entry(ctx.deps, args.message)
    html = sanitize_preview_html(args.body_html)

    async def operation(entry):
        state = MailWriteState()

        async def prepare() -> PreparedMailWrite:
            client = await mailbox_client(ctx, entry)
            pending = pending_write_detail(
                entry,
                action="reply",
                fields={"reply_all": args.reply_all},
                message_id=args.message.message_id if args.message else None,
            )

            async def mutate() -> None:
                await create_reply_draft(
                    client,
                    state=state,
                    message_id=args.message.message_id,
                    action="createReplyAll" if args.reply_all else "createReply",
                    body_html=html,
                )
                state.step = "check_attachments"
                await reject_draft_attachments(
                    client, message_id=state.message_id, operation="reply_to_message"
                )
                await send_message(client, state=state)

            return PreparedMailWrite(pending, mutate)

        callbacks = MailWriteCallbacks(entry, state, prepare)
        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="outlook_mail_reply_to_message",
            operation="reply_to_message",
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
    name="outlook_mail_reply_to_message",
    function=outlook_mail_reply_to_message,
    description=(
        "Sends a reply to an Outlook message, with an option to reply to all recipients. The "
        "reply appears above the quoted conversation. Select exactly one Outlook mailbox. To send "
        "an existing reply draft, use outlook_mail_send_draft. Reply drafts with attachments must "
        "be sent in Outlook."
    ),
    provider="outlook_mail",
    label="Reply in Outlook",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    supports_approval=True,
    takes_ctx=True,
    timeout=90,
    output_model=ReplyOutput,
    integration_binding=OUTLOOK_MAIL_WRITE_BINDING,
    availability_check=outlook_mail_available,
    approval_display_args=partial(mutation_display_args, ReplyInput),
    presentation=ToolPresentation(
        icon="outlook_mail",
        running_label="Sending Outlook reply",
        completed_label="Sent Outlook reply",
        failed_label="Could not send Outlook reply",
        approval_title="Reply in Outlook",
        approve_label="Approve & Send",
        approval_prompt="Your reply is sent above the quoted conversation.",
        arg_fields=(
            ToolFieldPresentation(
                key="message",
                label="Message",
                format="entity",
                editable=True,
                entity_kind="outlook_message",
            ),
            ToolFieldPresentation(key="body_html", label="Reply", format="html", editable=True),
            ToolFieldPresentation(
                key="reply_all", label="Reply all", format="boolean", editable=True, secondary=True
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
