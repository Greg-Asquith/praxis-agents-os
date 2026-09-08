# apps/api/integrations/outlook_mail/tools/move_message.py

"""Move Outlook message through the shared approval and audit runtime."""

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

from ..operations.move_message import move_message
from ..operations.resolve_folder import resolve_folder
from ..operations.utils import MailWriteState
from ..references import OutlookMessageReference
from .mutations import FolderName, MoveInput
from .schemas import MoveOutput
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


async def outlook_mail_move_message(
    ctx: RunContext[RuntimeDeps],
    message: Annotated[OutlookMessageReference, Field(description="Message to move.")],
    destination_folder: FolderName,
) -> dict:
    try:
        args = MoveInput(message=message, destination_folder=destination_folder)
    except ValidationError:
        raise ModelRetry("Review the Outlook message fields and their required values.") from None
    entry = single_mailbox_entry(ctx.deps, args.message)

    async def operation(entry):
        state = MailWriteState(message_id=args.message.message_id, step="move")

        async def prepare() -> PreparedMailWrite:
            client = await mailbox_client(ctx, entry)
            destination_id = await resolve_folder(client, folder=args.destination_folder)
            pending = pending_write_detail(
                entry,
                action="move",
                fields={"destination_folder": args.destination_folder},
                message_id=args.message.message_id if args.message else None,
            )

            async def mutate() -> None:
                await move_message(
                    client,
                    state=state,
                    message_id=args.message.message_id,
                    destination_id=destination_id,
                )

            return PreparedMailWrite(pending, mutate)

        callbacks = MailWriteCallbacks(entry, state, prepare)
        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="outlook_mail_move_message",
            operation="move_message",
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
    name="outlook_mail_move_message",
    function=outlook_mail_move_message,
    description=(
        "Moves an Outlook message to another folder in the same mailbox. Use a standard folder "
        "name, such as archive, or an exact folder display name. Select exactly one Outlook "
        "mailbox."
    ),
    provider="outlook_mail",
    label="Move Outlook message",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=True,
    supports_approval=True,
    takes_ctx=True,
    timeout=90,
    output_model=MoveOutput,
    integration_binding=OUTLOOK_MAIL_WRITE_BINDING,
    availability_check=outlook_mail_available,
    approval_display_args=partial(mutation_display_args, MoveInput),
    presentation=ToolPresentation(
        icon="outlook_mail",
        running_label="Moving Outlook message",
        completed_label="Moved Outlook message",
        failed_label="Could not move Outlook message",
        approval_title="Move Outlook message",
        approve_label="Approve & Move",
        approval_prompt="The agent wants to move this message to the selected folder.",
        arg_fields=(
            ToolFieldPresentation(
                key="message",
                label="Message",
                format="entity",
                editable=True,
                entity_kind="outlook_message",
            ),
            ToolFieldPresentation(
                key="destination_folder",
                label="Destination folder",
                format="text",
                editable=True,
                placeholder="archive",
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
