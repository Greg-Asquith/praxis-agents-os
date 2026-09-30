# apps/api/services/agents/runtime/tools/documents/edit_presentation.py

"""Runtime tool for editing PowerPoint decks."""

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
from services.documents.operations.presentation import PresentationOperation


@runtime_tool(
    name="edit_presentation",
    provider="core",
    label="Edit Presentation",
    code_eligible=True,
    description=(
        "Change a .pptx File and save it as a new revision. Read the deck first and pass its "
        "revision_id as base_revision_id; if the File changed since, nothing is saved and you "
        "read it again. Operations run in order, and nothing is saved unless all succeed. "
        "Target slides by slide_id and shapes by shape_id from the read. Edit the operator's "
        "deck rather than recreating it: new text keeps the formatting of the text it "
        "replaces, so the template's fonts and colours stay. Keep text short enough to fit "
        "its placeholder; split slides rather than shrinking fonts. The result lists each "
        "change, reads back every slide it touched, and gives the new revision_id for the "
        "next edit. Compare the read-back with what you meant to write. Slides with charts, "
        "videos, or embedded objects can't be duplicated."
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
        running_label="Editing a Presentation",
        completed_label="Edited a Presentation",
        failed_label="Couldn't Edit the Presentation",
        approval_title="Edit a Presentation",
        approval_prompt=(
            "The agent wants to change this presentation. The changes are saved as a new "
            "version, and you can restore the previous one from Files."
        ),
        approve_label="Approve & Save",
        arg_fields=(EDITED_FILE_FIELD,),
        result_fields=(WARNINGS_FIELD,),
    ),
)
async def edit_presentation(
    ctx: RunContext[RuntimeDeps],
    file_id: FileReference,
    base_revision_id: Annotated[UUID, Field(description="The revision_id your read returned.")],
    operations: Annotated[
        list[PresentationOperation],
        Field(min_length=1, max_length=settings.DOCUMENT_TOOLS_MAX_OPERATIONS),
    ],
):
    """Apply operations to a deck and save a new revision."""
    return await edit_office_file(
        ctx,
        tool_name="edit_presentation",
        document_format="pptx",
        file_id=file_id,
        base_revision_id=base_revision_id,
        operations=operations,
    )
