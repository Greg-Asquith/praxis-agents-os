# apps/api/integrations/outlook_mail/tools/send_draft.py

"""Sends the existing draft after approval of its retained contents."""

from typing import Annotated

from pydantic import Field
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
from services.integrations.approved_display_args import approved_display_args
from services.integrations.context.targeted import run_context_scope
from services.integrations.operations import run_audited_integration_operation

from ..operations.read_draft import read_draft
from ..operations.send_message import send_message
from ..operations.utils import MailWriteState
from ..references import OutlookMessageReference
from .schemas import SendOutput
from .utils import (
    OUTLOOK_MAIL_WRITE_BINDING,
    RESULTS_FIELD,
    MailWriteCallbacks,
    PreparedMailWrite,
    bounded_output,
    mailbox_client,
    mailbox_client_for_principal,
    outlook_mail_available,
    pending_write_detail,
    single_mailbox_entry,
)


async def draft_display_args(deps: RuntimeDeps, args: dict) -> dict:
    reference = OutlookMessageReference.model_validate(args["message"])
    entry = single_mailbox_entry(deps, reference)
    if not entry.write_allowed:
        raise ModelRetry("Enable writes for the selected Outlook mailbox before sending a draft.")
    client = await mailbox_client_for_principal(
        deps.db, actor=deps.user, workspace=deps.workspace, entry=entry
    )
    draft = await read_draft(client, message_id=reference.message_id)
    return {
        "message": reference.model_dump(mode="json"),
        "_draft": draft.approval_details(),
    }


async def outlook_mail_send_draft(
    ctx: RunContext[RuntimeDeps],
    message: Annotated[
        OutlookMessageReference,
        Field(description="The existing draft reference returned by create draft or search."),
    ],
) -> dict:
    """Sends a reviewed draft in place, including a previously created reply draft."""
    entry = single_mailbox_entry(ctx.deps, message)
    approved = approved_display_args(ctx)
    reference = OutlookMessageReference.model_validate(approved.get("message"))
    details = approved.get("_draft")
    if reference.identity() != message.identity() or not isinstance(details, dict):
        raise ModelRetry("Prepare this draft for review again before sending it.")

    async def operation(entry):
        state = MailWriteState(message_id=message.message_id, step="send")

        async def prepare() -> PreparedMailWrite:
            client = await mailbox_client(ctx, entry)
            draft = await read_draft(client, message_id=message.message_id)
            if draft.approval_details()["fingerprint"] != details.get("fingerprint"):
                raise ModelRetry("The draft changed after review. Prepare it for approval again.")
            state.web_link = draft.web_link
            pending = pending_write_detail(
                entry,
                action="send",
                fields={
                    "recipient_count": len(draft.to_recipients),
                    "cc_count": len(draft.cc_recipients),
                    "bcc_count": len(draft.bcc_recipients),
                },
                message_id=message.message_id,
            )

            async def mutate() -> None:
                await send_message(client, state=state)

            return PreparedMailWrite(pending, mutate)

        callbacks = MailWriteCallbacks(entry, state, prepare)
        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="outlook_mail_send_draft",
            operation="send_draft",
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
    name="outlook_mail_send_draft",
    function=outlook_mail_send_draft,
    description=(
        "Sends an existing Outlook draft as saved, including a reply draft, using its message "
        "reference. Use this after creating and reviewing a draft. Select exactly one Outlook "
        "mailbox. Drafts with attachments must be sent in Outlook."
    ),
    provider="outlook_mail",
    label="Send Outlook draft",
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
    approval_display_args=draft_display_args,
    presentation=ToolPresentation(
        icon="outlook_mail",
        running_label="Sending Outlook draft",
        completed_label="Outlook draft sent",
        failed_label="Could not send Outlook draft",
        approval_title="Send Outlook draft",
        approval_prompt="Send the draft as it is saved in Outlook.",
        arg_fields=(
            ToolFieldPresentation(
                key="message", label="Draft", format="entity", entity_kind="outlook_message"
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
