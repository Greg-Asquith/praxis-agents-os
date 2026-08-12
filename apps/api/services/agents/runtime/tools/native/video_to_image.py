# apps/api/services/agents/runtime/tools/native/video_to_image.py

"""Governed Google video-to-image generation from workspace Files.

Pydantic AI 2.20.0 maps video ``BinaryContent`` to Gemini ``inline_data``.
Workspace ``video/mov`` revisions are normalized to ``video/quicktime``, the
SDK-recognized MIME type. Inline data is bounded before provider dispatch by
``NATIVE_VIDEO_TO_IMAGE_MAX_INPUT_BYTES``. Gemini image output and explicit
safety refusals use the same normalized seams as ``generate_image``.

An inline MP4 conditions Gemini 3.1 Flash Image output. Google can return
image-only JPEG bytes despite the PNG request, which the shared persistence
boundary detects from the payload.
"""

from typing import Annotated

from pydantic import BaseModel, Field
from pydantic_ai import ModelRetry, RunContext

from core.exceptions.general import AppValidationError
from core.settings import settings
from services.agents.models.domain import PROVIDER_GOOGLE, ResolvedModel
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.entity_references.domain import FileReference
from services.agents.runtime.tools import (
    TOOL_EFFECT_SCOPE_INTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_NONE,
    TOOL_POLICY_APPROVAL,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.agents.runtime.tools.media_inputs import load_workspace_media_input
from services.agents.runtime.tools.native.image_generation import (
    configured_native_image_providers,
    resolve_image_generation_model,
    run_native_image_generation,
)
from services.agents.runtime.tools.registry import runtime_tool
from services.files import write_generated_image
from services.files.contract import FileCategory
from utils.validation import normalize_optional_text

DEFAULT_NATIVE_VIDEO_TO_IMAGE_MODEL = "gemini-3.1-flash-image"
VIDEO_MEDIA_TYPES = frozenset({"video/mov", "video/mp4"})
VIDEO_PROVIDER_MEDIA_TYPE_OVERRIDES = {"video/mov": "video/quicktime"}


class VideoToImageOutput(BaseModel):
    """Model-visible metadata for one image generated from a video."""

    prompt: str
    input_file_id: str
    input_revision_id: str
    input_name: str
    name: str
    file_id: str
    revision_id: str
    reference: FileReference
    width: int
    height: int
    size_bytes: int
    media_type: str
    model_provider: str
    model: str


def configured_video_to_image_provider() -> bool:
    """Return whether the Google native-image provider is configured."""
    return PROVIDER_GOOGLE in configured_native_image_providers()


@runtime_tool(
    name="generate_image_from_video",
    provider="native",
    label="Generate Image from Video",
    description=(
        "Generate one still image from the current revision of a workspace video using Google "
        "and save it to workspace Files. The UI displays the saved image automatically; do not "
        "construct Markdown, data, or attachment URLs for it."
    ),
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_INTERNAL,
    supports_approval=True,
    supports_auto=True,
    default_policy=TOOL_POLICY_APPROVAL,
    egress=TOOL_EGRESS_NONE,
    takes_ctx=True,
    timeout=None,
    output_model=VideoToImageOutput,
    availability_check=configured_video_to_image_provider,
    presentation=ToolPresentation(
        icon="image",
        running_label="Generating an Image from Video",
        completed_label="Generated {name}",
        failed_label="Couldn't Generate an Image from Video",
        approval_title="Generate an Image from Video",
        approval_prompt=(
            "The agent wants to use {file_id} to generate an image from this prompt: {prompt}"
        ),
        approve_label="Approve & Generate",
        arg_fields=(
            ToolFieldPresentation(
                key="prompt",
                label="Prompt",
                format="multiline",
                editable=True,
                placeholder="Describe the still image to create",
            ),
            ToolFieldPresentation(
                key="file_id",
                label="Source Video",
                format="entity",
                entity_kind="file",
            ),
        ),
        result_fields=(
            ToolFieldPresentation(
                key="reference",
                label="Generated Image",
                format="entity",
                entity_kind="file",
            ),
            ToolFieldPresentation(key="size_bytes", label="Size", format="bytes"),
            ToolFieldPresentation(key="width", label="Width", format="number"),
            ToolFieldPresentation(key="height", label="Height", format="number"),
        ),
    ),
)
async def generate_image_from_video(
    ctx: RunContext[RuntimeDeps],
    prompt: Annotated[
        str,
        Field(description="Detailed prompt for one still image derived from the video."),
    ],
    file_id: Annotated[
        FileReference,
        Field(description="Current workspace video to use as source material."),
    ],
    model: Annotated[
        str | None,
        Field(description="Optional Google helper model id. Omit to use the supported default."),
    ] = None,
) -> VideoToImageOutput:
    """Generate one image from a governed workspace video and persist it."""
    normalized_prompt = prompt.strip()
    if not normalized_prompt:
        raise ModelRetry("generate_image_from_video requires a non-empty prompt.")

    input_media = await load_workspace_media_input(
        ctx,
        file_id,
        category=FileCategory.VIDEO,
        allowed_media_types=VIDEO_MEDIA_TYPES,
        tool_name="generate_image_from_video",
        kind_label="video",
        max_bytes=settings.NATIVE_VIDEO_TO_IMAGE_MAX_INPUT_BYTES,
        media_type_overrides=VIDEO_PROVIDER_MEDIA_TYPE_OVERRIDES,
    )
    model_spec = resolve_video_to_image_model(model=model)
    image = await run_native_image_generation(
        deps=ctx.deps,
        prompt=normalized_prompt,
        aspect_ratio=None,
        model_spec=model_spec,
        action="video_to_image",
        input_media=(input_media.content,),
        output_format="png",
    )
    try:
        stored = await write_generated_image(
            ctx.deps.db,
            workspace=ctx.deps.workspace,
            agent=ctx.deps.agent,
            prompt=normalized_prompt,
            content=image.data,
            media_type=image.media_type,
            source="native_video_to_image",
            input_file_ids=(input_media.file_id,),
            input_revision_ids=(input_media.revision_id,),
        )
    except AppValidationError as exc:
        raise ModelRetry(exc.message) from exc

    return VideoToImageOutput(
        prompt=normalized_prompt,
        input_file_id=str(input_media.file_id),
        input_revision_id=str(input_media.revision_id),
        input_name=input_media.name,
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
        model_provider=PROVIDER_GOOGLE,
        model=model_spec.model,
    )


def resolve_video_to_image_model(*, model: str | None = None) -> ResolvedModel:
    """Resolve the single supported Google video-to-image helper model."""
    requested_model = normalize_optional_text(model) or DEFAULT_NATIVE_VIDEO_TO_IMAGE_MODEL
    if requested_model != DEFAULT_NATIVE_VIDEO_TO_IMAGE_MODEL:
        raise ModelRetry(
            "generate_image_from_video currently supports gemini-3.1-flash-image. "
            "Omit model to use it."
        )
    return resolve_image_generation_model(
        model_provider=PROVIDER_GOOGLE,
        model=requested_model,
    )
