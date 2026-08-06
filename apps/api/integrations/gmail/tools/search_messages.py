# apps/api/integrations/gmail/tools/search_messages.py

"""Search Gmail runtime tool."""

from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from integrations.gmail.references import GmailMessageReference
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    TOOL_EGRESS_PROVIDER_QUERY,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.agents.runtime.untrusted import untrusted_content_text
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.fan_out import run_context_fan_out

from ..operations.search_messages import search_messages
from .schemas import GmailSearchOutput
from .utils import (
    GMAIL_BINDING,
    RESULTS_FIELD,
    fan_out_dict,
    gmail_available,
    gmail_client,
    run_audited_operation,
)


async def gmail_search_messages(
    ctx: RunContext[RuntimeDeps],
    query: Annotated[str, Field(description="Gmail search query.")],
    limit: Annotated[int, Field(ge=1, le=25, description="Maximum messages to return.")] = 10,
) -> dict[str, Any]:
    normalized_query = query.strip()
    if not normalized_query:
        raise ModelRetry("gmail_search_messages requires a non-empty query.")

    async def operation(entry: ResolvedContextEntry) -> Any:
        async def execute() -> Any:
            client = await gmail_client(ctx, entry)
            result = await search_messages(client, query=normalized_query, limit=limit)
            for message in result["messages"]:
                subject = untrusted_content_text(message.get("subject")) or "(no subject)"
                sender = untrusted_content_text(message.get("sender"))
                date = untrusted_content_text(message.get("date"))
                message["reference"] = GmailMessageReference(
                    integration_resource_id=entry.integration_resource_id,
                    external_id=message["message_id"],
                    label=subject,
                    description=" · ".join(value for value in (sender, date) if value),
                    scope_label=entry.display_name,
                    sender=sender or None,
                    date=date or None,
                )
            return result

        return await run_audited_operation(
            ctx,
            entry,
            tool_name="gmail_search_messages",
            operation="search_messages",
            execute=execute,
        )

    results = await run_context_fan_out(
        ctx.deps,
        binding=GMAIL_BINDING,
        operation=operation,
    )
    return {"results": [fan_out_dict(item) for item in results]}


DEFINITION = RuntimeToolDefinition(
    name="gmail_search_messages",
    function=gmail_search_messages,
    description="Search messages in every compatible Gmail mailbox in the active context.",
    provider="gmail",
    label="Search Gmail",
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    takes_ctx=True,
    timeout=60,
    output_model=GmailSearchOutput,
    integration_binding=GMAIL_BINDING,
    availability_check=gmail_available,
    presentation=ToolPresentation(
        icon="gmail",
        running_label="Searching Gmail for {query}",
        completed_label="Searched Gmail for {query}",
        failed_label="Couldn't Search Gmail",
        arg_fields=(
            ToolFieldPresentation(key="query", label="Search", editable=True),
            ToolFieldPresentation(
                key="limit",
                label="Maximum Messages",
                format="number",
                editable=True,
                secondary=True,
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
