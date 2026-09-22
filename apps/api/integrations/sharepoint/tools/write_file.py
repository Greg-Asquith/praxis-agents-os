# apps/api/integrations/sharepoint/tools/write_file.py

"""Save file to SharePoint through the shared approval and audit runtime."""

from functools import partial

from pydantic_ai import RunContext

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

from ..operations.upload_item import upload_item
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
    content: TextContent,
    folder: SharePointDriveItemReference | None = None,
) -> dict:
    args = validate_input(WriteFileInput, {"name": name, "content": content, "folder": folder})
    data = content_bytes(args.content)
    content_type = text_content_type(args.name, operation="write_file")
    entry = write_entry(ctx.deps, args.folder)

    async def prepare(client, state):
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
        ctx, entry=entry, action="write_file", prepare=prepare, reference=args.folder
    )


DEFINITION = RuntimeToolDefinition(
    name="sharepoint_write_file",
    function=sharepoint_write_file,
    description="Creates a text file in a selected writable SharePoint library after approval. Use a text extension (.txt, .md, .csv, .json, or .html). Without a folder, select exactly one writable library. Existing names fail; use sharepoint_update_file to replace a file.",
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
        approval_prompt="Save this text as a new file. If no folder is chosen, use the root of SharePoint library {_library}. No existing file is replaced.",
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
        ),
        result_fields=RESULTS_FIELD,
    ),
)
