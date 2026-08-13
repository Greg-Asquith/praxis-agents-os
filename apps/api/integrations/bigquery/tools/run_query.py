# apps/api/integrations/bigquery/tools/run_query.py

from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from core.exceptions.integration import IntegrationTimeoutError, IntegrationValidationError
from core.settings import settings
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    TOOL_EGRESS_PROVIDER_QUERY,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
)

from ..operations.run_query import AllowedDataset, run_query
from ..settings import bigquery_settings
from .schemas import BigQueryRunQueryOutput
from .utils import (
    BIGQUERY_BINDING,
    active_bigquery_entries,
    bigquery_query_client,
    dataset_coordinates,
    dataset_location,
    query_labels,
    run_multi_context_query_with_audit,
)


async def bigquery_run_query(
    ctx: RunContext[RuntimeDeps],
    query: Annotated[
        str,
        Field(
            description=(
                "One GoogleSQL SELECT statement using fully qualified "
                "backticked `project.dataset.table` names."
            )
        ),
    ],
) -> dict[str, Any]:
    """Run exactly one bounded GoogleSQL SELECT within the active dataset boundary."""
    normalized = query.strip()
    if not normalized:
        raise ModelRetry("bigquery_run_query requires a GoogleSQL SELECT query.")
    entries = active_bigquery_entries(ctx)
    connection_ids = {entry.connection_id for entry in entries}
    if len(connection_ids) != 1:
        raise ModelRetry(
            "The active context contains BigQuery datasets from multiple connections. "
            "Ask the user to narrow it to one BigQuery connection."
        )
    allowed_datasets: dict[tuple[str, str], AllowedDataset] = {}
    for entry in entries:
        project_id, dataset_id = dataset_coordinates(entry)
        allowed_datasets[(project_id, dataset_id)] = AllowedDataset(
            project_id=project_id,
            dataset_id=dataset_id,
            location=dataset_location(entry),
        )

    async def execute():
        client, billing_project_id = await bigquery_query_client(ctx, entries[0])
        try:
            return await run_query(
                client,
                query=normalized,
                billing_project_id=billing_project_id,
                allowed_datasets=allowed_datasets,
                labels=query_labels(ctx),
                request_id=str(ctx.deps.run.id),
                max_bytes_billed=bigquery_settings.BIGQUERY_MAX_BYTES_BILLED,
                max_rows=settings.INTEGRATION_REPORT_MAX_ROWS,
                max_result_chars=bigquery_settings.BIGQUERY_MAX_RESULT_CHARS,
                timeout_seconds=bigquery_settings.BIGQUERY_QUERY_TIMEOUT_SECONDS,
            )
        except (IntegrationTimeoutError, IntegrationValidationError) as exc:
            provider_message = str(exc).partition(" | ")[0]
            raise ModelRetry(provider_message) from exc

    return await run_multi_context_query_with_audit(
        ctx,
        entries,
        tool_name="bigquery_run_query",
        operation="run_query",
        execute=execute,
    )


DEFINITION = RuntimeToolDefinition(
    name="bigquery_run_query",
    function=bigquery_run_query,
    description=(
        "Run exactly one bounded GoogleSQL SELECT query. Active BigQuery datasets define which "
        "tables that query may reference; the query is not repeated for each dataset. "
        "Use fully qualified backticked `project.dataset.table` names."
    ),
    provider="bigquery",
    label="Run BigQuery Query",
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    takes_ctx=True,
    timeout=bigquery_settings.BIGQUERY_QUERY_TIMEOUT_SECONDS + 15,
    output_model=BigQueryRunQueryOutput,
    integration_binding=BIGQUERY_BINDING,
    presentation=ToolPresentation(
        icon="bigquery",
        running_label="Running BigQuery Query",
        completed_label="Ran BigQuery Query",
        failed_label="Couldn't Run BigQuery Query",
        arg_fields=(
            ToolFieldPresentation(
                key="query",
                label="GoogleSQL Query",
                format="multiline",
                editable=True,
            ),
        ),
        result_fields=(
            ToolFieldPresentation(key="rows", label="Rows", format="list"),
            ToolFieldPresentation(key="total_rows", label="Total Rows"),
            ToolFieldPresentation(
                key="total_bytes_processed",
                label="Bytes Processed",
                format="bytes",
            ),
            ToolFieldPresentation(key="cache_hit", label="Cache Hit", format="boolean"),
        ),
    ),
)
