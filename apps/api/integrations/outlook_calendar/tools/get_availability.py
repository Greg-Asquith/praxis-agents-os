# apps/api/integrations/outlook_calendar/tools/get_availability.py

"""Check when people are free or busy."""

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
from services.integrations.microsoft_graph.time import bounded_window, validate_time_zone
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.get_schedule import get_schedule
from ..operations.utils import validate_addresses
from .schemas import AvailabilityOutput
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

MAX_ADDRESSES = 20
MAX_DAYS = 31


async def outlook_calendar_get_availability(
    ctx: RunContext[RuntimeDeps],
    addresses: Annotated[list[Annotated[str, Field(max_length=320)]], Field(max_length=50)],
    start: LocalDateTime,
    end: LocalDateTime,
    time_zone: TimeZone = None,
    interval_minutes: Annotated[int, Field(ge=5, le=1440)] = 30,
) -> dict:
    people = model_input(
        lambda: validate_addresses(addresses, limit=MAX_ADDRESSES, field="addresses")
    )
    start_at, end_at = model_input(lambda: bounded_window(start, end, max_days=MAX_DAYS))
    if time_zone is not None:
        model_input(lambda: validate_time_zone(time_zone))

    async def operation(entry):
        async def execute():
            zone = entry_time_zone(entry, time_zone)
            client = await calendar_client(ctx, entry)
            schedules = await get_schedule(
                client,
                addresses=people,
                start=start_at,
                end=end_at,
                time_zone=zone,
                interval_minutes=interval_minutes,
            )
            return IntegrationAuditOutcome(
                {"schedules": schedules, "interval_minutes": interval_minutes, "time_zone": zone}
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="outlook_calendar_get_availability",
            operation="get_availability",
            execute=execute,
        )

    return bounded_output(await run_once_per_connection(ctx, operation))


DEFINITION = RuntimeToolDefinition(
    name="outlook_calendar_get_availability",
    function=outlook_calendar_get_availability,
    description=(
        "Checks when up to 20 people are free or busy over a window of up to 31 days. Returns "
        "each person's busy periods and working hours without event subjects, and an "
        "availability_view string with one digit per interval: 0 free, 1 tentative, 2 busy, "
        "3 out of office, 4 working elsewhere."
    ),
    provider="outlook_calendar",
    label="Check Outlook availability",
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    default_policy=TOOL_POLICY_AUTO,
    takes_ctx=True,
    timeout=60,
    output_model=AvailabilityOutput,
    integration_binding=OUTLOOK_CALENDAR_BINDING,
    availability_check=outlook_calendar_available,
    presentation=ToolPresentation(
        icon="outlook_calendar",
        running_label="Checking availability",
        completed_label="Check Outlook availability",
        failed_label="Could not check availability",
        arg_fields=(
            ToolFieldPresentation(key="addresses", label="People", format="list", editable=True),
            ToolFieldPresentation(key="start", label="From", format="datetime", editable=True),
            ToolFieldPresentation(key="end", label="To", format="datetime", editable=True),
            TIME_ZONE_FIELD,
            ToolFieldPresentation(
                key="interval_minutes",
                label="Interval Minutes",
                format="number",
                editable=True,
                secondary=True,
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
