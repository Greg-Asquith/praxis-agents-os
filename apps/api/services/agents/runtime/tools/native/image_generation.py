# apps/api/services/agents/runtime/tools/native/image_generation.py

"""Audited provider-native image generation through configured helper models.

Pydantic AI 2.20.0 normalizes OpenAI Responses image-generation output and
Google inline image output as ``FilePart(BinaryImage)`` values on the helper
result messages. OpenAI content-policy refusals arrive with
``finish_reason='content_filter'`` and refusal provider details; Google safety
blocks use the same finish reason plus block-reason provider details. Praxis
maps only those explicit refusal shapes to content-policy outcome language and
keeps transport or missing-image failures distinct.

The OpenAI helper uses the current GPT-5.6 Luna Responses model with the current
``gpt-image-2`` image model. Google uses ``gemini-3.1-flash-image`` directly.
The registered schema snapshots configured providers at process start;
credential changes require an API and worker restart to refresh its choices.
"""

from typing import Annotated, Literal, get_args

from pydantic import BaseModel, Field
from pydantic_ai import Agent as PydanticAgent, ModelRetry, RunContext
from pydantic_ai.capabilities import ImageGeneration
from pydantic_ai.messages import BinaryImage, ModelMessage, ModelResponse
from pydantic_ai.native_tools import ImageAspectRatio
from pydantic_ai.usage import UsageLimits

from core.exceptions.general import AppValidationError
from core.settings import settings
from services.agents.models import build_model
from services.agents.models.domain import (
    PROVIDER_GOOGLE,
    PROVIDER_OPENAI,
    ModelConfigurationError,
    ResolvedModel,
)
from services.agents.models.registry import get_model
from services.agents.models.utils import is_provider_configured
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
from services.agents.runtime.tools.registry import runtime_tool
from services.files import write_generated_image
from utils.validation import normalize_optional_text

NativeImageProvider = Literal["google", "openai"]

SUPPORTED_NATIVE_IMAGE_PROVIDERS = (PROVIDER_GOOGLE, PROVIDER_OPENAI)
SUPPORTED_IMAGE_ASPECT_RATIOS: tuple[ImageAspectRatio, ...] = get_args(ImageAspectRatio)
OPENAI_IMAGE_ASPECT_RATIOS: tuple[ImageAspectRatio, ...] = ("1:1", "2:3", "3:2")
DEFAULT_NATIVE_IMAGE_MODELS = {
    PROVIDER_GOOGLE: "gemini-3.1-flash-image",
    PROVIDER_OPENAI: "gpt-5.6-luna",
}
DEFAULT_OPENAI_IMAGE_MODEL = "gpt-image-2"

IMAGE_GENERATION_HELPER_INSTRUCTIONS = """\
Generate exactly one new image from the user's prompt using the native image
generation capability. Do not edit or depend on an input image. After the image
is generated, respond with a short confirmation and do not generate another.
"""


def configured_native_image_providers() -> tuple[str, ...]:
    """Return configured native-image providers in stable order."""
    return tuple(
        provider
        for provider in SUPPORTED_NATIVE_IMAGE_PROVIDERS
        if is_provider_configured(provider)
    )


def _format_provider_list(providers: tuple[str, ...]) -> str:
    if not providers:
        return "none"
    if len(providers) == 1:
        return providers[0]
    return " and ".join(providers)


_REGISTERED_NATIVE_IMAGE_PROVIDERS = configured_native_image_providers()
_REGISTERED_NATIVE_IMAGE_PROVIDER_CSV = ", ".join(_REGISTERED_NATIVE_IMAGE_PROVIDERS) or "none"
_REGISTERED_NATIVE_IMAGE_PROVIDER_LIST = _format_provider_list(_REGISTERED_NATIVE_IMAGE_PROVIDERS)


