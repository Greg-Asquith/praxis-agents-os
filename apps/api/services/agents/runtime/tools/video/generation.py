# apps/api/services/agents/runtime/tools/video/generation.py

"""The steps every video generation and editing tool takes around its one provider call.

The call's record is committed before the provider call and again once the
provider's ID is known, so a resumed tool call finds it and never pays twice.
"""

from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.exceptions import ToolFailed

from core.settings import settings
from models.media_generation import MediaGeneration
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.video.utils import usage_event
from services.ai_usage.domain import PURPOSE_VIDEO_GENERATION
from services.ai_usage.pricing import find_price
from services.ai_usage.record_durable import record_ai_usage_durable
from services.media.catalogue import (
    MediaModel,
    MediaModelRoute,
    MediaTask,
    available_media_models,
    available_route,
    default_media_model,
    media_catalogue,
)
from services.media.generation import GeneratedVideo, VideoGenerationError, video_backend
from services.media.media_generations import find_media_generation, settle_media_generation
from utils.validation import normalize_optional_text

# A 4 second 4K clip took about two minutes, so a 15 second one can take several.
GENERATION_WAIT_SECONDS = 900
TOOL_TIMEOUT_SECONDS = GENERATION_WAIT_SECONDS + 120
MAX_PROMPT_CHARS = 4000
_ACTIONS = {
    "text_to_video": "generate video",
    "image_to_video": "generate video from images",
    "reference_to_video": "generate video from reference clips",
    "edit_video": "edit video",
}
HOW_TO_CHECK = (
    "Generated clips can miss parts of the prompt. Check this one with ask_video before "
    "reporting it as done, and say what you checked."
)


def resolve_media_model(model: str | None, task: MediaTask) -> tuple[MediaModel, MediaModelRoute]:
    """Returns the named catalogue model, or the default, with the route that serves it."""
    requested = normalize_optional_text(model)
    choices = ", ".join(entry.id for entry in available_media_models(task)) or "none"
    entry = default_media_model(task) if requested is None else media_catalogue().get(requested)
    if entry is None or task not in entry.tasks:
        raise ModelRetry(
            "No video models are set up on this deployment."
            if requested is None
            else f"{requested} can't {_ACTIONS.get(task, task)}. Choose one of: {choices}."
        )
    route = available_route(entry, task)
    if route is None:
        raise ModelRetry(
            f"{entry.label} isn't set up on this deployment. Choose one of: {choices}."
        )
    return entry, route


async def own_record(ctx: RunContext[RuntimeDeps], tool_name: str) -> MediaGeneration | None:
    """Returns the record this tool call already wrote, if any."""
    if not ctx.tool_call_id:
        raise ToolFailed(f"{tool_name} needs a tool call ID to record its paid call.")
    return await find_media_generation(
        ctx.deps.db,
        workspace_id=ctx.deps.workspace.id,
        run_id=ctx.deps.run.id,
        tool_call_id=ctx.tool_call_id,
    )


async def start_generation(
    ctx: RunContext[RuntimeDeps],
    *,
    task: MediaTask,
    entry: MediaModel,
    route: MediaModelRoute,
    send: Callable[[], Awaitable[str]],
) -> MediaGeneration:
    """Commits the record, sends the one paid request, then commits the provider's ID."""
    db = ctx.deps.db
    record = MediaGeneration(
        workspace_id=ctx.deps.workspace.id,
        run_id=ctx.deps.run.id,
        tool_call_id=ctx.tool_call_id,
        task=task,
        media_model=entry.id,
        route=route.route,
        provider_model=route.provider_model(task),
        status="requested",
    )
    db.add(record)
    await db.commit()
    try:
        external_id = await send()
    except VideoGenerationError as exc:
        await settle_media_generation(db, record, "failed", error=exc.message)
        raise agent_error(exc) from exc
    await settle_media_generation(db, record, "running", external_id=external_id)
    return record


async def wait_for_clip(ctx: RunContext[RuntimeDeps], record: MediaGeneration) -> GeneratedVideo:
    """Polls the provider for the clip and meters the call, billed or not."""
    if not record.external_id:
        # The worker stopped between the record and Google's answer; whether it was sent is unknown.
        await settle_media_generation(
            ctx.deps.db, record, "failed", error="The worker stopped before Google answered."
        )
        raise ToolFailed("The video request may not have reached Google. Try again.")
    try:
        video = await video_backend(record.route).wait(
            record.provider_model,
            record.external_id,
            timeout_seconds=GENERATION_WAIT_SECONDS,
            max_bytes=min(settings.MAX_FILE_SIZE_VIDEO, settings.MAX_FILE_SIZE_AGENT_FILE),
        )
    except VideoGenerationError as exc:
        await settle_media_generation(ctx.deps.db, record, "failed", error=exc.message)
        await _record_usage(ctx, record, None)
        raise agent_error(exc) from exc
    await _record_usage(ctx, record, video)
    return video


async def _record_usage(
    ctx: RunContext[RuntimeDeps], record: MediaGeneration, video: GeneratedVideo | None
) -> None:
    """Meters the call; a failed clip may still be billed, so its tokens are unknown."""
    event = usage_event(
        ctx, provider=record.route, model=record.provider_model, purpose=PURPOSE_VIDEO_GENERATION
    )
    await record_ai_usage_durable(
        replace(
            event,
            details={"media_model": record.media_model, "media_generation_id": str(record.id)},
            requests=1,
            unmeasured_requests=1 if video is None else 0,
            input_tokens=video.input_tokens if video else 0,
            output_tokens=video.output_tokens if video else 0,
        )
    )


def agent_error(exc: VideoGenerationError) -> Exception:
    """A refusal the agent can fix by rewording retries; anything else fails the call."""
    return ModelRetry(exc.message) if exc.refused else ToolFailed(exc.message)


def clip_cost(record: MediaGeneration, video: GeneratedVideo) -> str | None:
    """Returns the call's cost in US dollars from the tokens the provider reported."""
    price = find_price(record.route, record.provider_model, datetime.now(UTC).date())
    if price is None:
        return None
    cost = (
        Decimal(video.input_tokens) * price.input_usd_per_mtok
        + Decimal(video.output_tokens) * price.output_usd_per_mtok
    ) / Decimal(1_000_000)
    return f"{cost:.2f}"
