# apps/api/integrations/outlook_calendar/tools/cancel_event.py

"""Cancel or delete an Outlook event through the shared approval and audit runtime."""

from functools import partial
from typing import Annotated

from pydantic import Field
from pydantic_ai import RunContext

from core.exceptions.integration import IntegrationFailureDisposition, IntegrationValidationError
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

from ..operations.cancel_event import cancel_event
from ..operations.delete_event import delete_event
from ..operations.get_event import get_event_state
from ..operations.utils import CalendarWriteState
from ..references import OutlookEventReference
from .mutations import CancelEventInput
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
    event_calendar_entry(ctx.deps, model_input(lambda: CancelEventInput.model_validate(args)).event)


def _not_organizer() -> IntegrationValidationError:
    return IntegrationValidationError(
        "Only the organiser can cancel this meeting",
        provider_key="outlook_calendar",
        operation="cancel_event",
        error_code="not_organizer",
        failure_disposition=IntegrationFailureDisposition.NOT_DISPATCHED,
    )


async def outlook_calendar_cancel_event(
    ctx: RunContext[RuntimeDeps],
    event: Annotated[
        OutlookEventReference, Field(description="Event to cancel, from list or read events.")
    ],
    comment: Annotated[str, Field(max_length=2_000)] = "",
) -> dict:
    args = model_input(lambda: CancelEventInput(event=event, comment=comment))
    entry = event_calendar_entry(ctx.deps, args.event)

    async def operation(entry):
        state = CalendarWriteState(action="cancel", event_id=args.event.event_id)

        async def prepare() -> PreparedIntegrationWrite:
            client = await calendar_client(ctx, entry)
            current = await get_event_state(
                client,
                calendar_id=entry.external_id,
                event_id=args.event.event_id,
                operation="cancel_event",
            )
            # Organisers with attendees cancel so attendees hear; otherwise nobody else is told.
            organizer = current["is_organizer"]
            if organizer:
                state.action = "cancelled" if current["attendee_count"] else "deleted"
            pending = pending_write_detail(
                entry,
                action="cancel",
                fields={
                    "action": state.action,
                    "is_organizer": organizer,
                    "attendee_count": current["attendee_count"],
                    "event_type": current["type"],
                },
                event_id=args.event.event_id,
            )

            async def mutate() -> None:
                if not organizer:
                    raise _not_organizer()
                if state.action == "cancelled":
                    await cancel_event(
                        client, state=state, calendar_id=entry.external_id, comment=args.comment
                    )
                else:
                    await delete_event(client, state=state, calendar_id=entry.external_id)

            return PreparedIntegrationWrite(pending, mutate)

        callbacks = CalendarWriteCallbacks(entry, state, prepare)
        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="outlook_calendar_cancel_event",
            operation="cancel_event",
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
    name="outlook_calendar_cancel_event",
    function=outlook_calendar_cancel_event,
    description=(
        "Cancels an Outlook meeting you organise and sends attendees the cancellation with the "
        "comment. An event with no attendees is deleted. To turn down someone else's meeting, "
        "use outlook_calendar_respond_to_event with decline."
    ),
    provider="outlook_calendar",
    label="Cancel Outlook Event",
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
    approval_display_args=partial(write_display_args, CancelEventInput),
    approval_input_model=CancelEventInput,
    presentation=ToolPresentation(
        icon="outlook_calendar",
        running_label="Cancelling Outlook Event",
        completed_label="Cancelled Outlook Event",
        failed_label="Could Not Cancel Outlook Event",
        approval_title="Cancel Outlook Event",
        approve_label="Approve & Cancel",
        approval_prompt=(
            "Attendees receive a cancellation when you approve. An event with no attendees is "
            "deleted."
        ),
        arg_fields=(
            ToolFieldPresentation(
                key="event",
                label="Event",
                format="entity",
                editable=True,
                entity_kind="outlook_event",
            ),
            ToolFieldPresentation(
                key="comment", label="Message", format="multiline", editable=True, secondary=True
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
