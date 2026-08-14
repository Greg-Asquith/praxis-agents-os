# apps/api/integrations/bigquery/tools/get_table_schema.py

"""Read a cached schema for one active-context BigQuery table."""

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
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.get_table_schema import get_table_schema
from .schemas import BigQueryTableSchemaOutput
from .utils import (
    BIGQUERY_BINDING,
    active_bigquery_entries,
)


async def bigquery_get_table_schema(
    ctx: RunContext[RuntimeDeps],
    table: Annotated[
        str,
        Field(
            description=(
                "Table name or fully qualified `project.dataset.table` name "
                "from bigquery_list_tables."
            )
        ),
    ],
) -> dict[str, Any]:
    """Read cached schema metadata without making a provider request."""
    normalized = table.strip().strip("`")
    if not normalized:
        raise ModelRetry("bigquery_get_table_schema requires a table name.")
    entries = active_bigquery_entries(ctx)
    matches = _matching_entries(entries, normalized)
    if not matches:
        raise ModelRetry(
            f"No active BigQuery dataset contains {normalized!r}. "
            "Call bigquery_list_tables or ask the user to change the active context."
        )

    table_id = normalized.rsplit(".", maxsplit=1)[-1]
    found: list[tuple[Any, Any]] = []
    for entry in matches:

        async def execute(target=entry):
            return IntegrationAuditOutcome(
                await get_table_schema(
                    ctx.deps.db,
                    integration_resource_id=target.integration_resource_id,
                    table_external_id=table_id,
                )
            )

        row = await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="bigquery_get_table_schema",
            operation="get_cached_table_schema",
            execute=execute,
        )
        if row is not None:
            found.append((entry, row))
    if not found:
        raise ModelRetry(
            f"Cached schema metadata for {normalized!r} is unavailable. "
            "Call bigquery_list_tables or ask the user to refresh the connection."
        )
    if len(found) > 1:
        qualified = ", ".join(
            f"`{entry.external_id}.{row.table_external_id}`" for entry, row in found
        )
        raise ModelRetry(f"Table name {table_id!r} is ambiguous. Use one of: {qualified}.")

    entry, row = found[0]
    fully_qualified = f"{entry.external_id}.{row.table_external_id}"
    partitioning = dict(row.partitioning or {})
    return {
        "table": f"`{fully_qualified}`",
        "table_type": row.table_type,
        "description": row.description,
        "fields": [
            {
                "name": str(field.get("name", "")),
                "type": str(field.get("type", "")),
                "mode": str(field.get("mode", "")),
                "description": str(field.get("description", "")).strip() or None,
            }
            for field in row.schema_fields or []
            if isinstance(field, dict)
        ],
        "partitioning": partitioning,
        "clustering_fields": list(row.clustering_fields or []),
        "row_count": row.row_count,
        "size_bytes": row.size_bytes,
        "last_synced_at": row.last_synced_at,
        "requires_partition_filter": bool(partitioning.get("require_partition_filter")),
    }


def _matching_entries(entries, table: str):
    parts = table.split(".")
    if len(parts) == 1:
        return entries
    if len(parts) != 3:
        raise ModelRetry("Use a table name or a fully qualified `project.dataset.table` name.")
    dataset = ".".join(parts[:2])
    return tuple(entry for entry in entries if entry.external_id == dataset)


DEFINITION = RuntimeToolDefinition(
    name="bigquery_get_table_schema",
    function=bigquery_get_table_schema,
    description=(
        "Read cached fields and partitioning for one table in the active BigQuery datasets. "
        "This targets one table and does not repeat across every dataset. "
        "Use GoogleSQL with the returned fully qualified backticked table name."
    ),
    provider="bigquery",
    label="Get BigQuery Table Schema",
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    takes_ctx=True,
    output_model=BigQueryTableSchemaOutput,
    integration_binding=BIGQUERY_BINDING,
    presentation=ToolPresentation(
        icon="bigquery",
        running_label="Reading BigQuery Table Schema",
        completed_label="Read BigQuery Table Schema",
        failed_label="Couldn't Read BigQuery Table Schema",
        arg_fields=(ToolFieldPresentation(key="table", label="Table"),),
        result_fields=(
            ToolFieldPresentation(key="table", label="Table"),
            ToolFieldPresentation(key="fields", label="Fields", format="list"),
            ToolFieldPresentation(
                key="requires_partition_filter",
                label="Requires Partition Filter",
                format="boolean",
            ),
        ),
    ),
)
