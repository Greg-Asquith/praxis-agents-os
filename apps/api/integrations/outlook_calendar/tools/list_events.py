# apps/api/integrations/outlook_calendar/tools/list_events.py

"""List Outlook events in a time window."""

from typing import Annotated

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
from services.integrations.context.fan_out import run_context_fan_out
from services.integrations.microsoft_graph.time import bounded_window, validate_time_zone
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.list_calendar_view import list_calendar_view
from ..settings import outlook_calendar_settings
from .schemas import EventsOutput
from .utils import (
    OUTLOOK_CALENDAR_BINDING,
    RESULTS_FIELD,
    TIME_ZONE_FIELD,
    LocalDateTime,
    TimeZone,
    bounded_output,
    calendar_client,
    can_view_private,
    entry_time_zone,
    event_result,
    model_input,
    outlook_calendar_available,
)


async def outlook_calendar_list_events(
    ctx: RunContext[RuntimeDeps],
    start: LocalDateTime,
    end: LocalDateTime,
    time_zone: TimeZone = None,
    limit: Annotated[int, Field(ge=1, le=100)] = 25,
) -> dict:
    max_days = outlook_calendar_settings.OUTLOOK_CALENDAR_MAX_RANGE_DAYS
    start_at, end_at = model_input(lambda: bounded_window(start, end, max_days=max_days))
    if time_zone is not None:
        model_input(lambda: validate_time_zone(time_zone))

    async def operation(entry):
        async def execute():
            zone = entry_time_zone(entry, time_zone)
            client = await calendar_client(ctx, entry)
            events = await list_calendar_view(
                client,
                calendar_id=entry.external_id,
                start=start_at,
                end=end_at,
                time_zone=zone,
                limit=limit,
                can_view_private=can_view_private(entry),
            )
            return IntegrationAuditOutcome(
                {
                    "events": [event_result(entry, event) for event in events],
                    "count": len(events),
                    "time_zone": zone,
                }
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="outlook_calendar_list_events",
            operation="list_events",
            execute=execute,
        )

    return bounded_output(
        await run_context_fan_out(ctx, binding=OUTLOOK_CALENDAR_BINDING, operation=operation)
    )


DEFINITION = RuntimeToolDefinition(
    name="outlook_calendar_list_events",
    function=outlook_calendar_list_events,
    description=(
        "Lists events that overlap a time window in each selected Outlook calendar, including "
        "each occurrence of a recurring meeting. Times are local to time_zone, which defaults "
        "to the mailbox time zone. Returns up to 100 events per calendar."
    ),
    provider="outlook_calendar",
    label="List Outlook events",
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    default_policy=TOOL_POLICY_AUTO,
    takes_ctx=True,
    timeout=60,
    output_model=EventsOutput,
    integration_binding=OUTLOOK_CALENDAR_BINDING,
    availability_check=outlook_calendar_available,
    presentation=ToolPresentation(
        icon="outlook_calendar",
        running_label="Listing Outlook events",
        completed_label="List Outlook events",
        failed_label="Could not list Outlook events",
        arg_fields=(
            ToolFieldPresentation(key="start", label="From", format="datetime", editable=True),
            ToolFieldPresentation(key="end", label="To", format="datetime", editable=True),
            TIME_ZONE_FIELD,
            ToolFieldPresentation(
                key="limit",
                label="Maximum Results",
                format="number",
                editable=True,
                secondary=True,
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
