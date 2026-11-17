# apps/api/services/agents/runtime/tools/video/generate_video.py

"""Generates a video clip from a prompt with a catalogue video model and saves it as a File.

Each call is paid, so its record is committed before the provider call and again
once the provider's ID is known. A call that finds its own record saved returns
that File; one that finds it running waits on the same clip instead of paying twice.
"""

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.exceptions import ToolFailed

from core.exceptions.general import AppValidationError, ConflictError
from core.settings import settings
from models.files import File, FileRevision
from models.media_generation import MediaGeneration
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.entity_references.domain import FileReference
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_INTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_NONE,
    TOOL_POLICY_APPROVAL,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.agents.runtime.tools.files.utils import revision_source_ref
from services.agents.runtime.tools.registry import runtime_tool
from services.agents.runtime.tools.video.utils import progress, usage_event
from services.agents.runtime.untrusted import UntrustedContent, UntrustedNode
from services.ai_usage.domain import PURPOSE_VIDEO_GENERATION
from services.ai_usage.pricing import find_price
from services.ai_usage.record_durable import record_ai_usage_durable
from services.documents.outputs import OutputFolderResolver, save_new_file
from services.files.domain import GenerationProvenance
from services.media.catalogue import (
    PROCESSED_IN,
    MediaModel,
    MediaModelRoute,
    available_media_models,
    available_route,
    default_media_model,
    media_catalogue,
)
from services.media.generation import (
    GeneratedVideo,
    VideoGenerationError,
    VideoGenerationRequest,
    video_backend,
)
from services.media.media_generations import (
    find_media_generation,
    settle_media_generation,
)
from utils.validation import normalize_optional_text

TASK = "text_to_video"
DEFAULT_ASPECT_RATIO = "9:16"
DEFAULT_RESOLUTION = "720p"
DEFAULT_DURATION_SECONDS = 8
MAX_PROMPT_CHARS = 4000
# A 4 second 4K clip took about two minutes, so a 15 second one can take several.
GENERATION_WAIT_SECONDS = 900
TOOL_TIMEOUT_SECONDS = GENERATION_WAIT_SECONDS + 120
HOW_TO_CHECK = (
    "Generated clips can miss parts of the prompt. Check this one with ask_video before "
    "reporting it as done, and say what you checked."
)

AspectRatio = Literal["9:16", "16:9"]
Resolution = Literal["720p", "1080p", "4k"]


def _model_labels() -> dict[str, str]:
    labels = {}
    for model in available_media_models(TASK):
        if route := available_route(model, TASK):
            prices = [route.price_per_second(item) for item in model.limits.resolutions]
            low, high = min(prices, default=route.price(TASK)), max(prices, default=0)
            price = f"${low:.2f} to ${high:.2f} a second" if high > low else f"${low:.2f} a second"
            labels[model.id] = f"{model.label} · {price} · {PROCESSED_IN[model.processing]}"
    return labels


_MODEL_LABELS = _model_labels()


