# apps/api/integrations/outlook_mail/tools/search_messages.py

"""Search Outlook messages."""

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

from ..operations.search_messages import search_messages
from .schemas import SearchOutput
from .utils import (
    OUTLOOK_MAIL_BINDING,
    RESULTS_FIELD,
    bounded_output,
    mailbox_client,
    mailbox_time_zone,
    message_result,
    outlook_mail_available,
)


async def outlook_mail_search_messages(
    ctx: RunContext[RuntimeDeps],
    query: Annotated[str | None, Field(max_length=500)] = None,
    folder: Annotated[str, Field(min_length=1, max_length=500)] = "inbox",
    unread_only: bool = False,
    limit: Annotated[int, Field(ge=1, le=25)] = 10,
) -> dict:
    async def operation(entry):
        async def execute():
            client = await mailbox_client(ctx, entry)
            messages = await search_messages(
                client, query=query, folder=folder, unread_only=unread_only, limit=limit
            )
            result = {
                "messages": [message_result(entry, item) for item in messages],
                "count": len(messages),
            }
            return IntegrationAuditOutcome(
                {**result, "mailbox_time_zone": mailbox_time_zone(entry)}
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="outlook_mail_search_messages",
            operation="search_messages",
            execute=execute,
        )

    return bounded_output(
        await run_context_fan_out(ctx, binding=OUTLOOK_MAIL_BINDING, operation=operation)
    )


DEFINITION = RuntimeToolDefinition(
    name="outlook_mail_search_messages",
    function=outlook_mail_search_messages,
    description="Search Outlook messages in the selected mailboxes with bounded results.",
    provider="outlook_mail",
    label="Search Outlook messages",
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    default_policy=TOOL_POLICY_AUTO,
    takes_ctx=True,
    timeout=60,
    output_model=SearchOutput,
    integration_binding=OUTLOOK_MAIL_BINDING,
    availability_check=outlook_mail_available,
    presentation=ToolPresentation(
        icon="outlook_mail",
        running_label="Searching Outlook messages",
        completed_label="Search Outlook messages",
        failed_label="Could not search outlook messages",
        arg_fields=(
            ToolFieldPresentation(key="query", label="Query", format="text", editable=True),
            ToolFieldPresentation(
                key="folder", label="Folder", format="text", editable=True, secondary=True
            ),
            ToolFieldPresentation(
                key="unread_only",
                label="Unread only",
                format="boolean",
                editable=True,
                secondary=True,
            ),
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
