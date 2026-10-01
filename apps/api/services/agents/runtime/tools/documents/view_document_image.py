# apps/api/services/agents/runtime/tools/documents/view_document_image.py

"""Runtime tool for looking at an image embedded in an Office file."""

from typing import Annotated

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext, ToolReturn
from pydantic_ai.messages import BinaryContent

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.entity_references.domain import FileReference, internal_entity_id
from services.agents.runtime.tools.contract import TOOL_EFFECT_READ, ToolPresentation
from services.agents.runtime.tools.documents.utils import (
    DOCUMENT_TOOL_TIMEOUT,
    FILE_ARG_FIELD,
    file_result,
    load_file,
    office_format,
    run_worker,
)
from services.agents.runtime.tools.files.utils import agent_model_supports_vision
from services.agents.runtime.tools.registry import runtime_tool


@runtime_tool(
    name="view_document_image",
    provider="core",
    label="View Document Image",
    code_eligible=False,
    description=(
        "Look at an image embedded in a .pptx, .xlsx, or .docx File. Pass an image reference "
        "from read_presentation, read_workbook, or read_word_document."
    ),
    effect=TOOL_EFFECT_READ,
    takes_ctx=True,
    timeout=DOCUMENT_TOOL_TIMEOUT,
    configurable=False,
    auto_mount=True,
    presentation=ToolPresentation(
        icon="image",
        running_label="Looking at an Image",
        completed_label="Looked at an Image",
        failed_label="Couldn't Show the Image",
        arg_fields=(FILE_ARG_FIELD,),
    ),
)
async def view_document_image(
    ctx: RunContext[RuntimeDeps],
    file_id: FileReference,
    image_ref: Annotated[
        str, Field(max_length=300, description="An image reference, such as ppt/media/image1.png.")
    ],
):
    """Return an embedded image as image content."""
    if not agent_model_supports_vision(ctx.deps):
        raise ModelRetry("The configured model can't look at images.")
    file, revision, document_format, data = await load_file(
        ctx, internal_entity_id(file_id), office_format
    )
    result = await run_worker(
        "extract_image",
        document_format=document_format,
        data=data,
        args={"image_ref": image_ref},
    )
    if result.data is None:
        raise ModelRetry("The image is empty.")
    return ToolReturn(
        return_value=[
            file_result(file, revision, {"image_ref": image_ref}),
            BinaryContent(
                data=result.data,
                media_type=result.value["media_type"],
                identifier=f"{file.id}:{image_ref}",
            ),
        ],
        metadata={"file_id": str(file.id), "revision_id": str(revision.id)},
    )
