# apps/api/integrations/sharepoint/tools/create_folder.py

"""Create SharePoint folder through the shared approval and audit runtime."""

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

from ..operations.create_folder import create_folder
from ..operations.write_utils import ItemName
from ..references import SharePointDriveItemReference
from .mutations import CreateFolderInput
from .schemas import SharePointWriteOutput
from .utils import RESULTS_FIELD, SHAREPOINT_DRIVE_WRITE_BINDING, sharepoint_available
from .write_utils import (
    PreparedDriveWrite,
    mutation_display_args,
    pending_write_detail,
    require_parent,
    run_drive_write,
    validate_input,
    write_entry,
)


async def sharepoint_create_folder(
    ctx: RunContext[RuntimeDeps],
    name: ItemName,
    parent: SharePointDriveItemReference | None = None,
) -> dict:
    args = validate_input(CreateFolderInput, {"name": name, "parent": parent})
    entry = write_entry(ctx.deps, args.parent)

    async def prepare(client, state, _source):
        parent_id = await require_parent(
            client, drive_id=entry.external_id, reference=args.parent, operation="create_folder"
        )
        pending = pending_write_detail(entry, action="create_folder")

        async def mutate():
            await create_folder(
                client, drive_id=entry.external_id, parent_id=parent_id, name=args.name, state=state
            )

        return PreparedDriveWrite(pending, mutate)

    return await run_drive_write(
        ctx, entry=entry, action="create_folder", prepare=prepare, reference=args.parent
    )


DEFINITION = RuntimeToolDefinition(
    name="sharepoint_create_folder",
    function=sharepoint_create_folder,
    description="Creates a folder in a selected writable SharePoint library after approval. Without a parent, select exactly one writable library. An existing name fails without renaming or replacing anything.",
    provider="sharepoint",
    label="Create SharePoint folder",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    supports_approval=True,
    takes_ctx=True,
    timeout=90,
    output_model=SharePointWriteOutput,
    integration_binding=SHAREPOINT_DRIVE_WRITE_BINDING,
    availability_check=sharepoint_available,
    approval_display_args=partial(mutation_display_args, CreateFolderInput),
    presentation=ToolPresentation(
        icon="sharepoint",
        running_label="Creating SharePoint folder",
        completed_label="Created SharePoint folder",
        failed_label="Could not save to SharePoint",
        approval_title="Create SharePoint folder",
        approve_label="Create folder",
        approval_prompt="Create this folder. If no parent folder is chosen, use the root of SharePoint library {_library}. Existing folders and files are kept.",
        arg_fields=(
            ToolFieldPresentation(
                key="name", label="Name", format="text", editable=True, secondary=False
            ),
            ToolFieldPresentation(
                key="parent",
                label="Parent folder",
                format="entity",
                editable=True,
                secondary=True,
                entity_kind="sharepoint_drive_item",
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
