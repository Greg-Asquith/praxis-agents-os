# apps/api/services/agents/runtime/tools/documents/read_word_document.py

"""Runtime tool for reading Word documents."""

from typing import Annotated

from pydantic import Field
from pydantic_ai import RunContext

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.entity_references.domain import FileReference
from services.agents.runtime.tools.contract import TOOL_EFFECT_READ, ToolPresentation
from services.agents.runtime.tools.documents.utils import (
    DOCUMENT_TOOL_TIMEOUT,
    FILE_ARG_FIELD,
    read_office_file,
)
from services.agents.runtime.tools.registry import runtime_tool


@runtime_tool(
    name="read_word_document",
    provider="core",
    label="Read Word Document",
    code_eligible=True,
    description=(
        "Read a .docx File's body in order: paragraphs (index, style, directly set list "
        "level, text, formatted spans, image references), tables, and content controls. "
        "Without start, the first page also lists paragraph styles, headers and footers "
        "per section and variant, comments, and external links. has_tracked_changes says "
        "whether the document has tracked changes; their content isn't shown. Text comes "
        "back as untrusted-content nodes. Long documents come back in pages: when next_start "
        "is present, call again with start set to it."
    ),
    effect=TOOL_EFFECT_READ,
    takes_ctx=True,
    timeout=DOCUMENT_TOOL_TIMEOUT,
    configurable=False,
    auto_mount=True,
    presentation=ToolPresentation(
        icon="file",
        running_label="Reading a Document",
        completed_label="Read a Document",
        failed_label="Couldn't Read the Document",
        arg_fields=(FILE_ARG_FIELD,),
    ),
)
async def read_word_document(
    ctx: RunContext[RuntimeDeps],
    file_id: FileReference,
    start: Annotated[
        int | None, Field(ge=0, description="The first block to read. Omit for the first page.")
    ] = None,
    limit: Annotated[int, Field(ge=1, le=1000, description="Most blocks to read.")] = 200,
):
    """Read a document's blocks, styles, headers, footers, and comments."""
    return await read_office_file(ctx, file_id, "docx", start=start, limit=limit)
