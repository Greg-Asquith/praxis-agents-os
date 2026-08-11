# apps/api/services/agents/runtime/tools/native/image_editing.py

"""Governed image editing through OpenAI and Google helper models.

Pydantic AI 2.20.0 maps an input ``BinaryContent`` image into OpenAI
Responses ``input_image`` content and Google inline data. OpenAI receives
``ImageGeneration(action='edit')``; Google's image configuration ignores the
action and conditions generation on the inline image and prompt. Both paths
return image bytes through the same normalized ``ModelResponse.images`` seam
used by ``generate_image``. Explicit provider safety responses retain the
shared content-policy retry mapping.

OpenAI accepts one source image; Google preserves ordered multi-image input.
Google can return image-only JPEG output even when PNG is requested, so
persistence detects the actual bytes.
"""

from typing import Annotated

from pydantic import BaseModel, Field
from pydantic_ai import ModelRetry, RunContext

from core.exceptions.general import AppValidationError
from core.settings import settings
from services.agents.models.domain import PROVIDER_OPENAI, ResolvedModel
from services.agents.models.resolution import resolve_agent_model
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
from services.agents.runtime.tools.media_inputs import load_workspace_media_inputs
from services.agents.runtime.tools.native.image_generation import (
    _REGISTERED_NATIVE_IMAGE_PROVIDERS,
    DEFAULT_OPENAI_IMAGE_MODEL,
    NativeImageProvider,
    configured_native_image_providers,
    resolve_image_generation_model,
    run_native_image_generation,
)
from services.agents.runtime.tools.registry import runtime_tool
from services.files import write_generated_image
from services.files.contract import FileCategory
from services.files.resolve_chat_attachments import IMAGE_MEDIA_TYPES
from utils.validation import normalize_optional_text

_REGISTERED_EDIT_IMAGE_PROVIDERS = configured_native_image_providers()
_REGISTERED_EDIT_IMAGE_PROVIDER_LIST = (
    " and ".join(_REGISTERED_EDIT_IMAGE_PROVIDERS) if _REGISTERED_EDIT_IMAGE_PROVIDERS else "none"
)


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
    model_provider: NativeImageProvider
    model: str
    image_model: str


@runtime_tool(
    name="edit_image",
    provider="native",
    label="Edit Image",
    description=(
        "Edit one current workspace image revision and save the result to workspace Files. "
        "The UI displays the saved image automatically; do not construct Markdown, data, or "
        "attachment URLs for it. The helper provider can be selected from the configured "
        f"image providers: {_REGISTERED_EDIT_IMAGE_PROVIDER_LIST}."
    ),
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_INTERNAL,
    supports_approval=True,
    supports_auto=True,
    default_policy=TOOL_POLICY_APPROVAL,
    egress=TOOL_EGRESS_NONE,
    takes_ctx=True,
    timeout=None,
    output_model=EditImageOutput,
    availability_check=lambda: bool(configured_native_image_providers()),
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
                key="model_provider",
                label="Image Provider",
                editable=True,
                options=_REGISTERED_NATIVE_IMAGE_PROVIDERS,
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
                "Current workspace images to edit in reference order. Google accepts up to 14; "
                "OpenAI currently accepts one in this tool."
            ),
        ),
    ],
    model_provider: Annotated[
        Annotated[
            str,
            Field(json_schema_extra={"enum": list(_REGISTERED_EDIT_IMAGE_PROVIDERS)}),
        ]
        | None,
        Field(
            description=(
                "Optional image helper provider. Omit unless there is a reason to choose one."
            )
        ),
    ] = None,
    model: Annotated[
        str | None,
        Field(description="Optional helper model id. Omit to use the provider default."),
    ] = None,
) -> EditImageOutput:
    """Edit one governed workspace image and persist the result."""
    normalized_prompt = prompt.strip()
    if not normalized_prompt:
        raise ModelRetry("edit_image requires a non-empty prompt.")

    model_spec = resolve_image_editing_model(
        ctx.deps.agent,
        model_provider=model_provider,
        model=model,
    )
    if model_spec.provider == PROVIDER_OPENAI and len(file_ids) != 1:
        raise ModelRetry("OpenAI edit_image currently requires exactly one source image.")
    input_media = await load_workspace_media_inputs(
        ctx,
        file_ids,
        category=FileCategory.IMAGE,
        allowed_media_types=IMAGE_MEDIA_TYPES,
        tool_name="edit_image",
        kind_label="image",
        max_total_bytes=settings.NATIVE_IMAGE_EDITING_MAX_INPUT_BYTES,
    )
    image = await run_native_image_generation(
        prompt=normalized_prompt,
        aspect_ratio=None,
        model_spec=model_spec,
        action="edit",
        input_media=tuple(item.content for item in input_media),
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
            source="native_image_editing",
            input_file_ids=tuple(item.file_id for item in input_media),
            input_revision_ids=tuple(item.revision_id for item in input_media),
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
        model_provider=model_spec.provider,
        model=model_spec.model,
        image_model=(
            DEFAULT_OPENAI_IMAGE_MODEL
            if model_spec.provider == PROVIDER_OPENAI
            else model_spec.model
        ),
    )


def resolve_image_editing_model(
    agent,
    *,
    model_provider: str | None = None,
    model: str | None = None,
) -> ResolvedModel:
    """Resolve a configured OpenAI or Google image-editing helper model."""
    requested_provider = normalize_optional_text(model_provider)
    requested_model = normalize_optional_text(model)
    if requested_provider is None:
        if requested_model is not None:
            raise ModelRetry("edit_image model requires model_provider.")
        configured = configured_native_image_providers()
        if not configured:
            raise ModelRetry("No native edit_image providers are configured.")
        active_provider = resolve_agent_model(agent).provider
        requested_provider = active_provider if active_provider in configured else configured[0]
    return resolve_image_generation_model(
        model_provider=requested_provider,
        model=requested_model,
    )
