# apps/api/services/agents/runtime/tools/video/generate_video.py

"""Generates a video clip from a prompt with a catalogue video model and saves it as a File.

The prompt can come with reference images or short reference clips from workspace
Files. A call that finds its own paid record saved returns that File; one that finds
it running waits on the same clip instead of paying twice.
"""

import hashlib
from dataclasses import replace
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.exceptions import ToolFailed
from sqlalchemy import select

from core.exceptions.general import AppValidationError, ConflictError
from core.settings import settings
from models.files import File, FileRevision
from models.media_generation import MediaGeneration
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.entity_references.domain import FileReference, internal_entity_id
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_INTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_NONE,
    TOOL_POLICY_APPROVAL,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.agents.runtime.tools.files.utils import revision_source_ref
from services.agents.runtime.tools.media_inputs import VIDEO_MEDIA_TYPES, record_media_read_audit
from services.agents.runtime.tools.registry import runtime_tool
from services.agents.runtime.tools.video.generation import (
    HOW_TO_CHECK,
    MAX_PROMPT_CHARS,
    TOOL_TIMEOUT_SECONDS,
    clip_cost,
    own_record,
    resolve_media_model,
    start_generation,
    wait_for_clip,
)
from services.agents.runtime.tools.video.utils import (
    probed_video,
    progress,
    workspace_image,
    workspace_video,
)
from services.agents.runtime.untrusted import UntrustedContent, UntrustedNode
from services.documents.outputs import OutputFolderResolver, save_new_file
from services.files.contract import FileCategory
from services.files.domain import GenerationProvenance
from services.files.utils import file_revision_ref, revision_video_metadata
from services.media.catalogue import (
    PROCESSED_IN,
    MediaModel,
    MediaTask,
    available_media_models,
    available_route,
    default_media_model,
)
from services.media.generation import (
    GeneratedVideo,
    VideoGenerationRequest,
    VideoReference,
    video_backend,
)
from services.media.media_generations import settle_media_generation
from services.storage.factory import get_storage_provider
from utils.validation import normalize_optional_text

TASK = "text_to_video"
TOOL_NAME = "generate_video"
REFERENCE_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
DEFAULT_ASPECT_RATIO = "9:16"
DEFAULT_RESOLUTION = "720p"
DEFAULT_DURATION_SECONDS = 8

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


def _task(images: object, clips: object) -> MediaTask:
    return "reference_to_video" if clips else "image_to_video" if images else TASK


