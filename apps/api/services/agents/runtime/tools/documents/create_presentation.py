# apps/api/services/agents/runtime/tools/documents/create_presentation.py

"""Runtime tool for creating PowerPoint decks."""

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
from services.documents.operations.presentation import PresentationOperation


@runtime_tool(
    name="create_presentation",
    provider="core",
    label="Create Presentation",
    code_eligible=True,
    description=(
        "Create a new .pptx File. Start from template_file_id to keep a brand's layouts, fonts, "
        "and colours; otherwise a neutral 16:9 deck is used. Its main layouts, with body "
        "placeholder idx, are Title Slide and Title (subtitle 1), Section Header, Content (13), "
        "Two Content (18, 19), Comparison (headings 1 and 3, bodies 18 and 19), Agenda (13), "
        "Statement (17), Quote (13), Conclusion (13), Title Only, and Empty; every title is "
        "idx 0. Picture layouts exist too; read the deck for their idx. Unless "
        "keep_template_content is true, the template's slides are removed so only its layouts "
        "remain. Operations are the same as edit_presentation's; add slides with add_slide "
        "and fill their placeholders. Keep slide text short; split slides rather than "
        "shrinking fonts. New Files go in this conversation's folder unless folder names "
        "another. The result gives the new File's id and revision_id for further edits."
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
        approval_title="Create a Presentation",
        approval_prompt="The agent wants to create a presentation in your workspace files.",
        approve_label="Approve & Create",
        arg_fields=CREATE_ARG_FIELDS,
        result_fields=(WARNINGS_FIELD,),
    ),
)
async def create_presentation(
    ctx: RunContext[RuntimeDeps],
    name: Annotated[str, NAME_FIELD],
    operations: Annotated[
        list[PresentationOperation],
        Field(max_length=settings.DOCUMENT_TOOLS_MAX_OPERATIONS),
    ],
    template_file_id: FileReference | None = None,
    keep_template_content: bool = False,
    folder: Annotated[str | None, FOLDER_FIELD] = None,
):
    """Create a deck from a template and operations."""
    return await create_office_file(
        ctx,
        tool_name="create_presentation",
        document_format="pptx",
        name=name,
        folder=folder,
        template_file_id=template_file_id,
        clear_template=not keep_template_content,
        operations=operations,
    )