def _display_args(_deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Shows the model and settings that will run when the agent leaves them out."""
    default = default_media_model(TASK)
    return {
        "model": default.id if default is not None else None,
        "aspect_ratio": DEFAULT_ASPECT_RATIO,
        "resolution": DEFAULT_RESOLUTION,
        "duration_seconds": DEFAULT_DURATION_SECONDS,
        **{key: value for key, value in args.items() if value is not None},
    }


class GenerateVideoOutput(BaseModel):
    """Model-visible metadata for one generated workspace video."""

    name: str
    file_id: str
    revision_id: str
    reference: FileReference
    media_type: str
    size_bytes: int
    model: str
    aspect_ratio: str
    resolution: str
    duration_seconds: int
    cost_usd: str | None
    model_notes: UntrustedNode | None
    how_to_check: str


@runtime_tool(
    name="generate_video",
    provider="native",
    label="Generate Video",
    code_eligible=False,
    description=(
        "Generate one new video clip of 3 to 15 seconds, with sound, from a prompt and save it to "
        "workspace Files. Use it for hook shots, B-roll, product shots, and transitions. Each "
        "call costs money: about $0.07 a second at 720p, more at 1080p and 4K. Describe the "
        "shot, camera movement, lighting, and sound. It takes one to several minutes. The UI "
        "plays the saved clip; don't link to it."
    ),
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_INTERNAL,
    supports_approval=True,
    supports_auto=True,
    default_policy=TOOL_POLICY_APPROVAL,
    egress=TOOL_EGRESS_NONE,
    takes_ctx=True,
    timeout=TOOL_TIMEOUT_SECONDS,
    output_model=GenerateVideoOutput,
    availability_check=lambda: bool(available_media_models(TASK)),
    approval_display_args=_display_args,
    presentation=ToolPresentation(
        icon="video",
        running_label="Generating a Video",
        completed_label="Generated {name}",
        failed_label="Couldn't Generate the Video",
        approval_title="Generate a Video",
        approval_prompt="The agent wants to generate a video from this prompt: {prompt}",
        approve_label="Approve & Generate",
        arg_fields=(
            ToolFieldPresentation(
                key="prompt",
                label="Prompt",
                format="multiline",
                editable=True,
                placeholder="Describe the shot to generate",
            ),
            ToolFieldPresentation(
                key="model",
                label="Video Model",
                editable=True,
                options=tuple(_MODEL_LABELS),
                option_labels=_MODEL_LABELS,
            ),
            ToolFieldPresentation(
                key="aspect_ratio",
                label="Shape",
                editable=True,
                options=("9:16", "16:9"),
                option_labels={"9:16": "Vertical (9:16)", "16:9": "Landscape (16:9)"},
            ),
            ToolFieldPresentation(
                key="duration_seconds",
                label="Seconds",
                editable=True,
                format="number",
            ),
            ToolFieldPresentation(
                key="resolution",
                label="Resolution",
                editable=True,
                options=("720p", "1080p", "4k"),
                option_labels={"720p": "720p", "1080p": "1080p", "4k": "4K"},
                secondary=True,
            ),
            ToolFieldPresentation(key="name", label="Name", secondary=True),
            ToolFieldPresentation(key="folder", label="Folder", secondary=True),
        ),
    ),
)
async def generate_video(
    ctx: RunContext[RuntimeDeps],
    prompt: Annotated[
        str, Field(description="The shot to generate: subject, action, camera, light, and sound.")
    ],
    aspect_ratio: Annotated[
        AspectRatio | None,
        Field(description="9:16 for Reels, Shorts, and TikTok (the default), or 16:9."),
    ] = None,
    duration_seconds: Annotated[
        int | None,
        Field(ge=3, le=15, description="Length from 3 to 15 seconds. Default: 8."),
    ] = None,
    resolution: Annotated[
        Resolution | None,
        Field(description="720p (the default), 1080p, or 4k. Higher costs more."),
    ] = None,
    model: Annotated[
        Annotated[str, Field(json_schema_extra={"enum": list(_MODEL_LABELS)})] | None,
        Field(
            description="Optional video model. Omit it unless the person named one. Available: "
            + ("; ".join(f"{m.id} ({m.strengths})" for m in available_media_models(TASK)) or "none")
        ),
    ] = None,
    name: Annotated[
        str | None, Field(description="Optional File name. Omit to name it from the prompt.")
    ] = None,
    folder: Annotated[
        str | None,
        Field(description="Optional folder name, created if needed. Omit for this chat's folder."),
    ] = None,
) -> dict[str, object]:
    """Generates one clip, or returns the one this call already paid for."""
    prompt = prompt.strip()
    if not prompt:
        raise ModelRetry("generate_video requires a non-empty prompt.")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ModelRetry(f"prompt must be at most {MAX_PROMPT_CHARS} characters.")
    entry, route = _resolve_model(model)
    request = VideoGenerationRequest(
        provider_model=route.provider_model(TASK),
        prompt=prompt,
        aspect_ratio=aspect_ratio or DEFAULT_ASPECT_RATIO,
        resolution=resolution or DEFAULT_RESOLUTION,
        duration_seconds=duration_seconds or DEFAULT_DURATION_SECONDS,
    )
    _check_limits(entry, request)

    record = await _own_record(ctx)
    if record is not None and record.status == "saved":
        return await _saved_output(ctx, record)
    if record is not None and record.status == "failed":
        raise ToolFailed(record.error or "The video couldn't be generated.")
    if record is None:
        record = await _start(ctx, entry, route, request)

    await progress(ctx)("Generating Video")
    video = await _wait(ctx, record)
    return await _save(
        ctx,
        record,
        entry,
        request,
        video,
        name=normalize_optional_text(name),
        folder=normalize_optional_text(folder),
    )


def _resolve_model(model: str | None) -> tuple[MediaModel, MediaModelRoute]:
    requested = normalize_optional_text(model)
    choices = ", ".join(entry.id for entry in available_media_models(TASK)) or "none"
    entry = default_media_model(TASK) if requested is None else media_catalogue().get(requested)
    if entry is None or TASK not in entry.tasks:
        raise ModelRetry(
            "No video models are set up on this deployment."
            if requested is None
            else f"{requested} can't generate video. Choose one of: {choices}."
        )
    route = available_route(entry, TASK)
    if route is None:
        raise ModelRetry(
            f"{entry.label} isn't set up on this deployment. Choose one of: {choices}."
        )
    return entry, route


def _check_limits(entry: MediaModel, request: VideoGenerationRequest) -> None:
    limits = entry.limits
    if limits.aspect_ratios and request.aspect_ratio not in limits.aspect_ratios:
        raise ModelRetry(f"{entry.label} makes {', '.join(limits.aspect_ratios)} clips.")
    if limits.resolutions and request.resolution not in limits.resolutions:
        raise ModelRetry(f"{entry.label} makes {', '.join(limits.resolutions)} clips.")
    durations = limits.durations_seconds
    if durations and request.duration_seconds not in durations:
        raise ModelRetry(
            f"{entry.label} makes clips of {min(durations)} to {max(durations)} seconds."
        )


async def _own_record(ctx: RunContext[RuntimeDeps]) -> MediaGeneration | None:
    if not ctx.tool_call_id:
        raise ToolFailed("generate_video needs a tool call ID to record its paid call.")
    return await find_media_generation(
        ctx.deps.db,
        workspace_id=ctx.deps.workspace.id,
        run_id=ctx.deps.run.id,
        tool_call_id=ctx.tool_call_id,
    )


async def _start(
    ctx: RunContext[RuntimeDeps],
    entry: MediaModel,
    route: MediaModelRoute,
    request: VideoGenerationRequest,
) -> MediaGeneration:
    """Commits the record, sends the one paid request, then commits the provider's ID."""
    db = ctx.deps.db
    record = MediaGeneration(
        workspace_id=ctx.deps.workspace.id,
        run_id=ctx.deps.run.id,
        tool_call_id=ctx.tool_call_id,
        task=TASK,
        media_model=entry.id,
        route=route.route,
        provider_model=request.provider_model,
        status="requested",
    )
    db.add(record)
    await db.commit()
    try:
        external_id = await video_backend(route.route).start(request)
    except VideoGenerationError as exc:
        await settle_media_generation(db, record, "failed", error=exc.message)
        raise _agent_error(exc) from exc
    await settle_media_generation(db, record, "running", external_id=external_id)
    return record


async def _wait(ctx: RunContext[RuntimeDeps], record: MediaGeneration) -> GeneratedVideo:
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
        raise _agent_error(exc) from exc
    await _record_usage(ctx, record, video)
    return video


async def _save(
    ctx: RunContext[RuntimeDeps],
    record: MediaGeneration,
    entry: MediaModel,
    request: VideoGenerationRequest,
    video: GeneratedVideo,
    *,
    name: str | None,
    folder: str | None,
) -> dict[str, object]:
    deps = ctx.deps
    await progress(ctx)("Saving Video")
    provenance = GenerationProvenance(
        route=record.route,
        media_model=entry.id,
        provider_model=record.provider_model,
        external_id=record.external_id,
        task=TASK,
        prompt_digest=f"sha256:{hashlib.sha256(request.prompt.encode()).hexdigest()}",
        aspect_ratio=request.aspect_ratio,
        resolution=request.resolution,
        duration_seconds=request.duration_seconds,
    )
    try:
        stored = await save_new_file(
            deps,
            name=_file_name(name or request.prompt),
            content=video.content,
            media_type=video.media_type,
            folder=OutputFolderResolver(folder),
            details={"source": "video_generation", "media_generation_id": str(record.id)},
        )
    except (AppValidationError, ConflictError) as exc:
        await deps.db.rollback()
        await settle_media_generation(deps.db, record, "failed", error=exc.message)
        raise ToolFailed(f"The clip was generated but couldn't be saved: {exc.message}") from exc
    revision = await deps.db.get(FileRevision, stored.revision_id)
    if revision is None:
        raise RuntimeError("The saved revision is missing")
    revision.generation = provenance.model_dump(mode="json", exclude_none=True)
    await settle_media_generation(deps.db, record, "saved", revision=revision)
    file = await deps.db.get(File, revision.file_id)
    if file is None:
        raise RuntimeError("The saved File is missing")
    notes = video.thought_summary
    return {
        **_output(file, revision, provenance),
        "cost_usd": _cost(record, video),
        "model_notes": UntrustedContent(
            source_kind="video_generation_notes",
            source_ref=revision_source_ref(file, revision),
            content=notes,
        )
        if notes
        else None,
    }


async def _saved_output(ctx: RunContext[RuntimeDeps], record: MediaGeneration) -> dict[str, object]:
    """Returns the File this call already saved, without asking the provider again."""
    revision = await ctx.deps.db.get(FileRevision, record.revision_id)
    file = await ctx.deps.db.get(File, record.file_id) if record.file_id else None
    if revision is None or file is None or file.deleted or revision.generation is None:
        raise ToolFailed("This call's video was saved, then deleted.")
    provenance = GenerationProvenance.model_validate(revision.generation)
    return {**_output(file, revision, provenance), "cost_usd": None, "model_notes": None}


def _output(
    file: File, revision: FileRevision, provenance: GenerationProvenance
) -> dict[str, object]:
    return {
        "name": file.name,
        "file_id": str(file.id),
        "revision_id": str(revision.id),
        "reference": FileReference(
            entity_id=file.id,
            label=file.name,
            description=f"Generated video · {provenance.duration_seconds} s",
        ),
        "media_type": revision.content_type,
        "size_bytes": revision.size_bytes,
        "model": provenance.media_model,
        "aspect_ratio": provenance.aspect_ratio,
        "resolution": provenance.resolution,
        "duration_seconds": provenance.duration_seconds,
        "how_to_check": HOW_TO_CHECK,
    }


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


def _agent_error(exc: VideoGenerationError) -> Exception:
    return ModelRetry(exc.message) if exc.refused else ToolFailed(exc.message)


def _file_name(source: str) -> str:
    stem = "".join(char if char.isalnum() else "-" for char in source.lower())
    stem = "-".join(part for part in stem.split("-") if part)[:48].rstrip("-")
    return f"{stem or 'generated-video'}.mp4"


def _cost(record: MediaGeneration, video: GeneratedVideo) -> str | None:
    price = find_price(record.route, record.provider_model, datetime.now(UTC).date())
    if price is None:
        return None
    cost = (
        Decimal(video.input_tokens) * price.input_usd_per_mtok
        + Decimal(video.output_tokens) * price.output_usd_per_mtok
    ) / Decimal(1_000_000)
    return f"{cost:.2f}"
