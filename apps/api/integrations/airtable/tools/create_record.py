# apps/api/integrations/airtable/tools/create_record.py

"""Create Airtable record runtime tool."""

from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_EXTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_EXTERNAL_WRITE,
    TOOL_POLICY_APPROVAL,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.audit_events import terminal_applied_operation_detail
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.fan_out import run_context_fan_out
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.create_record import create_record
from .schemas import AirtableOutput
from .utils import (
    AIRTABLE_WRITE_BINDING,
    RESULTS_FIELD,
    airtable_client,
    pending_record_operation_detail,
)


async def airtable_create_record(
    ctx: RunContext[RuntimeDeps],
    table: Annotated[str, Field(description="Table name or id within the selected base.")],
    fields: Annotated[dict[str, Any], Field(description="Field values for the new record.")],
) -> dict[str, Any]:
    normalized_table = table.strip()
    if not normalized_table or not fields:
        raise ModelRetry("airtable_create_record requires a table and at least one field.")

    async def operation(entry: ResolvedContextEntry) -> Any:
        pending_detail = pending_record_operation_detail(
            entry,
            action="create",
            table=normalized_table,
            field_count=len(fields),
        )

        async def execute() -> Any:
            client = await airtable_client(ctx, entry)
            result = await create_record(
                client,
                base_id=entry.external_id,
                table=normalized_table,
                fields=fields,
            )
            external_ref = str(result.get("record_id", "")) or None
            return IntegrationAuditOutcome(
                result,
                external_ref=external_ref,
                operation_detail=terminal_applied_operation_detail(
                    pending_detail,
                    external_ref=external_ref,
                ),
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="airtable_create_record",
            operation="create_record",
            execute=execute,
            pending_operation_detail=pending_detail,
        )

    results = await run_context_fan_out(
        ctx,
        binding=AIRTABLE_WRITE_BINDING,
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


DEFINITION = RuntimeToolDefinition(
    name="airtable_create_record",
    function=airtable_create_record,
    description="Create one record in a table in every writable Airtable base in context.",
    provider="airtable",
    label="Create Airtable Record",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    takes_ctx=True,
    timeout=60,
    output_model=AirtableOutput,
    integration_binding=AIRTABLE_WRITE_BINDING,
    presentation=ToolPresentation(
        icon="airtable",
        running_label="Creating Airtable Record",
        completed_label="Created Airtable Record",
        failed_label="Couldn't Create Airtable Record",
        approval_title="Create Airtable Record",
        approval_prompt="The agent wants to add this record to the selected Airtable bases.",
        approve_label="Approve & Create",
        arg_fields=(
            ToolFieldPresentation(key="table", label="Table", editable=True),
            ToolFieldPresentation(key="fields", label="Fields", format="keyvalue", editable=True),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
