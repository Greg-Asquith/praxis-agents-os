# apps/api/integrations/outlook_calendar/tools/find_meeting_times.py

"""Suggest meeting times for a set of attendees."""

from typing import Annotated, Literal

from pydantic import Field
from pydantic_ai import RunContext

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    TOOL_EGRESS_PROVIDER_QUERY,
    TOOL_POLICY_AUTO,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.integrations.microsoft_graph.time import bounded_window, validate_time_zone
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.find_meeting_times import find_meeting_times
from ..operations.utils import validate_addresses
from .schemas import MeetingTimesOutput
from .utils import (
    OUTLOOK_CALENDAR_BINDING,
    RESULTS_FIELD,
    TIME_ZONE_FIELD,
    LocalDateTime,
    TimeZone,
    bounded_output,
    calendar_client,
    entry_time_zone,
    model_input,
    outlook_calendar_available,
    run_once_per_connection,
)

MAX_ATTENDEES = 20
MAX_DAYS = 14


async def outlook_calendar_find_meeting_times(
    ctx: RunContext[RuntimeDeps],
    attendees: Annotated[list[Annotated[str, Field(max_length=320)]], Field(max_length=50)],
    start: LocalDateTime,
    end: LocalDateTime,
    duration_minutes: Annotated[int, Field(ge=5, le=480)] = 30,
    time_zone: TimeZone = None,
    max_candidates: Annotated[int, Field(ge=1, le=10)] = 5,
    activity_domain: Literal["work", "personal"] = "work",
) -> dict:
    people = model_input(
        lambda: validate_addresses(attendees, limit=MAX_ATTENDEES, field="attendees")
    )
    start_at, end_at = model_input(lambda: bounded_window(start, end, max_days=MAX_DAYS))
    if time_zone is not None:
        model_input(lambda: validate_time_zone(time_zone))

    async def operation(entry):
        async def execute():
            zone = entry_time_zone(entry, time_zone)
            client = await calendar_client(ctx, entry)
            result = await find_meeting_times(
                client,
                attendees=people,
                start=start_at,
                end=end_at,
                time_zone=zone,
                duration_minutes=duration_minutes,
                max_candidates=max_candidates,
                activity_domain=activity_domain,
            )
            return IntegrationAuditOutcome({**result, "time_zone": zone})

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="outlook_calendar_find_meeting_times",
            operation="find_meeting_times",
            execute=execute,
        )

    return bounded_output(await run_once_per_connection(ctx, operation))


DEFINITION = RuntimeToolDefinition(
    name="outlook_calendar_find_meeting_times",
    function=outlook_calendar_find_meeting_times,
    description=(
        "Suggests up to 10 meeting times when you and up to 20 attendees are free, within a "
        "window of up to 14 days. Use work for working hours or personal for any time. When "
        "there are no suggestions, empty_suggestions_reason says why."
    ),
    provider="outlook_calendar",
    label="Find Outlook meeting times",
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    default_policy=TOOL_POLICY_AUTO,
    takes_ctx=True,
    timeout=60,
    output_model=MeetingTimesOutput,
    integration_binding=OUTLOOK_CALENDAR_BINDING,
    availability_check=outlook_calendar_available,
    presentation=ToolPresentation(
        icon="outlook_calendar",
        running_label="Finding meeting times",
        completed_label="Find Outlook meeting times",
        failed_label="Could not find meeting times",
        arg_fields=(
            ToolFieldPresentation(key="attendees", label="Attendees", format="list", editable=True),
            ToolFieldPresentation(key="start", label="From", format="datetime", editable=True),
            ToolFieldPresentation(key="end", label="To", format="datetime", editable=True),
            ToolFieldPresentation(
                key="duration_minutes", label="Duration Minutes", format="number", editable=True
            ),
            TIME_ZONE_FIELD,
            ToolFieldPresentation(
                key="max_candidates",
                label="Maximum Suggestions",
                format="number",
                editable=True,
                secondary=True,
            ),
            ToolFieldPresentation(
                key="activity_domain",
                label="Hours",
                format="text",
                editable=True,
                secondary=True,
                options=("work", "personal"),
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
