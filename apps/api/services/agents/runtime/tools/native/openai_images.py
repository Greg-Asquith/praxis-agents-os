# apps/api/services/agents/runtime/tools/native/openai_images.py

"""Direct OpenAI image requests with shared credentials, retries, and metering."""

import base64
import binascii
import logging
from collections.abc import Sequence
from typing import Literal

from openai import APIError, AsyncOpenAI
from openai.types import ImagesResponse
from pydantic_ai import ModelRetry, ToolFailed
from pydantic_ai.messages import BinaryContent, BinaryImage
from pydantic_ai.usage import RunUsage

from core.settings import settings
from services.agents.models.utils import provider_api_key, retrying_http_client
from services.agents.runtime.context import RuntimeDeps
from services.ai_usage.domain import PURPOSE_IMAGE_GENERATION, AIUsageEventData
from services.ai_usage.run_metered_helper import run_metered_helper

logger = logging.getLogger(__name__)

_SIZES = {"1:1": "1024x1024", "2:3": "1024x1536", "3:2": "1536x1024"}


async def run_openai_image(
    *,
    deps: RuntimeDeps,
    prompt: str,
    model: str,
    action: str,
    aspect_ratio: str | None,
    input_media: Sequence[BinaryContent],
    output_format: Literal["png", "webp", "jpeg"],
) -> BinaryImage:
    """Send the supplied prompt directly and return exactly one image."""
    if action not in {"generate", "edit"}:
        raise ModelRetry("OpenAI supports image generation and editing only.")
    if (action == "edit" and len(input_media) != 1) or (action == "generate" and input_media):
        raise ModelRetry("OpenAI editing requires one source image; generation accepts none.")
    client = AsyncOpenAI(
        api_key=provider_api_key("openai"),
        base_url=settings.OPENAI_BASE_URL,
        http_client=retrying_http_client(),
        max_retries=0,
    )
    details: dict[str, str | int] = {
        "action": action,
        "image_model": model,
        "usage_source": "images_api",
    }

    async def call(usage: RunUsage) -> ImagesResponse:
        usage.requests = 1
        kwargs = {
            "model": model,
            "prompt": prompt,
            "n": 1,
            "size": _SIZES[aspect_ratio] if aspect_ratio is not None else "auto",
            "output_format": output_format,
        }
        if action == "edit":
            source = input_media[0]
            response = await client.images.edit(
                image=(
                    f"source.{source.media_type.split('/')[-1]}",
                    source.data,
                    source.media_type,
                ),
                **kwargs,
            )
        else:
            response = await client.images.generate(moderation="auto", **kwargs)
        for field in ("quality", "size"):
            value = getattr(response, field, None)
            if isinstance(value, str) and value:
                details[f"image_{field}"] = value.lower()
        if response.usage is not None:
            for field in ("input_tokens", "output_tokens"):
                value = getattr(response.usage, field, None)
                if type(value) is int and value >= 0:
                    setattr(usage, field, value)
            for direction in ("input", "output"):
                token_details = getattr(response.usage, f"{direction}_tokens_details", None)
                for modality in ("text", "image"):
                    value = getattr(token_details, f"{modality}_tokens", None)
                    if type(value) is int and value >= 0:
                        details[f"{direction}_{modality}_tokens"] = value
        return response

    try:
        response = await run_metered_helper(
            AIUsageEventData(
                workspace_id=deps.workspace.id,
                provider="openai",
                model=model,
                purpose=PURPOSE_IMAGE_GENERATION,
                agent_id=deps.agent.id,
                user_id=deps.user.id,
                run_id=deps.run.id,
                conversation_id=deps.conversation.id,
                details=details,
            ),
            call,
        )
    except APIError as exc:
        logger.warning(
            "OpenAI image request failed",
            extra={"model": model, "status_code": getattr(exc, "status_code", None)},
        )
        if exc.code in ("moderation_blocked", "content_policy_violation"):
            raise ModelRetry(
                "The image provider declined this prompt under its content policy. "
                "Revise the prompt and try again."
            ) from exc
        raise ToolFailed(
            "The image provider could not complete the request. Try again or choose another provider."
        ) from exc

    images = response.data or []
    if len(images) > 1:
        raise ModelRetry(
            "The image provider returned multiple images, so none were saved. Try again."
        )
    if not images or not images[0].b64_json:
        raise ModelRetry("The image provider completed without returning an image. Try again.")
    encoded = images[0].b64_json
    if len(encoded) > 4 * ((settings.MAX_FILE_SIZE_IMAGE + 2) // 3):
        raise ModelRetry("The generated image exceeds the file size limit.")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ModelRetry("The image provider returned invalid image data. Try again.") from exc
    if len(content) > settings.MAX_FILE_SIZE_IMAGE:
        raise ModelRetry("The generated image exceeds the file size limit.")
    return BinaryImage(data=content, media_type=f"image/{response.output_format or output_format}")
