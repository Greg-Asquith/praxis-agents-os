# apps/api/integrations/notion/tools/update_page_properties.py

"""Update Notion page properties through an approval-only audited mutation."""

import asyncio
from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import RunContext

from core.exceptions.integration import IntegrationError
from integrations.notion.references import NotionPageReference, notion_scoped_page_reference
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
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.targeted import run_context_targets
from services.integrations.operations import run_audited_integration_operation

from ..client import NotionClient
from ..operations.update_page_properties import (
    UpdatePagePropertiesPreparation,
    prepare_update_page_properties,
    update_page_properties,
)
from .mutations import NotionPropertyUpdateRecords
from .schemas import NotionUpdatePagePropertiesOutput
from .utils import (
    NOTION_PROPERTY_COLUMNS,
    NOTION_WRITE_BINDING,
    RESULTS_FIELD,
    attach_notion_cancellation_evidence,
    bounded_notion_output,
    failed_notion_mutation_outcome,
    notion_available,
    notion_client,
    pending_update_properties_detail,
    successful_notion_mutation_outcome,
)


async def notion_update_page_properties(
    ctx: RunContext[RuntimeDeps],
    page: Annotated[
        NotionPageReference,
        Field(description="Scoped Notion page reference returned by search."),
    ],
    properties: NotionPropertyUpdateRecords,
) -> dict[str, Any]:
    async def operation(entry: ResolvedContextEntry, references) -> Any:
        selected_page = references[0]
        if not isinstance(selected_page, NotionPageReference):
            raise TypeError("Notion property updates require a page reference")
        client: NotionClient | None = None
        prepared: UpdatePagePropertiesPreparation | None = None

        async def prepare_pending_operation():
            nonlocal client, prepared
            client = await notion_client(ctx, entry)
            prepared = await prepare_update_page_properties(
                client,
                entry,
                page=selected_page,
                properties=properties,
            )
            return pending_update_properties_detail(entry, prepared)

        async def execute():
            if client is None or prepared is None:
                raise RuntimeError("Notion property update preparation did not complete")
            pending = pending_update_properties_detail(entry, prepared)
            reference = notion_scoped_page_reference(
                entry,
                page_id=prepared.page.external_id,
                label=prepared.page.display_name,
            )
            fallback = {
                "reference": reference,
                "url": None,
                "last_edited_time": None,
            }
            try:
                result = await update_page_properties(client, prepared=prepared)
            except asyncio.CancelledError as exc:
                attach_notion_cancellation_evidence(
                    exc,
                    pending,
                    operation="update_page_properties",
                )
                raise
            except IntegrationError as exc:
                return failed_notion_mutation_outcome(
                    pending,
                    fallback,
                    exc,
                    operation="update_page_properties",
                )

            return successful_notion_mutation_outcome(
                pending,
                {
                    "reference": reference,
                    "url": result["url"],
                    "last_edited_time": result["last_edited_time"],
                },
                external_ref=result["id"],
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="notion_update_page_properties",
            operation="update_page_properties",
            execute=execute,
            prepare_pending_operation=prepare_pending_operation,
        )

    results = await run_context_targets(
        ctx,
        binding=NOTION_WRITE_BINDING,
        references=[page],
        operation=operation,
    )
    return bounded_notion_output(results)


DEFINITION = RuntimeToolDefinition(
    name="notion_update_page_properties",
    function=notion_update_page_properties,
    description="Update schema-validated properties on one selected writable Notion page.",
    provider="notion",
    label="Update Notion Page Properties",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    supports_approval=True,
    takes_ctx=True,
    timeout=90,
    output_model=NotionUpdatePagePropertiesOutput,
    integration_binding=NOTION_WRITE_BINDING,
    availability_check=notion_available,
    presentation=ToolPresentation(
        icon="notion",
        running_label="Updating Notion Page Properties",
        completed_label="Updated Notion Page Properties",
        failed_label="Couldn't Update Notion Page Properties",
        approval_title="Update Notion Page Properties",
        approval_prompt="The agent wants to change these Notion page properties.",
        approve_label="Approve & Update",
        arg_fields=(
            ToolFieldPresentation(
                key="page",
                label="Page",
                format="entity",
                editable=True,
                entity_kind="notion_page",
            ),
            ToolFieldPresentation(
                key="properties",
                label="Properties",
                format="records",
                editable=True,
                columns=NOTION_PROPERTY_COLUMNS,
                min_rows=1,
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
