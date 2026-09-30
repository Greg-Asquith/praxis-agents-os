# apps/api/services/agents/runtime/tools/documents/create_workbook.py

"""Runtime tool for creating Excel workbooks."""

from typing import Annotated

from pydantic import Field
from pydantic_ai import RunContext

from core.settings import settings
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.entity_references.domain import FileReference
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_INTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_POLICY_AUTO,
    ToolPresentation,
)
from services.agents.runtime.tools.documents.utils import (
    CREATE_ARG_FIELDS,
    DOCUMENT_TOOL_TIMEOUT,
    FOLDER_FIELD,
    NAME_FIELD,
    WARNINGS_FIELD,
    create_office_file,
)
from services.agents.runtime.tools.registry import runtime_tool
from services.documents.operations.workbook import WorkbookOperation


@runtime_tool(
    name="create_workbook",
    provider="core",
    label="Create Workbook",
    code_eligible=True,
    description=(
        "Create a new .xlsx File, from template_file_id or from a blank workbook with one sheet, "
        "Sheet1. The template's sheets and cells are kept. Operations are the same as "
        "edit_workbook's: write inputs as values, derived values as formulas, and label units. "
        "Add charts last, because a workbook with a chart can't be edited again. New Files go "
        "in this conversation's folder unless folder names another. The result gives the new "
        "File's id and revision_id for further edits."
    ),
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_INTERNAL,
    default_policy=TOOL_POLICY_AUTO,
    supports_auto=True,
    supports_approval=True,
    takes_ctx=True,
    timeout=DOCUMENT_TOOL_TIMEOUT,
    configurable=False,
    auto_mount=True,
    presentation=ToolPresentation(
        icon="file-plus",
        running_label="Creating {name}",
        completed_label="Created {name}",
        failed_label="Couldn't Create {name}",
        approval_title="Create a Workbook",
        approval_prompt="The agent wants to create a workbook in your workspace files.",
        approve_label="Approve & Create",
        arg_fields=CREATE_ARG_FIELDS,
        result_fields=(WARNINGS_FIELD,),
    ),
)
async def create_workbook(
    ctx: RunContext[RuntimeDeps],
    name: Annotated[str, NAME_FIELD],
    operations: Annotated[
        list[WorkbookOperation],
        Field(max_length=settings.DOCUMENT_TOOLS_MAX_OPERATIONS),
    ],
    template_file_id: FileReference | None = None,
    folder: Annotated[str | None, FOLDER_FIELD] = None,
):
    """Create a workbook from a template and operations."""
    return await create_office_file(
        ctx,
        tool_name="create_workbook",
        document_format="xlsx",
        name=name,
        folder=folder,
        template_file_id=template_file_id,
        clear_template=False,
        operations=operations,
    )
