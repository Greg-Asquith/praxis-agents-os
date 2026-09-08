# apps/api/integrations/outlook_mail/tools/search_people.py

"""Search Outlook people."""

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
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.search_people import search_people
from .schemas import PeopleOutput
from .utils import (
    OUTLOOK_MAIL_BINDING,
    RESULTS_FIELD,
    bounded_output,
    mailbox_client,
    mailbox_time_zone,
    outlook_mail_available,
)


async def outlook_mail_search_people(
    ctx: RunContext[RuntimeDeps],
    query: Annotated[str, Field(min_length=1, max_length=100)],
    limit: Annotated[int, Field(ge=1, le=25)] = 10,
) -> dict:
    async def operation(entry):
        async def execute():
            client = await mailbox_client(ctx, entry)
            people = await search_people(client, query=query, limit=limit)
            result = {"people": people, "count": len(people)}
            return IntegrationAuditOutcome(
                {**result, "mailbox_time_zone": mailbox_time_zone(entry)}
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="outlook_mail_search_people",
            operation="search_people",
            execute=execute,
        )

    return bounded_output(
        await run_context_fan_out(ctx, binding=OUTLOOK_MAIL_BINDING, operation=operation)
    )


DEFINITION = RuntimeToolDefinition(
    name="outlook_mail_search_people",
    function=outlook_mail_search_people,
    description=(
        "Finds people by name in the selected Outlook mailboxes. Returns up to 25 people per "
        "mailbox, including email addresses, job titles, and departments."
    ),
    provider="outlook_mail",
    label="Search Outlook people",
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    default_policy=TOOL_POLICY_AUTO,
    takes_ctx=True,
    timeout=60,
    output_model=PeopleOutput,
    integration_binding=OUTLOOK_MAIL_BINDING,
    availability_check=outlook_mail_available,
    presentation=ToolPresentation(
        icon="outlook_mail",
        running_label="Searching Outlook people",
        completed_label="Search Outlook people",
        failed_label="Could not search outlook people",
        arg_fields=(
            ToolFieldPresentation(key="query", label="Name", format="text", editable=True),
            ToolFieldPresentation(
                key="limit",
                label="Maximum results",
                format="number",
                editable=True,
                secondary=True,
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
