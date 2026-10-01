# apps/api/services/agents/runtime/tools/documents/create_word_document.py

"""Runtime tool for creating Word documents."""

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
from services.documents.operations.word import WordOperation


@runtime_tool(
    name="create_word_document",
    provider="core",
    label="Create Word Document",
    code_eligible=True,
    description=(
        "Create a new .docx File. Start from template_file_id to keep a brand's styles, "
        "headers, and footers; otherwise a plain document with heading, list, and table "
        "styles is used. Unless keep_template_content is true, the template's body and "
        "comments are removed and its styles, headers, footers, and sections stay. Operations "
        "are the same as edit_word_document's; without an index, insert_paragraphs and "
        "insert_table add to the end. New Files go in this conversation's folder unless folder "
        "names another. The result gives the new File's id and revision_id for further edits."
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
        approval_title="Create a Document",
        approval_prompt="The agent wants to create a document in your workspace files.",
        approve_label="Approve & Create",
        arg_fields=CREATE_ARG_FIELDS,
        result_fields=(WARNINGS_FIELD,),
    ),
)
async def create_word_document(
    ctx: RunContext[RuntimeDeps],
    name: Annotated[str, NAME_FIELD],
    operations: Annotated[
        list[WordOperation],
        Field(max_length=settings.DOCUMENT_TOOLS_MAX_OPERATIONS),
    ],
    template_file_id: FileReference | None = None,
    keep_template_content: bool = False,
    folder: Annotated[str | None, FOLDER_FIELD] = None,
):
    """Create a Word document from a template and operations."""
    return await create_office_file(
        ctx,
        tool_name="create_word_document",
        document_format="docx",
        name=name,
        folder=folder,
        template_file_id=template_file_id,
        clear_template=not keep_template_content,
        operations=operations,
    )
