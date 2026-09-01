# apps/api/integrations/notion/tools/create_page.py

"""Create one Notion page through an approval-only audited mutation."""

import asyncio
from typing import Annotated, Any

from pydantic import AfterValidator, Field, StringConstraints
from pydantic_ai import ModelRetry, RunContext

from core.exceptions.integration import IntegrationError
from integrations.notion.references import (
    NotionDataSourceReference,
    NotionPageReference,
    notion_scoped_page_reference,
)
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
from ..operations.create_page import (
    MAX_NOTION_PAGE_TITLE_BYTES,
    MAX_NOTION_PAGE_TITLE_CHARS,
    CreatePagePreparation,
    create_page,
    prepare_create_page,
)
from ..operations.properties import validate_utf8_text
from .mutations import NotionPropertyRecords
from .schemas import NotionCreatePageOutput
from .utils import (
    NOTION_PROPERTY_COLUMNS,
    NOTION_WRITE_BINDING,
    RESULTS_FIELD,
    attach_notion_cancellation_evidence,
    bounded_notion_output,
    failed_notion_mutation_outcome,
    notion_available,
    notion_client,
    pending_create_page_detail,
    successful_notion_mutation_outcome,
)


def _validate_page_title(value: str) -> str:
    return validate_utf8_text(
        value,
        field_name="Page title",
        min_chars=1,
        max_chars=MAX_NOTION_PAGE_TITLE_CHARS,
        max_bytes=MAX_NOTION_PAGE_TITLE_BYTES,
    )


type NotionPageTitle = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_NOTION_PAGE_TITLE_CHARS),
    AfterValidator(_validate_page_title),
]


async def notion_create_page(
    ctx: RunContext[RuntimeDeps],
    title: Annotated[NotionPageTitle, Field(description="Title for the page to create.")],
    parent_page: Annotated[
        NotionPageReference | None,
        Field(description="Notion page to create the page under."),
    ] = None,
    parent_data_source: Annotated[
        NotionDataSourceReference | None,
        Field(description="Notion data source to create the page in."),
    ] = None,
    content_md: Annotated[
        str,
        Field(description="Optional Markdown content for the new page."),
    ] = "",
    properties: NotionPropertyRecords = (),
) -> dict[str, Any]:
    parent = _selected_parent(parent_page, parent_data_source)

    async def operation(entry: ResolvedContextEntry, references) -> Any:
        selected_parent = references[0]
        client: NotionClient | None = None
        prepared: CreatePagePreparation | None = None

        async def prepare_pending_operation():
            nonlocal client, prepared
            client = await notion_client(ctx, entry)
            prepared = await prepare_create_page(
                client,
                entry,
                parent_page=(
                    selected_parent if isinstance(selected_parent, NotionPageReference) else None
                ),
                parent_data_source=(
                    selected_parent
                    if isinstance(selected_parent, NotionDataSourceReference)
                    else None
                ),
                title=title,
                content_md=content_md,
                properties=properties,
            )
            return pending_create_page_detail(entry, prepared)

        async def execute():
            if client is None or prepared is None:
                raise RuntimeError("Notion page creation preparation did not complete")
            pending = pending_create_page_detail(entry, prepared)
            fallback = {
                "reference": None,
                "url": None,
                "title": prepared.title,
                "last_edited_time": None,
            }
            try:
                result = await create_page(client, prepared=prepared)
            except asyncio.CancelledError as exc:
                attach_notion_cancellation_evidence(exc, pending, operation="create_page")
                raise
            except IntegrationError as exc:
                return failed_notion_mutation_outcome(
                    pending,
                    fallback,
                    exc,
                    operation="create_page",
                )

            reference = notion_scoped_page_reference(
                entry,
                page_id=result["id"],
                label=result["title"],
            )
            return successful_notion_mutation_outcome(
                pending,
                {
                    "reference": reference,
                    "url": result["url"],
                    "title": result["title"],
                    "last_edited_time": result["last_edited_time"],
                },
                external_ref=result["id"],
                single_item=True,
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="notion_create_page",
            operation="create_page",
            execute=execute,
            prepare_pending_operation=prepare_pending_operation,
        )

    results = await run_context_targets(
        ctx,
        binding=NOTION_WRITE_BINDING,
        references=[parent],
        operation=operation,
    )
    return bounded_notion_output(results)


def _selected_parent(
    parent_page: NotionPageReference | None,
    parent_data_source: NotionDataSourceReference | None,
) -> NotionPageReference | NotionDataSourceReference:
    if (parent_page is None) == (parent_data_source is None):
        raise ModelRetry("Choose one Notion page or data source as the parent.")
    if parent_page is not None:
        return parent_page
    if parent_data_source is None:
        raise RuntimeError("Notion page creation requires one parent")
    return parent_data_source


DEFINITION = RuntimeToolDefinition(
    name="notion_create_page",
    function=notion_create_page,
    description="Create one page under a selected writable Notion page or data source.",
    provider="notion",
    label="Create Notion Page",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    supports_approval=True,
    takes_ctx=True,
    timeout=90,
    output_model=NotionCreatePageOutput,
    integration_binding=NOTION_WRITE_BINDING,
    availability_check=notion_available,
    presentation=ToolPresentation(
        icon="notion",
        running_label="Creating Notion Page",
        completed_label="Created Notion Page",
        failed_label="Couldn't Create Notion Page",
        approval_title="Create Notion Page",
        approval_prompt="The agent wants to create this page in Notion.",
        approve_label="Approve & Create",
        arg_fields=(
            ToolFieldPresentation(
                key="parent_page",
                label="Parent Page",
                format="entity",
                editable=True,
                secondary=True,
                entity_kind="notion_page",
            ),
            ToolFieldPresentation(
                key="parent_data_source",
                label="Parent Data Source",
                format="entity",
                editable=True,
                secondary=True,
                entity_kind="notion_data_source",
            ),
            ToolFieldPresentation(key="title", label="Title", editable=True),
            ToolFieldPresentation(
                key="content_md",
                label="Content",
                format="markdown",
                editable=True,
                secondary=True,
            ),
            ToolFieldPresentation(
                key="properties",
                label="Properties",
                format="records",
                editable=True,
                secondary=True,
                columns=NOTION_PROPERTY_COLUMNS,
                min_rows=0,
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
