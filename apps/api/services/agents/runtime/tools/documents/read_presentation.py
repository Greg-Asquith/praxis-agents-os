# apps/api/services/agents/runtime/tools/documents/read_presentation.py

"""Runtime tool for reading PowerPoint decks."""

from typing import Annotated

from pydantic import Field
from pydantic_ai import RunContext

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.entity_references.domain import FileReference
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.agents.runtime.tools.documents.utils import (
    DOCUMENT_TOOL_TIMEOUT,
    FILE_ARG_FIELD,
    read_office_file,
)
from services.agents.runtime.tools.registry import runtime_tool


@runtime_tool(
    name="read_presentation",
    provider="core",
    label="Read Presentation",
    code_eligible=True,
    description=(
        "Read a .pptx File's structure and text: slide size and, per slide, its id, layout, "
        "background images, shapes (id, kind, placeholder, position in points, paragraphs, "
        "table cells, chart series with x values and bubble sizes where the chart has them, "
        "image references), and notes. Without slides, the first page also lists layouts with "
        "their placeholders and external links. Paragraph spans give character ranges with "
        "explicit formatting; a soft line break is a vertical tab. Text comes back as "
        "untrusted-content nodes; read the text from each node's content. Long decks come back "
        "in pages: when next_slide is present, call again with slides listing the numbers from "
        "next_slide onwards. Read a deck before editing it."
    ),
    effect=TOOL_EFFECT_READ,
    takes_ctx=True,
    timeout=DOCUMENT_TOOL_TIMEOUT,
    configurable=False,
    auto_mount=True,
    presentation=ToolPresentation(
        icon="file",
        running_label="Reading a Presentation",
        completed_label="Read a Presentation",
        failed_label="Couldn't Read the Presentation",
        arg_fields=(
            FILE_ARG_FIELD,
            ToolFieldPresentation(key="slides", label="Slides", format="list", secondary=True),
        ),
    ),
)
async def read_presentation(
    ctx: RunContext[RuntimeDeps],
    file_id: FileReference,
    slides: Annotated[
        list[Annotated[int, Field(ge=1)]] | None,
        Field(max_length=500, description="Slide numbers to read, starting at 1. Omit for all."),
    ] = None,
):
    """Read a presentation's layouts and slides."""
    return await read_office_file(ctx, file_id, "pptx", slides=slides)
