# apps/api/services/agents/runtime/tools/documents/edit_workbook.py

"""Runtime tool for editing Excel workbooks."""

from typing import Annotated
from uuid import UUID

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
    DOCUMENT_TOOL_TIMEOUT,
    EDITED_FILE_FIELD,
    WARNINGS_FIELD,
    edit_office_file,
)
from services.agents.runtime.tools.registry import runtime_tool
from services.documents.operations.workbook import WorkbookOperation


@runtime_tool(
    name="edit_workbook",
    provider="core",
    label="Edit Workbook",
    code_eligible=True,
    description=(
        "Change a .xlsx File and save it as a new revision. Read the workbook first and pass "
        "its revision_id as base_revision_id; if the File changed since, nothing is saved and "
        "you read it again. Operations run in order, and nothing is saved unless all succeed. "
        "A string starting with = is a formula. Write formulas for derived values instead of "
        "pasting computed numbers, keep inputs and calculations apart, and label units. Every "
        "formula's sheet, name, and table references are checked. After an edit, formula cells "
        "have no saved values until Excel opens the workbook, so compute any figure you report "
        "from source values and compare it with the read-back. Rows can be appended but not "
        "inserted or deleted. Workbooks with charts, images, shapes, chart sheets, slicers, "
        "threaded comments, form controls, custom XML data, or dynamic array formulas, or "
        f"more than {settings.DOCUMENT_TOOLS_EDIT_MAX_CELLS:,} cells, can't be edited; build "
        "the result with create_workbook instead."
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
        icon="file",
        running_label="Editing a Workbook",
        completed_label="Edited a Workbook",
        failed_label="Couldn't Edit the Workbook",
        approval_title="Edit a Workbook",
        approval_prompt=(
            "The agent wants to change this workbook. The changes are saved as a new version, "
            "and you can restore the previous one from Files."
        ),
        approve_label="Approve & Save",
        arg_fields=(EDITED_FILE_FIELD,),
        result_fields=(WARNINGS_FIELD,),
    ),
)
async def edit_workbook(
    ctx: RunContext[RuntimeDeps],
    file_id: FileReference,
    base_revision_id: Annotated[UUID, Field(description="The revision_id your read returned.")],
    operations: Annotated[
        list[WorkbookOperation],
        Field(min_length=1, max_length=settings.DOCUMENT_TOOLS_MAX_OPERATIONS),
    ],
):
    """Apply operations to a workbook and save a new revision."""
    return await edit_office_file(
        ctx,
        tool_name="edit_workbook",
        document_format="xlsx",
        file_id=file_id,
        base_revision_id=base_revision_id,
        operations=operations,
    )
