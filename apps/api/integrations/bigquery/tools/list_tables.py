# apps/api/integrations/bigquery/tools/list_tables.py

"""List cached tables for active BigQuery datasets."""

from typing import Any

from pydantic_ai import RunContext

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.list_tables import list_tables
from .schemas import BigQueryListTablesOutput
from .utils import BIGQUERY_BINDING, active_bigquery_entries


async def bigquery_list_tables(ctx: RunContext[RuntimeDeps]) -> dict[str, Any]:
    """List cached tables for every active BigQuery dataset in one tool call."""
    entries = active_bigquery_entries(ctx)
    datasets: list[dict[str, Any]] = []
    for entry in entries:

        async def execute(target=entry):
            return IntegrationAuditOutcome(
                await list_tables(
                    ctx.deps.db,
                    integration_resource_id=target.integration_resource_id,
                )
            )

        rows = await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="bigquery_list_tables",
            operation="list_cached_tables",
            execute=execute,
        )
        datasets.append(
            {
                "dataset": entry.external_id,
                "display_name": entry.display_name,
                "tables": [
                    {
                        "table": row.table_external_id,
                        "table_type": row.table_type,
                        "description": row.description,
                        "row_count": row.row_count,
                        "last_synced_at": row.last_synced_at,
                    }
                    for row in rows
                ],
            }
        )
    return {"datasets": datasets}


DEFINITION = RuntimeToolDefinition(
    name="bigquery_list_tables",
    function=bigquery_list_tables,
    description=(
        "List cached tables for every active BigQuery dataset in one discovery call. "
        "Use GoogleSQL with fully qualified `project.dataset.table` names."
    ),
    provider="bigquery",
    label="List BigQuery Tables",
    effect=TOOL_EFFECT_READ,
    takes_ctx=True,
    output_model=BigQueryListTablesOutput,
    integration_binding=BIGQUERY_BINDING,
    presentation=ToolPresentation(
        icon="bigquery",
        running_label="Listing BigQuery Tables",
        completed_label="Listed BigQuery Tables",
        failed_label="Couldn't List BigQuery Tables",
        result_fields=(ToolFieldPresentation(key="datasets", label="Datasets", format="list"),),
    ),
)
