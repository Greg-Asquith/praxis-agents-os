# apps/api/integrations/sharepoint/tools/write_file.py

"""Save file to SharePoint through the shared approval and audit runtime."""

from functools import partial
from pathlib import PurePosixPath

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
from services.files.contract import require_matching_pair
from services.integrations.files import FileReference

from ..operations.upload_item import upload_item
from ..operations.utils import file_error
from ..operations.write_utils import ItemName, TextContent, text_content_type
from ..references import SharePointDriveItemReference
from .mutations import WriteFileInput
from .schemas import SharePointWriteOutput
from .utils import RESULTS_FIELD, SHAREPOINT_DRIVE_WRITE_BINDING, sharepoint_available
from .write_utils import (
    PreparedDriveWrite,
    content_bytes,
    mutation_display_args,
    pending_write_detail,
    require_parent,
    run_drive_write,
    validate_input,
    write_entry,
)


async def sharepoint_write_file(
    ctx: RunContext[RuntimeDeps],
    name: ItemName,
    content: TextContent | None = None,
    folder: SharePointDriveItemReference | None = None,
    source: FileReference | None = None,
) -> dict:
    args = validate_input(
        WriteFileInput, {"name": name, "content": content, "folder": folder, "source": source}
    )
    text_data = content_bytes(args.content) if args.content is not None else None
    entry = write_entry(ctx.deps, args.folder)

    async def prepare(client, state, source_file):
        data = source_file.data if source_file is not None else text_data
        content_type = (
            source_file.revision.content_type
            if source_file is not None
            else text_content_type(args.name, operation="write_file")
        )
        try:
            require_matching_pair(content_type, PurePosixPath(args.name).suffix)
        except AppValidationError:
            raise file_error(
                "Choose a name with an extension matching the source File type.",
                "type_mismatch",
                operation="write_file",
            ) from None
        parent_id = await require_parent(
            client, drive_id=entry.external_id, reference=args.folder, operation="write_file"
        )
        pending = pending_write_detail(
            entry, action="write_file", size_bytes=len(data), content_type=content_type
        )

        async def mutate():
            await upload_item(
                client,
                drive_id=entry.external_id,
                parent_id=parent_id,
                name=args.name,
                data=data,
                state=state,
            )

        return PreparedDriveWrite(pending, mutate)

    return await run_drive_write(
        ctx,
        entry=entry,
        action="write_file",
        prepare=prepare,
        reference=args.folder,
        source=args.source,
    )


DEFINITION = RuntimeToolDefinition(
    name="sharepoint_write_file",
    function=sharepoint_write_file,
    description="Creates a file in a selected writable SharePoint library after approval. Provide either text content with a text extension, or a source workspace File reference. The name extension must match the source type. Without a folder, select exactly one writable library. Existing names fail; use sharepoint_update_file to replace a file.",
    provider="sharepoint",
    label="Save file to SharePoint",
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
    approval_display_args=partial(mutation_display_args, WriteFileInput),
    presentation=ToolPresentation(
        icon="sharepoint",
        running_label="Saving SharePoint file",
        completed_label="Saved SharePoint file",
        failed_label="Could not save to SharePoint",
        approval_title="Save file to SharePoint",
        approve_label="Save file",
        approval_prompt="Save the reviewed content as a new file. If no folder is chosen, use the root of SharePoint library {_library}. No existing file is replaced.",
        arg_fields=(
            ToolFieldPresentation(
                key="name", label="Name", format="text", editable=True, secondary=False
            ),
            ToolFieldPresentation(
                key="folder",
                label="Folder",
                format="entity",
                editable=True,
                secondary=True,
                entity_kind="sharepoint_drive_item",
            ),
            ToolFieldPresentation(
                key="content", label="Content", format="multiline", editable=True, secondary=False
            ),
            ToolFieldPresentation(
                key="source",
                label="Source File",
                format="entity",
                editable=False,
                secondary=True,
                entity_kind="file",
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
