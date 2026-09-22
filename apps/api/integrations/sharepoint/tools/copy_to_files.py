# apps/api/integrations/sharepoint/tools/copy_to_files.py

"""Copies a selected SharePoint file into immutable workspace storage."""

from typing import Annotated

from pydantic import Field
from pydantic_ai import RunContext

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_INTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_PROVIDER_QUERY,
    TOOL_POLICY_AUTO,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.audit_events import (
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    IntegrationOperationTarget,
    PendingIntegrationOperationDetail,
    terminal_applied_operation_detail,
)
from services.integrations.context.targeted import run_context_targets
from services.integrations.files import FileReference
from services.integrations.files.create_copy import create_copy
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.copy_item import copy_item
from ..operations.utils import item_result, untrusted
from ..operations.write_utils import item_version
from ..references import SharePointDriveItemReference
from .schemas import SharePointCopyData, SharePointCopyOutput
from .utils import (
    RESULTS_FIELD,
    SHAREPOINT_DRIVE_BINDING,
    bounded_output,
    drive_client,
    sharepoint_available,
)


async def sharepoint_copy_to_files(
    ctx: RunContext[RuntimeDeps],
    file: SharePointDriveItemReference,
    folder: Annotated[str | None, Field(max_length=255)] = None,
) -> dict:
    async def operation(entry, references):
        reference = references[0]

        async def execute():
            client = await drive_client(ctx, entry)
            item, content = await copy_item(
                client, drive_id=entry.external_id, item_id=reference.item_id
            )
            source = item_result(item, drive_id=entry.external_id, operation="copy_to_files")
            version = item_version(item, operation="copy_to_files")
            saved = await create_copy(
                ctx.deps,
                name=source["name"].content,
                content=content,
                content_type=item["file"]["mimeType"],
                folder=folder,
            )
            source_ref = f"{entry.external_id}:{reference.item_id}"
            detail = terminal_applied_operation_detail(
                PendingIntegrationOperationDetail(
                    target=IntegrationOperationTarget(
                        entity_type="sharepoint_drive_item",
                        external_id=reference.item_id,
                        attributes={"drive_id": entry.external_id},
                    ),
                    intent_groups=[
                        IntegrationOperationIntentGroup(
                            key="copy_to_files",
                            action="copy_to_files",
                            entity_type="file",
                            items=[IntegrationOperationIntent(fields={"source": source_ref})],
                        )
                    ],
                ),
                external_ref=str(saved.file.id),
            )
            detail.outcome_groups[0].outcomes[0].effects[0].fields.update(
                source=source_ref,
                version=version,
                file_id=str(saved.file.id),
                revision_id=str(saved.revision.id),
            )
            result = SharePointCopyData(
                reference=FileReference(entity_id=saved.file.id, label="Copied SharePoint file"),
                file_id=saved.file.id,
                revision_id=saved.revision.id,
                name=untrusted(entry.external_id, reference.item_id, saved.file.name),
                content_type=source["content_type"],
                size_bytes=saved.bytes_written,
                source=source,
                version=version,
            )
            return IntegrationAuditOutcome(
                result.model_dump(), external_ref=source_ref, operation_detail=detail
            )

        async with ctx.deps.db.begin_nested():
            return await run_audited_integration_operation(
                ctx,
                entry,
                tool_name="sharepoint_copy_to_files",
                operation="copy_to_files",
                execute=execute,
            )

    return bounded_output(
        await run_context_targets(
            ctx, binding=SHAREPOINT_DRIVE_BINDING, references=[file], operation=operation
        )
    )


DEFINITION = RuntimeToolDefinition(
    name="sharepoint_copy_to_files",
    function=sharepoint_copy_to_files,
    description=(
        "Copy original bytes from a selected SharePoint or OneDrive library into a new workspace "
        "File. Supports the Files document, text, image, and video types within their size limits. "
        "Optionally save into a named folder, creating it if needed. Returns a File reference "
        "for editing through run_code and the source version for sharepoint_update_file. "
        "The original bytes stay out of model context."
    ),
    provider="sharepoint",
    label="Copy SharePoint file to Files",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_INTERNAL,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    default_policy=TOOL_POLICY_AUTO,
    supports_auto=True,
    supports_approval=True,
    takes_ctx=True,
    timeout=300,
    output_model=SharePointCopyOutput,
    integration_binding=SHAREPOINT_DRIVE_BINDING,
    availability_check=sharepoint_available,
    presentation=ToolPresentation(
        icon="sharepoint",
        running_label="Copying SharePoint file to Files",
        completed_label="Copied SharePoint file to Files",
        failed_label="Could not copy SharePoint file to Files",
        approval_title="Copy SharePoint file to Files",
        approval_prompt="Save a copy of this SharePoint file in your workspace Files.",
        approve_label="Approve & Copy",
        arg_fields=(
            ToolFieldPresentation(
                key="file", label="File", format="entity", entity_kind="sharepoint_drive_item"
            ),
            ToolFieldPresentation(key="folder", label="Folder", editable=True, secondary=True),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
