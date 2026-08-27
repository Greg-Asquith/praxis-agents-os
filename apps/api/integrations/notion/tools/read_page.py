# apps/api/integrations/notion/tools/read_page.py

"""Read one selected Notion page as bounded enhanced Markdown."""

from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import RunContext

from integrations.notion.references import NotionPageReference, notion_page_reference
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    TOOL_EGRESS_PROVIDER_QUERY,
    TOOL_POLICY_AUTO,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.targeted import run_context_targets
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.get_page import get_page
from ..operations.get_page_markdown import get_page_markdown
from .schemas import NotionPageOutput
from .utils import (
    NOTION_BINDING,
    RESULTS_FIELD,
    bounded_notion_output,
    notion_available,
    notion_client,
)


async def notion_read_page(
    ctx: RunContext[RuntimeDeps],
    page: Annotated[
        NotionPageReference,
        Field(description="Scoped Notion page reference returned by search."),
    ],
) -> dict[str, Any]:
    async def operation(entry: ResolvedContextEntry, references) -> Any:
        reference = references[0]

        async def execute() -> Any:
            client = await notion_client(ctx, entry)
            metadata = await get_page(client, page_id=reference.page_id)
            markdown = await get_page_markdown(client, page_id=reference.page_id)
            canonical_reference = notion_page_reference(entry, metadata)
            return IntegrationAuditOutcome(
                {
                    "reference": canonical_reference,
                    "title": metadata["title"],
                    "url": metadata["url"],
                    "source_updated_at": metadata["last_edited_time"],
                    **markdown,
                },
                external_ref=reference.page_id,
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="notion_read_page",
            operation="read_page",
            execute=execute,
        )

    results = await run_context_targets(
        ctx,
        binding=NOTION_BINDING,
        references=[page],
        operation=operation,
    )
    return bounded_notion_output(results)


DEFINITION = RuntimeToolDefinition(
    name="notion_read_page",
    function=notion_read_page,
    description="Read one selected Notion page as enhanced Markdown, with explicit size limits.",
    provider="notion",
    label="Read Notion Page",
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    default_policy=TOOL_POLICY_AUTO,
    takes_ctx=True,
    timeout=60,
    output_model=NotionPageOutput,
    integration_binding=NOTION_BINDING,
    availability_check=notion_available,
    presentation=ToolPresentation(
        icon="notion",
        running_label="Reading Notion Page",
        completed_label="Read Notion Page",
        failed_label="Couldn't Read Notion Page",
        arg_fields=(
            ToolFieldPresentation(
                key="page",
                label="Page",
                format="entity",
                editable=True,
                entity_kind="notion_page",
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
