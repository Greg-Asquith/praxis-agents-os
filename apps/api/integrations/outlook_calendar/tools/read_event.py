# apps/api/integrations/outlook_calendar/tools/read_event.py

"""Read one Outlook event."""

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
from services.integrations.context.targeted import run_context_targets
from services.integrations.microsoft_graph.time import validate_time_zone
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.get_event import get_event
from ..references import OutlookEventReference
from .schemas import EventOutput
from .utils import (
    OUTLOOK_CALENDAR_BINDING,
    RESULTS_FIELD,
    TIME_ZONE_FIELD,
    TimeZone,
    bounded_output,
    calendar_client,
    can_view_private,
    entry_time_zone,
    event_result,
    model_input,
    outlook_calendar_available,
)


# The Field description keeps the `event` wrapper in the model-facing schema; pydantic-ai
# unwraps a lone model-typed parameter otherwise, and approvals need the wrapper key.
async def outlook_calendar_read_event(
    ctx: RunContext[RuntimeDeps],
    event: Annotated[
        OutlookEventReference,
        Field(description="Scoped Outlook event reference returned by list events."),
    ],
    time_zone: TimeZone = None,
) -> dict:
    if time_zone is not None:
        model_input(lambda: validate_time_zone(time_zone))

    async def operation(entry, references):
        reference = references[0]

        async def execute():
            client = await calendar_client(ctx, entry)
            result = await get_event(
                client,
                calendar_id=entry.external_id,
                event_id=reference.event_id,
                time_zone=entry_time_zone(entry, time_zone),
                can_view_private=can_view_private(entry),
            )
            return IntegrationAuditOutcome(
                event_result(entry, result), external_ref=reference.provider_entity_id
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="outlook_calendar_read_event",
            operation="read_event",
            execute=execute,
        )

    return bounded_output(
        await run_context_targets(
            ctx, binding=OUTLOOK_CALENDAR_BINDING, references=[event], operation=operation
        )
    )


DEFINITION = RuntimeToolDefinition(
    name="outlook_calendar_read_event",
    function=outlook_calendar_read_event,
    description=(
        "Reads an Outlook event using its event reference. Returns the description, up to 100 "
        "attendees with their responses, and the recurrence, with up to 20,000 body characters."
    ),
    provider="outlook_calendar",
    label="Read Outlook event",
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    default_policy=TOOL_POLICY_AUTO,
    takes_ctx=True,
    timeout=60,
    output_model=EventOutput,
    integration_binding=OUTLOOK_CALENDAR_BINDING,
    availability_check=outlook_calendar_available,
    presentation=ToolPresentation(
        icon="outlook_calendar",
        running_label="Reading Outlook event",
        completed_label="Read Outlook event",
        failed_label="Could not read Outlook event",
        arg_fields=(
            ToolFieldPresentation(
                key="event", label="Event", format="entity", entity_kind="outlook_event"
            ),
            TIME_ZONE_FIELD,
        ),
        result_fields=RESULTS_FIELD,
    ),
)
