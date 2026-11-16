# apps/api/integrations/outlook_calendar/tools/create_event.py

"""Create an Outlook event through the shared approval and audit runtime."""

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
from services.integrations.microsoft_graph.time import (
    graph_date_time,
    parse_local_datetime,
    validate_time_zone,
)
from services.integrations.operations import run_audited_integration_operation
from services.integrations.previews.sanitize import sanitize_preview_html
from services.integrations.write_lifecycle import PreparedIntegrationWrite

from ..operations.create_event import create_event
from ..operations.utils import CalendarWriteState, graph_attendees
from ..references import OutlookCalendarReference
from .mutations import CreateEventInput
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
    model_input,
    outlook_calendar_available,
    pending_write_detail,
    select_calendar_entry,
    transaction_id,
    write_display_args,
)


def _validate_args(ctx: RunContext[RuntimeDeps], **args) -> None:
    parsed = model_input(lambda: CreateEventInput.model_validate(args))
    select_calendar_entry(ctx.deps, parsed.calendar)


def _graph_event(args: CreateEventInput, time_zone: str, transaction: str) -> dict:
    event = {
        "subject": args.subject,
        "start": graph_date_time(parse_local_datetime(args.start, field="start"), time_zone),
        "end": graph_date_time(parse_local_datetime(args.end, field="end"), time_zone),
        "isAllDay": args.is_all_day,
        "showAs": args.show_as,
        "attendees": graph_attendees(args.attendees or []),
        "isOnlineMeeting": args.is_online_meeting,
        "transactionId": transaction,
    }
    if args.body_html:
        event["body"] = {"contentType": "html", "content": sanitize_preview_html(args.body_html)}
    if args.location:
        event["location"] = {"displayName": args.location}
    if args.is_online_meeting:
        event["onlineMeetingProvider"] = "teamsForBusiness"
    return event


async def outlook_calendar_create_event(
    ctx: RunContext[RuntimeDeps],
    subject: Annotated[str, Field(min_length=1, max_length=255)],
    start: LocalDateTime,
    end: LocalDateTime,
    time_zone: TimeZone = None,
    attendees: Annotated[
        list[str] | None,
        Field(max_length=100, description="Attendee email addresses. Each receives an invitation."),
    ] = None,
    body_html: Annotated[str, Field(max_length=50_000)] = "",
    location: Annotated[str, Field(max_length=255)] = "",
    is_online_meeting: Annotated[
        bool, Field(description="Adds a Microsoft Teams meeting link.")
    ] = False,
    is_all_day: Annotated[
        bool, Field(description="Start and end at midnight on the first and following day.")
    ] = False,
    show_as: Literal["free", "tentative", "busy", "oof", "workingElsewhere"] = "busy",
    calendar: Annotated[
        OutlookCalendarReference | None,
        Field(description="Calendar for the event. Defaults to the selected default calendar."),
    ] = None,
) -> dict:
    args = model_input(
        lambda: CreateEventInput(
            subject=subject,
            start=start,
            end=end,
            time_zone=time_zone,
            attendees=attendees,
            body_html=body_html,
            location=location,
            is_online_meeting=is_online_meeting,
            is_all_day=is_all_day,
            show_as=show_as,
            calendar=calendar,
        )
    )
    shown = approved_default(ctx, "calendar", args.calendar)
    entry = select_calendar_entry(
        ctx.deps,
        model_input(lambda: OutlookCalendarReference.model_validate(shown)) if shown else None,
    )
    zone = model_input(
        lambda: validate_time_zone(str(approved_default(ctx, "time_zone", args.time_zone) or ""))
    )
    transaction = transaction_id(ctx)

    async def operation(entry):
        state = CalendarWriteState(action="create")

        async def prepare() -> PreparedIntegrationWrite:
            client = await calendar_client(ctx, entry)
            pending = pending_write_detail(
                entry,
                action="create",
                fields={
                    "attendee_count": len(args.attendees or []),
                    "start": args.start,
                    "end": args.end,
                    "time_zone": zone,
                    "is_all_day": args.is_all_day,
                    "is_online_meeting": args.is_online_meeting,
                    "transaction_id": transaction,
                },
            )

            async def mutate() -> None:
                await create_event(
                    client,
                    state=state,
                    calendar_id=entry.external_id,
                    event=_graph_event(args, zone, transaction),
                )

            return PreparedIntegrationWrite(pending, mutate)

        callbacks = CalendarWriteCallbacks(entry, state, prepare)
        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="outlook_calendar_create_event",
            operation="create_event",
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
    name="outlook_calendar_create_event",
    function=outlook_calendar_create_event,
    description=(
        "Creates an Outlook event in one selected calendar and sends an invitation to every "
        "attendee. Times are local to time_zone, which defaults to the mailbox time zone. Use "
        "outlook_calendar_search_people to turn a name into an address first."
    ),
    provider="outlook_calendar",
    label="Create Outlook Event",
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
    approval_display_args=partial(write_display_args, CreateEventInput),
    approval_input_model=CreateEventInput,
    presentation=ToolPresentation(
        icon="outlook_calendar",
        running_label="Creating Outlook Event",
        completed_label="Created Outlook Event",
        failed_label="Could Not Create Outlook Event",
        approval_title="Create Outlook Event",
        approve_label="Approve & Send",
        approval_prompt="Invitations are sent to every attendee when you approve.",
        # The card shows Teams Meeting, All Day, and Show As on one line of their own.
        arg_fields=(
            ToolFieldPresentation(
                key="subject", label="Subject", format="text", editable=True, width="full"
            ),
            ToolFieldPresentation(
                key="start", label="Start", format="datetime", editable=True, width="third"
            ),
            ToolFieldPresentation(
                key="end", label="End", format="datetime", editable=True, width="third"
            ),
            ToolFieldPresentation(
                key="time_zone", label="Time Zone", format="text", editable=True, width="third"
            ),
            ToolFieldPresentation(key="attendees", label="Attendees", format="list", editable=True),
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
            ToolFieldPresentation(
                key="calendar",
                label="Calendar",
                format="entity",
                editable=True,
                secondary=True,
                entity_kind="outlook_calendar",
                width="half",
            ),
            ToolFieldPresentation(
                key="is_online_meeting",
                label="Teams Meeting",
                format="boolean",
                editable=True,
                secondary=True,
            ),
            ToolFieldPresentation(
                key="is_all_day", label="All Day", format="boolean", editable=True, secondary=True
            ),
            ToolFieldPresentation(
                key="show_as",
                label="Show As",
                format="text",
                editable=True,
                secondary=True,
                options=("free", "tentative", "busy", "oof", "workingElsewhere"),
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
