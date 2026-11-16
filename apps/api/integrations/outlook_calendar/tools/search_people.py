# apps/api/integrations/outlook_calendar/tools/search_people.py

"""Search people to invite."""

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
from services.integrations.microsoft_graph import search_people
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from .schemas import PeopleOutput
from .utils import (
    OUTLOOK_CALENDAR_BINDING,
    RESULTS_FIELD,
    bounded_output,
    calendar_client,
    outlook_calendar_available,
    run_once_per_connection,
)


async def outlook_calendar_search_people(
    ctx: RunContext[RuntimeDeps],
    query: Annotated[str, Field(min_length=1, max_length=100)],
    limit: Annotated[int, Field(ge=1, le=25)] = 10,
) -> dict:
    async def operation(entry):
        async def execute():
            client = await calendar_client(ctx, entry)
            people = await search_people(client, query=query, limit=limit)
            return IntegrationAuditOutcome({"people": people, "count": len(people)})

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="outlook_calendar_search_people",
            operation="search_people",
            execute=execute,
        )

    return bounded_output(await run_once_per_connection(ctx, operation))


DEFINITION = RuntimeToolDefinition(
    name="outlook_calendar_search_people",
    function=outlook_calendar_search_people,
    description=(
        "Finds people by name so you can invite them or check their availability. Returns up "
        "to 25 people with email addresses, job titles, and departments."
    ),
    provider="outlook_calendar",
    label="Search Outlook people",
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    default_policy=TOOL_POLICY_AUTO,
    takes_ctx=True,
    timeout=60,
    output_model=PeopleOutput,
    integration_binding=OUTLOOK_CALENDAR_BINDING,
    availability_check=outlook_calendar_available,
    presentation=ToolPresentation(
        icon="outlook_calendar",
        running_label="Searching people",
        completed_label="Search Outlook people",
        failed_label="Could not search people",
        arg_fields=(
            ToolFieldPresentation(key="query", label="Name", format="text", editable=True),
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
