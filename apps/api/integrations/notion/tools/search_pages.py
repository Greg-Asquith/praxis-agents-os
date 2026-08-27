# apps/api/integrations/notion/tools/search_pages.py

"""Search Notion page and data-source titles."""

from typing import Annotated, Any, Literal

from pydantic import Field
from pydantic_ai import RunContext

from integrations.notion.references import (
    notion_data_source_reference,
    notion_page_reference,
)
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    TOOL_EGRESS_PROVIDER_QUERY,
    TOOL_POLICY_AUTO,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.fan_out import run_context_fan_out
from services.integrations.context.targeted import run_context_scope
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.search import search
from .schemas import NotionSearchOutput
from .search_cursor import MAX_SCOPED_CURSOR_CHARS, decode_search_cursor, encode_search_cursor
from .utils import (
    NOTION_BINDING,
    RESULTS_FIELD,
    bounded_notion_output,
    notion_available,
    notion_client,
)

COVERAGE_NOTE = (
    "Search matches titles only among pages shared with this connection. "
    "Results can be incomplete or delayed."
)


async def notion_search_pages(
    ctx: RunContext[RuntimeDeps],
    query: Annotated[
        str | None,
        Field(max_length=2_000, description="Optional title text to match."),
    ] = None,
    kind: Annotated[
        Literal["page", "data_source", "all"],
        Field(description="Type of Notion object to return."),
    ] = "all",
    limit: Annotated[int, Field(ge=1, le=50, description="Maximum results per grant.")] = 25,
    start_cursor: Annotated[
        str | None,
        Field(
            max_length=MAX_SCOPED_CURSOR_CHARS,
            description="Scoped continuation cursor from an earlier result.",
        ),
    ] = None,
) -> dict[str, Any]:
    normalized_query = query.strip() if query else None
    continuation = decode_search_cursor(start_cursor) if start_cursor else None
    provider_cursor = continuation[1] if continuation is not None else None

    async def operation(entry: ResolvedContextEntry) -> Any:
        async def execute() -> Any:
            client = await notion_client(ctx, entry)
            result = await search(
                client,
                query=normalized_query,
                kind=kind,
                limit=limit,
                start_cursor=provider_cursor,
            )
            items = []
            for item in result["items"]:
                reference = (
                    notion_page_reference(entry, item)
                    if item["kind"] == "page"
                    else notion_data_source_reference(entry, item)
                )
                if reference is not None:
                    items.append(
                        {
                            "kind": item["kind"],
                            "title": item["title"],
                            "url": item["url"],
                            "last_edited_time": item["last_edited_time"],
                            "reference": reference,
                        }
                    )
            next_cursor = result["next_cursor"]
            return IntegrationAuditOutcome(
                {
                    **result,
                    "items": items,
                    "count": len(items),
                    "next_cursor": (
                        encode_search_cursor(
                            workspace_id=entry.external_id,
                            provider_cursor=next_cursor,
                        )
                        if next_cursor
                        else None
                    ),
                    "coverage_note": COVERAGE_NOTE,
                }
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="notion_search_pages",
            operation="search_pages",
            execute=execute,
        )

    if continuation is None:
        results = await run_context_fan_out(ctx, binding=NOTION_BINDING, operation=operation)
    else:
        results = await run_context_scope(
            ctx,
            binding=NOTION_BINDING,
            provider_scope_id=continuation[0],
            operation=operation,
        )
    return bounded_notion_output(results)


DEFINITION = RuntimeToolDefinition(
    name="notion_search_pages",
    function=notion_search_pages,
    description=(
        "Search titles of Notion pages and data sources shared with every selected grant. "
        "Search can be incomplete or delayed."
    ),
    provider="notion",
    label="Search Notion",
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    default_policy=TOOL_POLICY_AUTO,
    takes_ctx=True,
    timeout=60,
    output_model=NotionSearchOutput,
    integration_binding=NOTION_BINDING,
    availability_check=notion_available,
    presentation=ToolPresentation(
        icon="notion",
        running_label="Searching Notion",
        completed_label="Searched Notion",
        failed_label="Couldn't Search Notion",
        arg_fields=(
            ToolFieldPresentation(key="query", label="Title", editable=True),
            ToolFieldPresentation(
                key="kind",
                label="Type",
                editable=True,
                options=("page", "data_source", "all"),
                secondary=True,
            ),
            ToolFieldPresentation(
                key="limit", label="Maximum Results", format="number", editable=True, secondary=True
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
