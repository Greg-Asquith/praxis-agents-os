# apps/api/integrations/sharepoint/tools/update_file.py

"""Replace SharePoint file through the shared approval and audit runtime."""

from functools import partial

from pydantic_ai import RunContext

from core.exceptions.general import AppValidationError
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
from services.files.contract import contract_for_content_type
from services.integrations.files import FileReference

from ..operations.replace_item import replace_item, verify_current_version
from ..operations.utils import file_error
from ..operations.write_utils import TextContent, VersionToken, text_content_type
from ..references import SharePointDriveItemReference
from .mutations import UpdateFileInput
from .schemas import SharePointWriteOutput
from .utils import RESULTS_FIELD, SHAREPOINT_DRIVE_WRITE_BINDING, sharepoint_available
from .write_utils import (
    PreparedDriveWrite,
    content_bytes,
    mutation_display_args,
    pending_write_detail,
    require_editable_content_type,
    run_drive_write,
    validate_input,
    write_entry,
)


async def sharepoint_update_file(
    ctx: RunContext[RuntimeDeps],
    file: SharePointDriveItemReference,
    expected_version: VersionToken,
    content: TextContent | None = None,
    source: FileReference | None = None,
) -> dict:
    args = validate_input(
        UpdateFileInput,
        {"file": file, "expected_version": expected_version, "content": content, "source": source},
    )
    text_data = content_bytes(args.content) if args.content is not None else None
    entry = write_entry(ctx.deps, args.file)

    async def prepare(client, state, source_file):
        item = await verify_current_version(
            client,
            drive_id=entry.external_id,
            item_id=args.file.item_id,
            expected_version=args.expected_version,
        )
        if source_file is not None:
            data = source_file.data
            content_type = source_file.revision.content_type
            target_type = item["file"].get("mimeType")
            try:
                matching_type = (
                    isinstance(target_type, str)
                    and contract_for_content_type(target_type).content_type == content_type
                )
            except AppValidationError:
                matching_type = False
            if not matching_type:
                raise file_error(
                    "Choose a source File with the same type as the SharePoint file.",
                    "type_mismatch",
                    operation="update_file",
                )
        else:
            data = text_data
            require_editable_content_type(item["file"].get("mimeType"), operation="update_file")
            content_type = text_content_type(item.get("name", ""), operation="update_file")
        pending = pending_write_detail(
            entry,
            action="update_file",
            size_bytes=len(data),
            content_type=content_type,
            expected_version=args.expected_version,
            item_id=args.file.item_id,
        )

        async def mutate():
            await replace_item(
                client,
                drive_id=entry.external_id,
                item_id=args.file.item_id,
                data=data,
                expected_version=args.expected_version,
                state=state,
            )

        return PreparedDriveWrite(pending, mutate)

    return await run_drive_write(
        ctx,
        entry=entry,
        action="update_file",
        prepare=prepare,
        reference=args.file,
        source=args.source,
    )


DEFINITION = RuntimeToolDefinition(
    name="sharepoint_update_file",
    function=sharepoint_update_file,
    description="Replaces a file in a selected writable SharePoint library after approval. Provide either text content for a text file, or a source workspace File of the same type. Requires the version returned by sharepoint_read_file or sharepoint_copy_to_files. Changes to the remote version or reviewed source revision stop the replacement.",
    provider="sharepoint",
    label="Replace SharePoint file",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    supports_approval=True,
    takes_ctx=True,
    timeout=300,
    output_model=SharePointWriteOutput,
    integration_binding=SHAREPOINT_DRIVE_WRITE_BINDING,
    availability_check=sharepoint_available,
    approval_display_args=partial(mutation_display_args, UpdateFileInput),
    approval_review_fields=("source",),
    approval_input_model=UpdateFileInput,
    presentation=ToolPresentation(
        icon="sharepoint",
        running_label="Replacing SharePoint file",
        completed_label="Replaced SharePoint file",
        failed_label="Could not save to SharePoint",
        approval_title="Replace SharePoint file",
        approve_label="Replace file",
        approval_prompt="Replace this file in SharePoint library {_library} with the reviewed content. A changed version stops the replacement.",
        arg_fields=(
            ToolFieldPresentation(
                key="file",
                label="File",
                format="entity",
                editable=False,
                secondary=False,
                entity_kind="sharepoint_drive_item",
            ),
            ToolFieldPresentation(
                key="expected_version",
                label="Version",
                format="text",
                editable=False,
                secondary=False,
            ),
            ToolFieldPresentation(
                key="content", label="Content", format="multiline", editable=True, secondary=True
            ),
            ToolFieldPresentation(
                key="source",
                label="Source File",
                format="entity",
                editable=True,
                secondary=True,
                entity_kind="file",
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
