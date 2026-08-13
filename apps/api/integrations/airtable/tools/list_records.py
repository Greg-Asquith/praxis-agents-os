# apps/api/integrations/airtable/tools/list_records.py

"""List Airtable records runtime tool."""

from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from integrations.airtable.references import airtable_record_reference
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    TOOL_EGRESS_PROVIDER_QUERY,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.fan_out import run_context_fan_out
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.list_records import MAX_RECORDS, list_records
from .schemas import AirtableOutput
from .utils import (
    AIRTABLE_BINDING,
    RESULTS_FIELD,
    airtable_client,
)


async def airtable_list_records(
    ctx: RunContext[RuntimeDeps],
    table: Annotated[str, Field(description="Table name or id within the selected base.")],
    view: Annotated[str | None, Field(description="Optional view name or id.")] = None,
    filter_by_formula: Annotated[
        str | None,
        Field(description="Optional Airtable filter formula."),
    ] = None,
    max_records: Annotated[int, Field(ge=1, le=MAX_RECORDS)] = MAX_RECORDS,
) -> dict[str, Any]:
    normalized_table = table.strip()
    if not normalized_table:
        raise ModelRetry("airtable_list_records requires a table name or id.")

    async def operation(entry: ResolvedContextEntry) -> Any:
        async def execute() -> Any:
            client = await airtable_client(ctx, entry)
            result = await list_records(
                client,
                base_id=entry.external_id,
                table=normalized_table,
                view=view.strip() if view and view.strip() else None,
                filter_by_formula=(
                    filter_by_formula.strip()
                    if filter_by_formula and filter_by_formula.strip()
                    else None
                ),
                max_records=max_records,
            )
            for record in result["records"]:
                reference = airtable_record_reference(entry, normalized_table, record)
                if reference is not None:
                    record["reference"] = reference
            return IntegrationAuditOutcome(result)

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="airtable_list_records",
            operation="list_records",
            execute=execute,
        )

    results = await run_context_fan_out(ctx, binding=AIRTABLE_BINDING, operation=operation)
    return {"results": serialize_fan_out_results(results)}


DEFINITION = RuntimeToolDefinition(
    name="airtable_list_records",
    function=airtable_list_records,
    description="List up to 100 records from a table in each selected Airtable base.",
    provider="airtable",
    label="List Airtable Records",
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    takes_ctx=True,
    timeout=60,
    output_model=AirtableOutput,
    integration_binding=AIRTABLE_BINDING,
    presentation=ToolPresentation(
        icon="airtable",
        running_label="Listing Airtable Records",
        completed_label="Listed Airtable Records",
        failed_label="Couldn't List Airtable Records",
        arg_fields=(
            ToolFieldPresentation(key="table", label="Table", editable=True),
            ToolFieldPresentation(key="view", label="View", editable=True, secondary=True),
            ToolFieldPresentation(
                key="filter_by_formula",
                label="Filter Formula",
                editable=True,
                secondary=True,
            ),
            ToolFieldPresentation(
                key="max_records",
                label="Maximum Records",
                format="number",
                editable=True,
                secondary=True,
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
