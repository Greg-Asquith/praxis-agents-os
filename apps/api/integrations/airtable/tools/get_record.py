# apps/api/integrations/airtable/tools/get_record.py

"""Get Airtable record runtime tool."""

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
    record_id: Annotated[str, Field(description="Airtable record id.")],
) -> dict[str, Any]:
    normalized_table = table.strip()
    normalized_record_id = record_id.strip()
    if not normalized_table or not normalized_record_id:
        raise ModelRetry("airtable_get_record requires a table and record_id.")

    async def operation(entry: ResolvedContextEntry) -> Any:
        async def execute() -> Any:
            client = await airtable_client(ctx, entry)
            return await get_record(
                client,
                base_id=entry.external_id,
                table=normalized_table,
                record_id=normalized_record_id,
            )

        return await run_audited_operation(
            ctx,
            entry,
            tool_name="airtable_get_record",
            operation="get_record",
            execute=execute,
            external_ref=normalized_record_id,
        )

    results = await run_context_fan_out(ctx.deps, binding=AIRTABLE_BINDING, operation=operation)
    return {"results": [fan_out_dict(item) for item in results]}


DEFINITION = RuntimeToolDefinition(
    name="airtable_get_record",
    function=airtable_get_record,
    description="Get one record by id from a table in each selected Airtable base.",
    provider="airtable",
    label="Get Airtable Record",
    effect=TOOL_EFFECT_READ,
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
            ToolFieldPresentation(key="table", label="Table"),
            ToolFieldPresentation(key="record_id", label="Record"),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
