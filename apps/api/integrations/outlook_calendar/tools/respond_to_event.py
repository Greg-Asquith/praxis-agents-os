# apps/api/integrations/outlook_calendar/tools/respond_to_event.py

"""Respond to an Outlook invitation through the shared approval and audit runtime."""

from functools import partial
from typing import Annotated, Literal

from pydantic import Field
from pydantic_ai import RunContext

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
from services.integrations.write_lifecycle import PreparedIntegrationWrite

from ..operations.respond_to_event import respond_to_event
from ..operations.utils import CalendarWriteState
from ..references import OutlookEventReference
from .mutations import RespondToEventInput
from .schemas import WriteOutput
from .utils import (
    OUTLOOK_CALENDAR_WRITE_BINDING,
    RESULTS_FIELD,
    CalendarWriteCallbacks,
    bounded_output,
    calendar_client,
    event_calendar_entry,
    model_input,
    outlook_calendar_available,
    pending_write_detail,
    write_display_args,
)


def _validate_args(ctx: RunContext[RuntimeDeps], **args) -> None:
    parsed = model_input(lambda: RespondToEventInput.model_validate(args))
    event_calendar_entry(ctx.deps, parsed.event)


async def outlook_calendar_respond_to_event(
    ctx: RunContext[RuntimeDeps],
    event: Annotated[
        OutlookEventReference, Field(description="Invitation to answer, from list or read events.")
    ],
    response: Literal["accept", "tentative", "decline"],
    comment: Annotated[str, Field(max_length=2_000)] = "",
    send_response: Annotated[
        bool, Field(description="Tells the organiser. When false, only your calendar changes.")
    ] = True,
) -> dict:
    args = model_input(
        lambda: RespondToEventInput(
            event=event, response=response, comment=comment, send_response=send_response
        )
    )
    entry = event_calendar_entry(ctx.deps, args.event)

    async def operation(entry):
        state = CalendarWriteState(action=args.response, event_id=args.event.event_id)

        async def prepare() -> PreparedIntegrationWrite:
            client = await calendar_client(ctx, entry)
            pending = pending_write_detail(
                entry,
                action="respond",
                fields={"response": args.response, "send_response": args.send_response},
                event_id=args.event.event_id,
            )

            async def mutate() -> None:
                await respond_to_event(
                    client,
                    state=state,
                    calendar_id=entry.external_id,
                    response=args.response,
                    comment=args.comment,
                    send_response=args.send_response,
                )

            return PreparedIntegrationWrite(pending, mutate)

        callbacks = CalendarWriteCallbacks(entry, state, prepare)
        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="outlook_calendar_respond_to_event",
            operation="respond_to_event",
            execute=callbacks.execute,
            prepare_pending_operation=callbacks.prepare,
        )

    return bounded_output(
        await run_context_scope(
            ctx,
            binding=OUTLOOK_CALENDAR_WRITE_BINDING,
            provider_scope_id=entry.external_id,
            operation=operation,
        )
    )


DEFINITION = RuntimeToolDefinition(
    name="outlook_calendar_respond_to_event",
    function=outlook_calendar_respond_to_event,
    description=(
        "Accepts, tentatively accepts, or declines an Outlook invitation, with an optional "
        "comment to the organiser."
    ),
    provider="outlook_calendar",
    label="Respond to Outlook Event",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    supports_approval=True,
    takes_ctx=True,
    args_validator=_validate_args,
    timeout=90,
    output_model=WriteOutput,
    integration_binding=OUTLOOK_CALENDAR_WRITE_BINDING,
    availability_check=outlook_calendar_available,
    approval_display_args=partial(write_display_args, RespondToEventInput),
    approval_input_model=RespondToEventInput,
    presentation=ToolPresentation(
        icon="outlook_calendar",
        running_label="Responding to Outlook Event",
        completed_label="Responded to Outlook Event",
        failed_label="Could Not Respond to Outlook Event",
        approval_title="Respond to Outlook Event",
        approve_label="Approve & Respond",
        approval_prompt="The organiser is told your response when Send Response is on.",
        arg_fields=(
            ToolFieldPresentation(
                key="event",
                label="Event",
                format="entity",
                editable=True,
                entity_kind="outlook_event",
            ),
            ToolFieldPresentation(
                key="response",
                label="Response",
                format="text",
                editable=True,
                options=("accept", "tentative", "decline"),
            ),
            ToolFieldPresentation(
                key="send_response",
                label="Send Response",
                format="boolean",
                editable=True,
                secondary=True,
            ),
            ToolFieldPresentation(
                key="comment", label="Comment", format="multiline", editable=True, secondary=True
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