class GenerateImageOutput(BaseModel):
    """Model-visible metadata for one generated workspace image."""

    prompt: str
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
    name="generate_image",
    provider="native",
    label="Generate Image",
    description=(
        "Generate one new image and save it to workspace Files using a provider-native helper "
        "model. The UI displays the saved image automatically; do not construct Markdown, data, "
        "or attachment URLs for it. Image editing is not supported. The helper provider can be "
        f"selected from the available native image providers: {_REGISTERED_NATIVE_IMAGE_PROVIDER_CSV}."
    ),
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_INTERNAL,
    supports_approval=True,
    supports_auto=True,
    default_policy=TOOL_POLICY_APPROVAL,
    egress=TOOL_EGRESS_NONE,
    takes_ctx=True,
    timeout=None,
    output_model=GenerateImageOutput,
    availability_check=lambda: bool(configured_native_image_providers()),
    presentation=ToolPresentation(
        icon="image",
        running_label="Generating an Image",
        completed_label="Generated {name}",
        failed_label="Couldn't Generate the Image",
        approval_title="Generate an Image",
        approval_prompt="The agent wants to generate an image from this prompt: {prompt}",
        approve_label="Approve & Generate",
        arg_fields=(
            ToolFieldPresentation(
                key="prompt",
                label="Prompt",
                format="multiline",
                editable=True,
                placeholder="Describe the image to generate",
            ),
            ToolFieldPresentation(
                key="aspect_ratio",
                label="Aspect Ratio",
                editable=True,
                options=SUPPORTED_IMAGE_ASPECT_RATIOS,
                secondary=True,
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
async def generate_image(
    ctx: RunContext[RuntimeDeps],
    prompt: Annotated[str, Field(description="Detailed prompt for one new image.")],
    model_provider: Annotated[
        NativeImageProvider,
        Field(
            description=(
                "Image provider to use. Available providers are "
                f"{_REGISTERED_NATIVE_IMAGE_PROVIDER_LIST}."
            ),
        ),
    ],
    aspect_ratio: Annotated[
        ImageAspectRatio | None,
        Field(
            description=(
                "Optional output aspect ratio. OpenAI supports 1:1, 2:3, and 3:2; Google "
                "supports every listed value. Omit to let the provider choose."
            )
        ),
    ] = None,
    model: Annotated[
        str | None,
        Field(
            description=(
                "Optional helper model id for model_provider. Omit to use the provider's "
                "current native-image default."
            )
        ),
    ] = None,
) -> GenerateImageOutput:
    """Generate one image and persist it as a workspace File."""
    normalized_prompt = prompt.strip()
    if not normalized_prompt:
        raise ModelRetry("generate_image requires a non-empty prompt.")

    model_spec = resolve_image_generation_model(model_provider=model_provider, model=model)
    image = await run_native_image_generation(
        prompt=normalized_prompt,
        aspect_ratio=aspect_ratio,
        model_spec=model_spec,
    )
    try:
        stored = await write_generated_image(
            ctx.deps.db,
            workspace=ctx.deps.workspace,
            agent=ctx.deps.agent,
            prompt=normalized_prompt,
            content=image.data,
            media_type=image.media_type,
        )
    except AppValidationError as exc:
        raise ModelRetry(exc.message) from exc

    image_model = (
        DEFAULT_OPENAI_IMAGE_MODEL if model_spec.provider == PROVIDER_OPENAI else model_spec.model
    )
    return GenerateImageOutput(
        prompt=normalized_prompt,
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
        image_model=image_model,
    )


def resolve_image_generation_model(
    *,
    model_provider: str,
    model: str | None = None,
) -> ResolvedModel:
    """Resolve a provider-supported native-image helper model."""
    requested_provider = model_provider.strip().lower()
    requested_model = normalize_optional_text(model)
    return _native_model_spec(
        provider=requested_provider,
        model=requested_model or _default_model_for_provider(requested_provider),
    )


async def run_native_image_generation(
    *,
    prompt: str,
    aspect_ratio: ImageAspectRatio | None,
    model_spec: ResolvedModel,
) -> BinaryImage:
    """Run the short-lived native helper and return its single image."""
    if (
        model_spec.provider == PROVIDER_OPENAI
        and aspect_ratio is not None
        and aspect_ratio not in OPENAI_IMAGE_ASPECT_RATIOS
    ):
        raise ModelRetry(
            "OpenAI image generation supports aspect ratios 1:1, 2:3, and 3:2. "
            "Choose one of those values, omit aspect_ratio, or use Google."
        )
    capability = ImageGeneration(
        native=True,
        local=False,
        action="generate",
        moderation="auto",
        aspect_ratio=aspect_ratio,
        image_model=(
            DEFAULT_OPENAI_IMAGE_MODEL if model_spec.provider == PROVIDER_OPENAI else None
        ),
    )
    helper = PydanticAgent(
        build_model(model_spec),
        name=f"praxis_native_image_generation_{model_spec.provider}",
        instructions=IMAGE_GENERATION_HELPER_INSTRUCTIONS,
        output_type=str,
        capabilities=[capability],
    )
    result = await helper.run(
        f"Generate exactly one new image from this prompt:\n\n{prompt}",
        usage_limits=UsageLimits(request_limit=model_spec.max_steps),
    )
    messages = result.all_messages()
    images = [
        image
        for message in messages
        if isinstance(message, ModelResponse)
        for image in message.images
    ]
    if len(images) == 1:
        return images[0]
    if len(images) > 1:
        raise ModelRetry(
            "The image provider returned multiple images, so none were saved. Try again."
        )
    if _was_content_policy_refusal(messages):
        raise ModelRetry(
            "The image provider declined this prompt under its content policy. "
            "Revise the prompt and try again."
        )
    raise ModelRetry(
        "The image provider completed without returning an image. Try again or choose another provider."
    )


def _was_content_policy_refusal(messages: list[ModelMessage]) -> bool:
    for message in messages:
        if not isinstance(message, ModelResponse):
            continue
        if message.finish_reason == "content_filter":
            return True
        details = message.provider_details or {}
        if details.get("refusal") or details.get("block_reason"):
            return True
    return False


def _native_model_spec(*, provider: str, model: str) -> ResolvedModel:
    normalized_provider = provider.strip().lower()
    normalized_model = model.strip()
    _require_configured_provider(normalized_provider)

    if normalized_provider == PROVIDER_GOOGLE:
        if normalized_model != DEFAULT_NATIVE_IMAGE_MODELS[PROVIDER_GOOGLE]:
            raise ModelRetry(
                "Google generate_image currently supports gemini-3.1-flash-image. "
                "Omit model to use it."
            )
        settings_map: dict[str, object] = {}
    else:
        try:
            info = get_model(normalized_provider, normalized_model)
        except ModelConfigurationError as exc:
            raise ModelRetry(
                "Unknown OpenAI generate_image helper model. Choose a model from the OpenAI "
                "catalog or omit model."
            ) from exc
        if info.deprecated:
            raise ModelRetry(f"Model '{normalized_provider}:{normalized_model}' is deprecated.")
        settings_map = dict(info.default_settings)

    return ResolvedModel(
        provider=normalized_provider,
        model=normalized_model,
        settings=settings_map,
        max_steps=settings.NATIVE_IMAGE_GENERATION_MAX_STEPS,
    )


def _default_model_for_provider(provider: str) -> str:
    normalized_provider = provider.strip().lower()
    _require_configured_provider(normalized_provider)
    model = DEFAULT_NATIVE_IMAGE_MODELS.get(normalized_provider)
    if model is None:
        raise ModelRetry(
            f"Provider '{normalized_provider}' does not support native generate_image."
        )
    return model


def _require_configured_provider(provider: str) -> None:
    configured = configured_native_image_providers()
    if provider in configured:
        return
    if not configured:
        raise ModelRetry("No native generate_image providers are configured.")
    raise ModelRetry(
        f"Provider '{provider}' is not configured for native generate_image. "
        f"Available configured providers: {', '.join(configured)}."
    )
