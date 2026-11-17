# apps/api/services/agents/runtime/tools/native/image_editing.py

"""Governed image editing with the media catalogue's image models.

OpenAI receives one source image and the unchanged prompt directly. Google
preserves ordered multi-image input and can return JPEG when PNG is requested;
persistence detects the actual bytes.
"""

from typing import Annotated

from pydantic import BaseModel, Field
from pydantic_ai import ModelRetry, RunContext

from core.exceptions.general import AppValidationError
from core.settings import settings
from services.agents.models.domain import PROVIDER_OPENAI
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.entity_references.domain import FileReference
from services.agents.runtime.tools import (
    TOOL_EFFECT_SCOPE_INTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_NONE,
    TOOL_POLICY_AUTO,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.agents.runtime.tools.media_inputs import load_workspace_media_inputs
from services.agents.runtime.tools.native.image_generation import (
    image_model_description,
    image_model_display_args,
    image_model_option_labels,
    resolve_image_model,
    run_native_image_generation,
)
from services.agents.runtime.tools.registry import runtime_tool
from services.files import write_generated_image
from services.files.contract import FileCategory
from services.files.resolve_chat_attachments import IMAGE_MEDIA_TYPES
from services.media.catalogue import available_media_models

_EDIT_MODEL_LABELS = image_model_option_labels("edit_image")


class EditImageOutput(BaseModel):
    """Model-visible metadata for one edited workspace image."""

    prompt: str
    input_file_ids: list[str]
    input_revision_ids: list[str]
    input_names: list[str]
    name: str
    file_id: str
    revision_id: str
    reference: FileReference
    width: int
    height: int
    size_bytes: int
    media_type: str
    model: str
    model_provider: str
    image_model: str


@runtime_tool(
    name="edit_image",
    provider="native",
    label="Edit Image",
    code_eligible=False,
    description=(
        "Edit one current workspace image revision and save the result to workspace Files. "
        "The UI displays the saved image automatically; do not construct Markdown, data, or "
        "attachment URLs for it."
    ),
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_INTERNAL,
    supports_approval=True,
    supports_auto=True,
    default_policy=TOOL_POLICY_AUTO,
    egress=TOOL_EGRESS_NONE,
    takes_ctx=True,
    timeout=None,
    output_model=EditImageOutput,
    availability_check=lambda: bool(available_media_models("edit_image")),
    approval_display_args=image_model_display_args("edit_image"),
    presentation=ToolPresentation(
        icon="image",
        running_label="Editing an Image",
        completed_label="Edited {name}",
        failed_label="Couldn't Edit the Image",
        approval_title="Edit an Image",
        approval_prompt="The agent wants to edit {file_ids} using this prompt: {prompt}",
        approve_label="Approve & Edit",
        arg_fields=(
            ToolFieldPresentation(
                key="prompt",
                label="Prompt",
                format="multiline",
                editable=True,
                placeholder="Describe the changes to make",
            ),
            ToolFieldPresentation(
                key="file_ids",
                label="Source Images",
                format="entity_list",
                entity_kind="file",
            ),
            ToolFieldPresentation(
                key="model",
                label="Image Model",
                editable=True,
                options=tuple(_EDIT_MODEL_LABELS),
                option_labels=_EDIT_MODEL_LABELS,
            ),
        ),
        result_fields=(
            ToolFieldPresentation(
                key="reference",
                label="Edited Image",
                format="entity",
                entity_kind="file",
            ),
            ToolFieldPresentation(key="size_bytes", label="Size", format="bytes"),
            ToolFieldPresentation(key="width", label="Width", format="number"),
            ToolFieldPresentation(key="height", label="Height", format="number"),
        ),
    ),
)
async def edit_image(
    ctx: RunContext[RuntimeDeps],
    prompt: Annotated[str, Field(description="Detailed instructions for editing the image.")],
    file_ids: Annotated[
        list[FileReference],
        Field(
            min_length=1,
            max_length=14,
            description=(
                "Current workspace images to edit in reference order. Nano Banana accepts up "
                "to 14; GPT Image accepts one."
            ),
        ),
    ],
    model: Annotated[
        Annotated[str, Field(json_schema_extra={"enum": list(_EDIT_MODEL_LABELS)})] | None,
        Field(description=image_model_description("edit_image")),
    ] = None,
) -> EditImageOutput:
    """Edit one governed workspace image and persist the result."""
    normalized_prompt = prompt.strip()
    if not normalized_prompt:
        raise ModelRetry("edit_image requires a non-empty prompt.")

    choice = resolve_image_model(model, "edit_image")
    max_inputs = choice.model.limits.max_input_images
    if max_inputs is not None and len(file_ids) > max_inputs:
        raise ModelRetry(
            f"{choice.model.label} edits at most {max_inputs} source image"
            f"{'' if max_inputs == 1 else 's'} at a time. Pass fewer or choose another model."
        )
    if choice.spec.provider == PROVIDER_OPENAI:
        normalized_prompt = prompt
    input_media = await load_workspace_media_inputs(
        ctx,
        file_ids,
        category=FileCategory.IMAGE,
        allowed_media_types=IMAGE_MEDIA_TYPES,
        tool_name="edit_image",
        kind_label="image",
        max_total_bytes=settings.NATIVE_IMAGE_EDITING_MAX_INPUT_BYTES,
    )
    await ctx.deps.db.commit()
    image = await run_native_image_generation(
        deps=ctx.deps,
        prompt=normalized_prompt,
        aspect_ratio=None,
        model_spec=choice.spec,
        action="edit",
        input_media=tuple(item.content for item in input_media),
        output_format="png",
        usage_details=choice.usage_details,
    )
    try:
        stored = await write_generated_image(
            ctx.deps.db,
            workspace=ctx.deps.workspace,
            agent=ctx.deps.agent,
            prompt=normalized_prompt,
            content=image.data,
            media_type=image.media_type,
            source="native_image_editing",
            input_file_ids=tuple(item.file_id for item in input_media),
            input_revision_ids=tuple(item.revision_id for item in input_media),
            conversation_id=ctx.deps.conversation.id,
            requested_by_user_id=ctx.deps.user.id,
        )
    except AppValidationError as exc:
        raise ModelRetry(exc.message) from exc

    return EditImageOutput(
        prompt=normalized_prompt,
        input_file_ids=[str(item.file_id) for item in input_media],
        input_revision_ids=[str(item.revision_id) for item in input_media],
        input_names=[item.name for item in input_media],
        name=stored.name,
        file_id=str(stored.file_id),
        revision_id=str(stored.revision_id),
        reference=FileReference(
            entity_id=stored.file_id,
            label=stored.name,
            description=f"Image · {stored.width}x{stored.height} · {stored.size_bytes:,} bytes",
        ),
        width=stored.width,
        height=stored.height,
        size_bytes=stored.size_bytes,
        media_type=stored.content_type,
        model=choice.model.id,
        model_provider=choice.spec.provider,
        image_model=choice.spec.model,
    )