async def _display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Shows the model and settings that will run when the agent leaves them out, with each
    model's price a second by resolution so the card's estimate follows the approver's edits.
    Reference clips are billed as input, so their measured length and price come too."""
    task = _task(args.get("image_file_ids"), args.get("reference_video_file_ids"))
    default = default_media_model(task)
    routes = {
        model.id: (model, route)
        for model in available_media_models(task)
        if (route := available_route(model, task))
    }
    display = {
        "model": default.id if default is not None else None,
        "aspect_ratio": DEFAULT_ASPECT_RATIO,
        "resolution": DEFAULT_RESOLUTION,
        "duration_seconds": DEFAULT_DURATION_SECONDS,
        **{key: value for key, value in args.items() if value is not None},
        "_prices": {
            model_id: {item: str(route.price_per_second(item)) for item in model.limits.resolutions}
            for model_id, (model, route) in routes.items()
        },
    }
    seconds = await _reference_seconds(deps, args.get("reference_video_file_ids"))
    if seconds:
        display["_reference_seconds"] = str(seconds)
        display["_input_prices"] = {
            model_id: str(route.usd_per_input_second)
            for model_id, (_model, route) in routes.items()
            if route.usd_per_input_second is not None
        }
    return display


async def _reference_seconds(deps: RuntimeDeps, references: object) -> Decimal:
    """Returns the measured length of the reference clips the approver is shown."""
    if not isinstance(references, list):
        return Decimal(0)
    ids = []
    for reference in references:
        try:
            ids.append(
                UUID(str(reference["entity_id"] if isinstance(reference, dict) else reference))
            )
        except (KeyError, ValueError):
            continue
    if not ids:
        return Decimal(0)
    revisions = await deps.db.scalars(
        select(FileRevision)
        .join(File, File.current_revision_id == FileRevision.id)
        .where(
            File.id.in_(ids),
            File.category == FileCategory.VIDEO.value,
            FileRevision.workspace_id == deps.workspace.id,
        )
    )
    measured = [revision_video_metadata(revision) for revision in revisions]
    return sum(
        (Decimal(item.duration_ms) / 1000 for item in measured if item is not None), Decimal(0)
    )


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
    name=TOOL_NAME,
    provider="native",
    label="Generate Video",
    code_eligible=False,
    description=(
        "Generate one new video clip of 3 to 15 seconds, with sound, from a prompt and save it to "
        "workspace Files. Use it for hook shots, B-roll, product shots, and transitions. Each "
        "call costs money: about $0.07 a second at 720p, more at 1080p and 4K. Describe the "
        "shot, camera movement, lighting, and sound. To keep a product, person, or place "
        "looking like the person's own, pass workspace images as image_file_ids, clips of 3 "
        "seconds or less as reference_video_file_ids, or both, and say in the prompt how each is used, "
        "such as the opening frame or the product to show. It takes one to several minutes. "
        "The UI plays the saved clip; don't link to it."
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
                key="image_file_ids",
                label="Reference Images",
                format="entity_list",
                entity_kind="file",
            ),
            ToolFieldPresentation(
                key="reference_video_file_ids",
                label="Reference Clips",
                format="entity_list",
                entity_kind="file",
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
    image_file_ids: Annotated[
        list[FileReference] | None,
        Field(
            max_length=6,
            description=(
                "Optional workspace PNG, JPEG, or WebP images to draw on: the opening frame, or "
                "a product, person, or place to keep. Up to six."
            ),
        ),
    ] = None,
    reference_video_file_ids: Annotated[
        list[FileReference] | None,
        Field(
            max_length=3,
            description=(
                "Optional workspace clips of 3 seconds or less whose subject, motion, or style "
                "to follow. Up to three for a clip of 10 seconds or less, one for a longer clip. "
                "Their sound is ignored."
            ),
        ),
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
    task = _task(image_file_ids, reference_video_file_ids)
    entry, route = resolve_media_model(model, task)
    request = VideoGenerationRequest(
        provider_model=route.provider_model(TASK),
        prompt=prompt,
        aspect_ratio=aspect_ratio or DEFAULT_ASPECT_RATIO,
        resolution=resolution or DEFAULT_RESOLUTION,
        duration_seconds=duration_seconds or DEFAULT_DURATION_SECONDS,
    )
    _check_limits(entry, request)

    record = await own_record(ctx, TOOL_NAME)
    if record is not None and record.status == "saved":
        return await _saved_output(ctx, record)
    if record is not None and record.status == "failed":
        raise ToolFailed(record.error or "The video couldn't be generated.")
    references = [
        *await _reference_images(ctx, entry, image_file_ids or []),
        *await _reference_clips(ctx, entry, reference_video_file_ids or [], request),
    ]
    if record is None:
        request = replace(request, references=await _read_references(ctx, entry, references))
        record = await start_generation(
            ctx,
            task=task,
            entry=entry,
            route=route,
            send=lambda: video_backend(route.route).start(request),
        )

    await progress(ctx)("Generating Video")
    video = await wait_for_clip(ctx, record)
    return await _save(
        ctx,
        record,
        entry,
        request,
        video,
        references=references,
        name=normalize_optional_text(name),
        folder=normalize_optional_text(folder),
    )


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


def _unique(references: list[FileReference]) -> list[FileReference]:
    return list({internal_entity_id(item): item for item in references}.values())


async def _reference_images(
    ctx: RunContext[RuntimeDeps], entry: MediaModel, references: list[FileReference]
) -> list[tuple[File, FileRevision]]:
    """Returns the workspace's own images to send, refusing more than the model takes."""
    references = _unique(references)
    limit = entry.limits.max_input_images
    if limit is not None and len(references) > limit:
        raise ModelRetry(f"{entry.label} takes up to {limit} reference images.")
    images = [await workspace_image(ctx, item, tool_name=TOOL_NAME) for item in references]
    for file, revision in images:
        if revision.content_type.split(";", 1)[0].strip().lower() not in REFERENCE_IMAGE_TYPES:
            raise ModelRetry(f"{file.name} isn't a PNG, JPEG, or WebP image. Use one that is.")
    return images


