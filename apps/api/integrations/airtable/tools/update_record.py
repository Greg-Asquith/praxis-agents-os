# apps/api/integrations/airtable/tools/update_record.py

"""Update Airtable record runtime tool."""

from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_EXTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_POLICY_APPROVAL,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.audit_events import AuditStatus
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.fan_out import run_context_fan_out

from ..operations.update_record import update_record
from .schemas import AirtableOutput
from .utils import (
    AIRTABLE_WRITE_BINDING,
    RESULTS_FIELD,
    airtable_client,
    fan_out_dict,
    record_airtable_operation_audit,
    run_audited_operation,
)


async def airtable_update_record(
    ctx: RunContext[RuntimeDeps],
    table: Annotated[str, Field(description="Table name or id within the selected base.")],
    record_id: Annotated[str, Field(description="Airtable record id to update.")],
    fields: Annotated[dict[str, Any], Field(description="Field values to update.")],
) -> dict[str, Any]:
    normalized_table = table.strip()
    normalized_record_id = record_id.strip()
    if not normalized_table or not normalized_record_id or not fields:
        raise ModelRetry(
            "airtable_update_record requires a table, record_id, and at least one field."
        )

    async def operation(entry: ResolvedContextEntry) -> Any:
        async def execute() -> Any:
            client = await airtable_client(ctx, entry)
            return await update_record(
                client,
                base_id=entry.external_id,
                table=normalized_table,
                record_id=normalized_record_id,
                fields=fields,
            )

        return await run_audited_operation(
            ctx,
            entry,
            tool_name="airtable_update_record",
            operation="update_record",
            execute=execute,
            external_ref_from_result=lambda value: str(value.get("record_id", "")) or None,
        )

    async def audit_write_denied(entry: ResolvedContextEntry) -> None:
        await record_airtable_operation_audit(
            ctx,
            entry,
            tool_name="airtable_update_record",
            operation="update_record",
            status=AuditStatus.FAILURE,
            external_ref=normalized_record_id,
            error_code="write_not_permitted",
        )

    results = await run_context_fan_out(
        ctx.deps,
        binding=AIRTABLE_WRITE_BINDING,
        operation=operation,
        write=True,
        on_write_denied=audit_write_denied,
    )
    return {"results": [fan_out_dict(item) for item in results]}


DEFINITION = RuntimeToolDefinition(
    name="airtable_update_record",
    function=airtable_update_record,
    description="Update one record in every writable Airtable base in context.",
    provider="airtable",
    label="Update Airtable Record",
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    default_policy=TOOL_POLICY_APPROVAL,
    takes_ctx=True,
    timeout=60,
    output_model=AirtableOutput,
    integration_binding=AIRTABLE_WRITE_BINDING,
    presentation=ToolPresentation(
        icon="airtable",
        running_label="Updating Airtable Record",
        completed_label="Updated Airtable Record",
        failed_label="Couldn't Update Airtable Record",
        approval_title="Update Airtable Record",
        approval_prompt="The agent wants to change this record in the selected Airtable bases.",
        approve_label="Approve & Update",
        arg_fields=(
            ToolFieldPresentation(key="table", label="Table", editable=True),
            ToolFieldPresentation(key="record_id", label="Record"),
            ToolFieldPresentation(key="fields", label="Fields", format="keyvalue", editable=True),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
