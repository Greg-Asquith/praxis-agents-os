# apps/api/integrations/airtable/tools/update_record.py

"""Update Airtable record runtime tool."""

from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from integrations.airtable.references import AirtableRecordReference, airtable_tables_match
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
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.context.targeted import run_context_targets
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.update_record import update_record
from .schemas import AirtableRecordMutationOutput
from .utils import (
    AIRTABLE_WRITE_BINDING,
    RESULTS_FIELD,
    airtable_client,
    pending_record_operation_detail,
)


async def airtable_update_record(
    ctx: RunContext[RuntimeDeps],
    table: Annotated[str, Field(description="Table name or id within the selected base.")],
    record_id: Annotated[
        AirtableRecordReference,
        Field(description="Scoped Airtable record to update."),
    ],
    fields: Annotated[dict[str, Any], Field(description="Field values to update.")],
) -> dict[str, Any]:
    normalized_table = table.strip()
    if not normalized_table or not fields:
        raise ModelRetry(
            "airtable_update_record requires a table, record_id, and at least one field."
        )
    if not airtable_tables_match(record_id.table, normalized_table):
        raise ModelRetry(
            "The Airtable table changed after this record was selected. "
            "Choose a record from the current table."
        )

    async def operation(entry: ResolvedContextEntry, references) -> Any:
        reference = references[0]
        pending_detail = pending_record_operation_detail(
            entry,
            action="update",
            table=record_id.table.strip(),
            field_count=len(fields),
            record_id=reference.record_id,
        )

        async def execute() -> Any:
            client = await airtable_client(ctx, entry)
            result = await update_record(
                client,
                base_id=entry.external_id,
                table=record_id.table.strip(),
                record_id=reference.record_id,
                fields=fields,
            )
            external_ref = str(result.get("record_id", "")) or None
            result["reference"] = AirtableRecordReference(
                base_id=entry.external_id,
                table=reference.table,
                record_id=external_ref or reference.record_id,
                label=reference.label,
                description=reference.description,
                scope_label=entry.display_name,
            )
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
            tool_name="airtable_update_record",
            operation="update_record",
            execute=execute,
            pending_operation_detail=pending_detail,
        )

    results = await run_context_targets(
        ctx,
        binding=AIRTABLE_WRITE_BINDING,
        references=[record_id],
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


DEFINITION = RuntimeToolDefinition(
    name="airtable_update_record",
    function=airtable_update_record,
    description="Update one selected record in its Airtable base and table.",
    provider="airtable",
    label="Update Airtable Record",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    takes_ctx=True,
    timeout=60,
    output_model=AirtableRecordMutationOutput,
    integration_binding=AIRTABLE_WRITE_BINDING,
    presentation=ToolPresentation(
        icon="airtable",
        running_label="Updating Airtable Record",
        completed_label="Updated Airtable Record",
        failed_label="Couldn't Update Airtable Record",
        approval_title="Update Airtable Record",
        approval_prompt="The agent wants to change this Airtable record.",
        approve_label="Approve & Update",
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
            ToolFieldPresentation(key="fields", label="Fields", format="keyvalue", editable=True),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