async def _reference_clips(
    ctx: RunContext[RuntimeDeps],
    entry: MediaModel,
    references: list[FileReference],
    request: VideoGenerationRequest,
) -> list[tuple[File, FileRevision]]:
    """Returns the workspace's own short clips to send, within the model's reference limits."""
    references = _unique(references)
    if not references:
        return []
    limits = entry.limits
    # The count for the shortest output length that covers this clip.
    _, allowed = min(
        (
            (length, count)
            for length, count in limits.reference_clips_by_length.items()
            if request.duration_seconds <= length
        ),
        default=(0, 0),
    )
    if len(references) > allowed:
        raise ModelRetry(
            f"{entry.label} takes {allowed} reference clip{'' if allowed == 1 else 's'} for a "
            f"{request.duration_seconds} second clip. Pass fewer, or make a shorter clip."
        )
    clips = [await workspace_video(ctx, item, tool_name=TOOL_NAME) for item in references]
    longest = limits.max_reference_seconds
    for file, revision in clips:
        if revision.content_type.split(";", 1)[0].strip().lower() not in VIDEO_MEDIA_TYPES:
            raise ModelRetry(f"{file.name} isn't an MP4, MOV, or WebM video. Use one that is.")
        seconds = probed_video(revision).duration_ms / 1000
        if longest is not None and seconds > longest:
            raise ModelRetry(
                f"{file.name} is {seconds:.1f} seconds, and {entry.label} takes reference clips "
                f"of up to {longest}. Cut the moment to use with cut_video_clips, then pass the "
                "new clip."
            )
    return clips


async def _read_references(
    ctx: RunContext[RuntimeDeps], entry: MediaModel, references: list[tuple[File, FileRevision]]
) -> tuple[VideoReference, ...]:
    """Reads each reference to send inline, refusing a set too large for one request."""
    if sum(revision.size_bytes for _, revision in references) > settings.MAX_FILE_SIZE_VIDEO:
        raise ModelRetry("These references are too large to send together. Pass fewer or smaller.")
    storage = get_storage_provider()
    loaded = []
    for file, revision in references:
        await record_media_read_audit(
            ctx,
            file.id,
            revision.id,
            operation="video_generation_reference",
            tool_name=TOOL_NAME,
            details={"media_model": entry.id},
        )
        loaded.append(
            VideoReference(
                kind="image" if file.category == FileCategory.IMAGE.value else "video",
                content=await storage.get_object(file_revision_ref(revision)),
                media_type=revision.content_type.split(";", 1)[0].strip().lower(),
            )
        )
    return tuple(loaded)


async def _save(
    ctx: RunContext[RuntimeDeps],
    record: MediaGeneration,
    entry: MediaModel,
    request: VideoGenerationRequest,
    video: GeneratedVideo,
    *,
    references: list[tuple[File, FileRevision]],
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
        task=record.task,
        prompt_digest=f"sha256:{hashlib.sha256(request.prompt.encode()).hexdigest()}",
        reference_revision_ids=tuple(revision.id for _, revision in references) or None,
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
        "cost_usd": clip_cost(record, video),
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


def _file_name(source: str) -> str:
    stem = "".join(char if char.isalnum() else "-" for char in source.lower())
    stem = "-".join(part for part in stem.split("-") if part)[:48].rstrip("-")
    return f"{stem or 'generated-video'}.mp4"
