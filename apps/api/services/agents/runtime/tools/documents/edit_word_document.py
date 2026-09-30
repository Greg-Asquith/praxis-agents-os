# apps/api/services/agents/runtime/tools/documents/edit_word_document.py

"""Runtime tool for editing Word documents."""

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
from services.documents.operations.word import WordOperation


@runtime_tool(
    name="edit_word_document",
    provider="core",
    label="Edit Word Document",
    code_eligible=True,
    description=(
        "Change a .docx File and save it as a new revision. Read the document first and pass "
        "its revision_id as base_revision_id; if the File changed since, nothing is saved and "
        "you read it again. Operations run in order, and nothing is saved unless all succeed. "
        "Paragraph operations, including add_comment, target a paragraph by its index from the "
        "read plus expect_text, the start of its current text; the operation fails if they "
        "don't match. replace_text changes every match in the body and tables and takes "
        "neither, so make find specific. Indexes shift as earlier operations in the same call "
        "insert or delete paragraphs. Use the document's own styles from the read. Edits that "
        "would remove images, fields, links, or comments fail instead; use replace_text for "
        "text inside them. Edits aren't tracked changes. "
        "The result lists each change, reads back every block it touched, and gives the new "
        "revision_id for the next edit. Compare the read-back with what you meant to write."
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
        running_label="Editing a Document",
        completed_label="Edited a Document",
        failed_label="Couldn't Edit the Document",
        approval_title="Edit a Document",
        approval_prompt=(
            "The agent wants to change this document. The changes are saved as a new version, "
            "and you can restore the previous one from Files."
        ),
        approve_label="Approve & Save",
        arg_fields=(EDITED_FILE_FIELD,),
        result_fields=(WARNINGS_FIELD,),
    ),
)
async def edit_word_document(
    ctx: RunContext[RuntimeDeps],
    file_id: FileReference,
    base_revision_id: Annotated[UUID, Field(description="The revision_id your read returned.")],
    operations: Annotated[
        list[WordOperation],
        Field(min_length=1, max_length=settings.DOCUMENT_TOOLS_MAX_OPERATIONS),
    ],
):
    """Apply operations to a Word document and save a new revision."""
    return await edit_office_file(
        ctx,
        tool_name="edit_word_document",
        document_format="docx",
        file_id=file_id,
        base_revision_id=base_revision_id,
        operations=operations,
    )
