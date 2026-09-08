# apps/api/integrations/outlook_mail/tools/update_message.py

"""Update Outlook message through the shared approval and audit runtime."""

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

from ..operations.update_message import update_message
from ..operations.utils import MailWriteState
from ..references import OutlookMessageReference
from .mutations import UpdateInput
from .schemas import UpdateOutput
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


async def outlook_mail_update_message(
    ctx: RunContext[RuntimeDeps],
    message: Annotated[OutlookMessageReference, Field(description="Message to update.")],
    is_read: Annotated[bool | None, Field(strict=True)] = None,
    flagged: Annotated[bool | None, Field(strict=True)] = None,
) -> dict:
    try:
        args = UpdateInput(message=message, is_read=is_read, flagged=flagged)
    except ValidationError:
        raise ModelRetry("Review the Outlook message fields and their required values.") from None
    entry = single_mailbox_entry(ctx.deps, args.message)

    async def operation(entry):
        state = MailWriteState(message_id=args.message.message_id, step="update")

        async def prepare() -> PreparedMailWrite:
            client = await mailbox_client(ctx, entry)
            pending = pending_write_detail(
                entry,
                action="update",
                fields={
                    key: value
                    for key, value in {"is_read": args.is_read, "flagged": args.flagged}.items()
                    if value is not None
                },
                message_id=args.message.message_id if args.message else None,
            )

            async def mutate() -> None:
                await update_message(
                    client,
                    state=state,
                    message_id=args.message.message_id,
                    is_read=args.is_read,
                    flagged=args.flagged,
                )

            return PreparedMailWrite(pending, mutate)

        callbacks = MailWriteCallbacks(entry, state, prepare)
        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="outlook_mail_update_message",
            operation="update_message",
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
    name="outlook_mail_update_message",
    function=outlook_mail_update_message,
    description=(
        "Changes an Outlook message's read status, flag status, or both. Omitted values leave "
        "that status unchanged. Select exactly one Outlook mailbox."
    ),
    provider="outlook_mail",
    label="Update Outlook message",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=True,
    supports_approval=True,
    takes_ctx=True,
    timeout=90,
    output_model=UpdateOutput,
    integration_binding=OUTLOOK_MAIL_WRITE_BINDING,
    availability_check=outlook_mail_available,
    approval_display_args=partial(mutation_display_args, UpdateInput),
    presentation=ToolPresentation(
        icon="outlook_mail",
        running_label="Updating Outlook message",
        completed_label="Updated Outlook message",
        failed_label="Could not update Outlook message",
        approval_title="Update Outlook message",
        approve_label="Approve & Update",
        approval_prompt="The agent wants to change the read or flag state of this message.",
        arg_fields=(
            ToolFieldPresentation(
                key="message",
                label="Message",
                format="entity",
                editable=True,
                entity_kind="outlook_message",
            ),
            ToolFieldPresentation(
                key="is_read", label="Read", format="boolean", editable=True, secondary=True
            ),
            ToolFieldPresentation(
                key="flagged", label="Flagged", format="boolean", editable=True, secondary=True
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
