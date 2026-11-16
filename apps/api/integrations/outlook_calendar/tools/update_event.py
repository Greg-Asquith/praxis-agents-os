# apps/api/integrations/outlook_calendar/tools/update_event.py

"""Update an Outlook event through the shared approval and audit runtime."""

from functools import partial
from typing import Annotated

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
from services.integrations.microsoft_graph.time import (
    graph_date_time,
    parse_local_datetime,
    validate_time_zone,
)
from services.integrations.operations import run_audited_integration_operation
from services.integrations.previews.sanitize import sanitize_preview_html
from services.integrations.write_lifecycle import PreparedIntegrationWrite

from ..operations.get_event import get_event_state
from ..operations.update_event import update_event
from ..operations.utils import CalendarWriteState, graph_attendees
from ..references import OutlookEventReference
from .mutations import UpdateEventInput
from .schemas import WriteOutput
from .utils import (
    OUTLOOK_CALENDAR_WRITE_BINDING,
    RESULTS_FIELD,
    CalendarWriteCallbacks,
    LocalDateTime,
    TimeZone,
    approved_default,
    bounded_output,
    calendar_client,
    event_calendar_entry,
    model_input,
    outlook_calendar_available,
    pending_write_detail,
    write_display_args,
)

_CHANGE_KEYS = ("subject", "start", "attendees", "body_html", "location")


def _validate_args(ctx: RunContext[RuntimeDeps], **args) -> None:
    event_calendar_entry(ctx.deps, model_input(lambda: UpdateEventInput.model_validate(args)).event)


def _graph_changes(args: UpdateEventInput, time_zone: str | None) -> dict:
    changes: dict = {}
    if args.subject is not None:
        changes["subject"] = args.subject
    if args.start is not None and args.end is not None and time_zone is not None:
        changes["start"] = graph_date_time(
            parse_local_datetime(args.start, field="start"), time_zone
        )
        changes["end"] = graph_date_time(parse_local_datetime(args.end, field="end"), time_zone)
    if args.attendees is not None:
        changes["attendees"] = graph_attendees(args.attendees)
    if args.body_html is not None:
        changes["body"] = {"contentType": "html", "content": sanitize_preview_html(args.body_html)}
    if args.location is not None:
        changes["location"] = {"displayName": args.location}
    return changes


async def outlook_calendar_update_event(
    ctx: RunContext[RuntimeDeps],
    event: Annotated[
        OutlookEventReference, Field(description="Event to change, from list or read events.")
    ],
    subject: Annotated[str | None, Field(max_length=255)] = None,
    start: LocalDateTime | None = None,
    end: LocalDateTime | None = None,
    time_zone: TimeZone = None,
    attendees: Annotated[
        list[str] | None,
        Field(max_length=100, description="Replaces the whole attendee list."),
    ] = None,
    body_html: Annotated[str | None, Field(max_length=50_000)] = None,
    location: Annotated[str | None, Field(max_length=255)] = None,
) -> dict:
    args = model_input(
        lambda: UpdateEventInput(
            event=event,
            subject=subject,
            start=start,
            end=end,
            time_zone=time_zone,
            attendees=attendees,
            body_html=body_html,
            location=location,
        )
    )
    entry = event_calendar_entry(ctx.deps, args.event)
    zone = (
        model_input(
            lambda: validate_time_zone(
                str(approved_default(ctx, "time_zone", args.time_zone) or "")
            )
        )
        if args.start is not None
        else None
    )

    async def operation(entry):
        state = CalendarWriteState(action="update", event_id=args.event.event_id)

        async def prepare() -> PreparedIntegrationWrite:
            client = await calendar_client(ctx, entry)
            current = await get_event_state(
                client,
                calendar_id=entry.external_id,
                event_id=args.event.event_id,
                operation="update_event",
            )
            state.event_type = current["type"]
            fields = {
                "changed": [key for key in _CHANGE_KEYS if getattr(args, key) is not None],
                "event_type": current["type"],
            }
            if args.attendees is not None:
                fields["attendee_count"] = len(args.attendees)
            if zone is not None:
                fields |= {"start": args.start, "end": args.end, "time_zone": zone}
            pending = pending_write_detail(
                entry, action="update", fields=fields, event_id=args.event.event_id
            )

            async def mutate() -> None:
                await update_event(
                    client,
                    state=state,
                    calendar_id=entry.external_id,
                    changes=_graph_changes(args, zone),
                )

            return PreparedIntegrationWrite(pending, mutate)

        callbacks = CalendarWriteCallbacks(entry, state, prepare)
        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="outlook_calendar_update_event",
            operation="update_event",
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
    name="outlook_calendar_update_event",
    function=outlook_calendar_update_event,
    description=(
        "Changes an Outlook event's subject, times, attendees, description, or location, and "
        "sends attendees an update. Omitted fields stay unchanged; attendees replaces the whole "
        "list. Set start and end together. On a recurring event this changes only the listed "
        "fields of that occurrence or series and never its recurrence."
    ),
    provider="outlook_calendar",
    label="Update Outlook Event",
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
    approval_display_args=partial(write_display_args, UpdateEventInput),
    approval_input_model=UpdateEventInput,
    presentation=ToolPresentation(
        icon="outlook_calendar",
        running_label="Updating Outlook Event",
        completed_label="Updated Outlook Event",
        failed_label="Could Not Update Outlook Event",
        approval_title="Update Outlook Event",
        approve_label="Approve & Send",
        approval_prompt="Attendees receive an update when you approve.",
        arg_fields=(
            ToolFieldPresentation(
                key="event",
                label="Event",
                format="entity",
                editable=True,
                entity_kind="outlook_event",
            ),
            ToolFieldPresentation(
                key="subject",
                label="Subject",
                format="text",
                editable=True,
                secondary=True,
                width="full",
            ),
            ToolFieldPresentation(
                key="start",
                label="Start",
                format="datetime",
                editable=True,
                secondary=True,
                width="third",
            ),
            ToolFieldPresentation(
                key="end",
                label="End",
                format="datetime",
                editable=True,
                secondary=True,
                width="third",
            ),
            ToolFieldPresentation(
                key="time_zone",
                label="Time Zone",
                format="text",
                editable=True,
                secondary=True,
                width="third",
            ),
            ToolFieldPresentation(
                key="attendees", label="Attendees", format="list", editable=True, secondary=True
            ),
            ToolFieldPresentation(
                key="location",
                label="Location",
                format="text",
                editable=True,
                secondary=True,
                width="half",
            ),
            ToolFieldPresentation(
                key="body_html",
                label="Description",
                format="html",
                editable=True,
                secondary=True,
                width="half",
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
