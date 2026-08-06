# apps/api/integrations/airtable/tools/get_record.py

"""Get Airtable record runtime tool."""

from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from integrations.airtable.references import AirtableRecordReference, airtable_tables_match
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    TOOL_EGRESS_PROVIDER_QUERY,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.targeted import run_context_targets

from ..operations.get_record import get_record
from .schemas import AirtableOutput
from .utils import (
    AIRTABLE_BINDING,
    RESULTS_FIELD,
    airtable_client,
    fan_out_dict,
    run_audited_operation,
)


async def airtable_get_record(
    ctx: RunContext[RuntimeDeps],
    table: Annotated[str, Field(description="Table name or id within the selected base.")],
    record_id: Annotated[AirtableRecordReference, Field(description="Scoped Airtable record.")],
) -> dict[str, Any]:
    normalized_table = table.strip()
    if not normalized_table:
        raise ModelRetry("airtable_get_record requires a table and record_id.")
    if not airtable_tables_match(record_id.table, normalized_table):
        raise ModelRetry(
            "The Airtable table changed after this record was selected. "
            "Choose a record from the current table."
        )

    async def operation(entry: ResolvedContextEntry, references) -> Any:
        reference = references[0]

        async def execute() -> Any:
            client = await airtable_client(ctx, entry)
            return await get_record(
                client,
                base_id=entry.external_id,
                table=record_id.table.strip(),
                record_id=reference.external_id,
            )

        return await run_audited_operation(
            ctx,
            entry,
            tool_name="airtable_get_record",
            operation="get_record",
            execute=execute,
            external_ref=reference.external_id,
        )

    results = await run_context_targets(
        ctx.deps,
        binding=AIRTABLE_BINDING,
        references=[record_id],
        operation=operation,
    )
    return {"results": [fan_out_dict(item) for item in results]}


DEFINITION = RuntimeToolDefinition(
    name="airtable_get_record",
    function=airtable_get_record,
    description="Get one selected record from its Airtable base and table.",
    provider="airtable",
    label="Get Airtable Record",
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    takes_ctx=True,
    timeout=60,
    output_model=AirtableOutput,
    integration_binding=AIRTABLE_BINDING,
    presentation=ToolPresentation(
        icon="airtable",
        running_label="Getting Airtable Record",
        completed_label="Got Airtable Record",
        failed_label="Couldn't Get Airtable Record",
        arg_fields=(
            ToolFieldPresentation(key="table", label="Table", editable=True),
            ToolFieldPresentation(
                key="record_id",
                label="Record",
                format="entity",
                editable=True,
                entity_kind="airtable_record",
                depends_on=("table",),
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
