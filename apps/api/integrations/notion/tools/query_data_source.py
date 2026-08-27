# apps/api/integrations/notion/tools/query_data_source.py

"""Query bounded records from one selected Notion data source."""

from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import RunContext

from integrations.notion.references import (
    NotionDataSourceReference,
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
from services.integrations.context.targeted import run_context_targets
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.query_data_source import query_data_source
from ..operations.utils import MAX_NOTION_PROVIDER_CURSOR_CHARS
from .schemas import NotionDataSourceQueryOutput
from .utils import (
    NOTION_BINDING,
    RESULTS_FIELD,
    bounded_notion_output,
    notion_available,
    notion_client,
)


async def notion_query_data_source(
    ctx: RunContext[RuntimeDeps],
    data_source: Annotated[
        NotionDataSourceReference,
        Field(description="Scoped Notion data-source reference returned by search."),
    ],
    limit: Annotated[int, Field(ge=1, le=50, description="Maximum records to return.")] = 25,
    start_cursor: Annotated[
        str | None,
        Field(
            max_length=MAX_NOTION_PROVIDER_CURSOR_CHARS,
            description="Provider cursor from an earlier result.",
        ),
    ] = None,
) -> dict[str, Any]:
    async def operation(entry: ResolvedContextEntry, references) -> Any:
        reference = references[0]

        async def execute() -> Any:
            client = await notion_client(ctx, entry)
            result = await query_data_source(
                client,
                data_source_id=reference.data_source_id,
                limit=limit,
                start_cursor=start_cursor,
            )
            records = []
            for record in result["records"]:
                page_reference = notion_page_reference(entry, record)
                if page_reference is not None:
                    records.append(
                        {
                            "reference": page_reference,
                            "title": record["title"],
                            "url": record["url"],
                            "last_edited_time": record["last_edited_time"],
                            "properties": record["properties"],
                            "properties_truncated": record["properties_truncated"],
                        }
                    )
            return IntegrationAuditOutcome(
                {**result, "records": records, "count": len(records)},
                external_ref=reference.data_source_id,
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="notion_query_data_source",
            operation="query_data_source",
            execute=execute,
        )

    results = await run_context_targets(
        ctx,
        binding=NOTION_BINDING,
        references=[data_source],
        operation=operation,
    )
    return bounded_notion_output(results)


DEFINITION = RuntimeToolDefinition(
    name="notion_query_data_source",
    function=notion_query_data_source,
    description="Return one bounded page of records from a selected Notion data source.",
    provider="notion",
    label="Query Notion Data Source",
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    default_policy=TOOL_POLICY_AUTO,
    takes_ctx=True,
    timeout=60,
    output_model=NotionDataSourceQueryOutput,
    integration_binding=NOTION_BINDING,
    availability_check=notion_available,
    presentation=ToolPresentation(
        icon="notion",
        running_label="Querying Notion Data Source",
        completed_label="Queried Notion Data Source",
        failed_label="Couldn't Query Notion Data Source",
        arg_fields=(
            ToolFieldPresentation(
                key="data_source",
                label="Data Source",
                format="entity",
                editable=True,
                entity_kind="notion_data_source",
            ),
            ToolFieldPresentation(
                key="limit", label="Maximum Records", format="number", editable=True, secondary=True
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
