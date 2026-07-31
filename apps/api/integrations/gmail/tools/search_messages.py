# apps/api/integrations/gmail/tools/search_messages.py

"""Search Gmail runtime tool."""

from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
)
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
            return await search_messages(client, query=normalized_query, limit=limit)

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
