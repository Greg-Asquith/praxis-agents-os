# apps/api/integrations/outlook_mail/tools/create_draft.py

"""Save Outlook draft through the shared approval and audit runtime."""

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

from ..operations.create_draft import create_draft
from ..operations.create_reply_draft import create_reply_draft
from ..operations.utils import MailWriteState
from ..references import OutlookMessageReference
from .mutations import DraftInput, MailBody, OptionalRecipients, Recipients, Subject
from .schemas import DraftOutput
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


async def outlook_mail_create_draft(
    ctx: RunContext[RuntimeDeps],
    to: Recipients | None = None,
    subject: Subject | None = None,
    body_html: MailBody = "",
    cc: OptionalRecipients | None = None,
    bcc: OptionalRecipients | None = None,
    reply_to: OutlookMessageReference | None = None,
    reply_all: Annotated[bool, Field(strict=True)] = False,
) -> dict:
    try:
        args = DraftInput(
            to=to,
            subject=subject,
            body_html=body_html,
            cc=cc,
            bcc=bcc,
            reply_to=reply_to,
            reply_all=reply_all,
        )
    except ValidationError:
        raise ModelRetry("Review the Outlook message fields and their required values.") from None
    entry = single_mailbox_entry(ctx.deps, args.reply_to)
    html = sanitize_preview_html(args.body_html)

    async def operation(entry):
        state = MailWriteState()

        async def prepare() -> PreparedMailWrite:
            client = await mailbox_client(ctx, entry)
            pending = pending_write_detail(
                entry,
                action="draft",
                fields={
                    **{
                        (f"{key}_source" if args.reply_to and values is None else count_key): (
                            "outlook_reply"
                            if args.reply_to and values is None
                            else len(values or [])
                        )
                        for key, count_key, values in (
                            ("to", "recipient_count", args.to),
                            ("cc", "cc_count", args.cc),
                            ("bcc", "bcc_count", args.bcc),
                        )
                    },
                    "reply_all": args.reply_all,
                },
                message_id=args.reply_to.message_id if args.reply_to else None,
            )

            async def mutate() -> None:
                if args.reply_to is not None:
                    await create_reply_draft(
                        client,
                        state=state,
                        message_id=args.reply_to.message_id,
                        action="createReplyAll" if args.reply_all else "createReply",
                        body_html=html,
                        cc=args.cc,
                        bcc=args.bcc,
                    )
                else:
                    await create_draft(
                        client,
                        state=state,
                        to=args.to,
                        subject=args.subject,
                        body_html=html,
                        cc=args.cc,
                        bcc=args.bcc,
                    )

            return PreparedMailWrite(pending, mutate)

        callbacks = MailWriteCallbacks(entry, state, prepare)
        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="outlook_mail_create_draft",
            operation="create_draft",
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
    name="outlook_mail_create_draft",
    function=outlook_mail_create_draft,
    description=(
        "Creates an Outlook email draft without sending it. Reply drafts include the quoted "
        "conversation. Select exactly one Outlook mailbox. To send the saved draft, use "
        "outlook_mail_send_draft."
    ),
    provider="outlook_mail",
    label="Save Outlook draft",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    supports_approval=True,
    takes_ctx=True,
    timeout=90,
    output_model=DraftOutput,
    integration_binding=OUTLOOK_MAIL_WRITE_BINDING,
    availability_check=outlook_mail_available,
    approval_display_args=partial(mutation_display_args, DraftInput),
    presentation=ToolPresentation(
        icon="outlook_mail",
        running_label="Saving Outlook draft",
        completed_label="Saved Outlook draft",
        failed_label="Could not save Outlook draft",
        approval_title="Save Outlook draft",
        approve_label="Approve & Save",
        approval_prompt="The agent wants to save a draft in Outlook. Nothing is sent. A reply draft includes the quoted conversation.",
        arg_fields=(
            ToolFieldPresentation(
                key="to", label="To", format="list", editable=True, secondary=True
            ),
            ToolFieldPresentation(
                key="subject", label="Subject", format="text", editable=True, secondary=True
            ),
            ToolFieldPresentation(key="body_html", label="Message", format="html", editable=True),
            ToolFieldPresentation(
                key="cc", label="Cc", format="list", editable=True, secondary=True
            ),
            ToolFieldPresentation(
                key="bcc", label="Bcc", format="list", editable=True, secondary=True
            ),
            ToolFieldPresentation(
                key="reply_to",
                label="Reply to",
                format="entity",
                editable=True,
                secondary=True,
                entity_kind="outlook_message",
            ),
            ToolFieldPresentation(
                key="reply_all", label="Reply all", format="boolean", editable=True, secondary=True
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
