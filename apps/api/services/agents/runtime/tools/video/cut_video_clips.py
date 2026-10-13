# apps/api/services/agents/runtime/tools/video/cut_video_clips.py

"""Cuts clips from workspace videos, joining ranges in order, and saves each as a new File."""

from collections.abc import Awaitable, Callable
from math import ceil
from pathlib import PurePath
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.exceptions import ToolFailed

from core.exceptions.general import AppValidationError
from core.settings import settings
from models.files import File, FileRevision
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.entity_references.domain import FileReference
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_INTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_POLICY_AUTO,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.agents.runtime.tools.registry import runtime_tool
from services.agents.runtime.tools.video.transcribe_video import TRANSCRIPTION_ALLOWANCE_SECONDS
from services.agents.runtime.tools.video.utils import (
    probed_video,
    progress,
    record_video_audit,
    video_transcript,
    workspace_video,
)
from services.files import create_conversation_file_references
from services.files.revision_actor import FileRevisionActor
from services.files.utils import format_duration
from services.media import discard_staged_outputs, save_media_output
from services.media.clips import (
    RENDER_CONCURRENCY,
    AspectRatio,
    ClipSource,
    PlannedClip,
    output_size,
    plan_clip,
    render_clips,
)
from services.media.domain import MAX_CUT_SEGMENTS, MediaOperationResult, MediaRendererError
from services.media.get_video_shot_cuts import get_video_shot_cuts
from services.media.run_media_operation import REQUEST_ALLOWANCE_SECONDS
from services.media.transcription_providers import transcription_provider
from services.storage.paths import safe_filename

MAX_CLIPS = 5
MAX_CLIP_NAME_CHARS = 120
RENDERER_CALL_SECONDS = settings.MEDIA_RENDERER_TIMEOUT_SECONDS + REQUEST_ALLOWANCE_SECONDS


class ClipSegmentArgument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: FileReference = Field(description="Workspace video this segment comes from.")
    start_ms: int | None = Field(
        default=None,
        ge=0,
        description="Start in milliseconds, such as a moment's start_ms. Omit for the start.",
    )
    end_ms: int | None = Field(
        default=None, gt=0, description="End in milliseconds. Omit for the end of the video."
    )


class ClipArgument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segments: list[ClipSegmentArgument] = Field(
        min_length=1,
        max_length=MAX_CUT_SEGMENTS,
        description=(
            "Ranges joined in order into one clip. Ranges and whole videos from several "
            "workspace videos can be mixed."
        ),
    )
    name: str | None = Field(
        default=None,
        max_length=MAX_CLIP_NAME_CHARS,
        description="Optional file name. Omit to name the clip from its video and times.",
    )
    snap: bool = Field(
        default=True,
        description=(
            "Move cuts to whole sentences and shot changes. Set false only to cut at the exact "
            "times given."
        ),
    )


def cut_video_clips_available() -> bool:
    return settings.media_renderer_available


@runtime_tool(
    name="cut_video_clips",
    provider="native",
    label="Cut Video Clips",
    code_eligible=False,
    description=(
        "Cut up to five clips from workspace videos and save each as a new video File. Each clip "
        "joins one or more segments in order; segments can come from different videos, as "
        "ranges or whole videos. Pass the start_ms and end_ms that find_video_moments returned "
        "rather than inventing times. aspect_ratio 9:16 suits Reels, Shorts, and TikTok; "
        "framing 'center' crops to fill the frame, 'fit' shows the whole frame over a blurred "
        "fill. One clip failing doesn't stop the others; the result reports each clip."
    ),
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_INTERNAL,
    default_policy=TOOL_POLICY_AUTO,
    supports_auto=True,
    supports_approval=True,
    takes_ctx=True,
    # A first cut on a video also transcribes it and measures its shots before rendering.
    timeout=RENDERER_CALL_SECONDS
    + TRANSCRIPTION_ALLOWANCE_SECONDS
    + RENDERER_CALL_SECONDS
    + ceil(MAX_CLIPS / RENDER_CONCURRENCY) * RENDERER_CALL_SECONDS,
    availability_check=cut_video_clips_available,
    presentation=ToolPresentation(
        icon="video",
        running_label="Cutting Video Clips",
        completed_label="Cut Video Clips",
        failed_label="Couldn't Cut Video Clips",
        approval_title="Cut Video Clips",
        approval_prompt="The agent wants to cut clips from workspace videos and save them.",
        approve_label="Approve & Cut",
        arg_fields=(
            ToolFieldPresentation(key="aspect_ratio", label="Aspect Ratio"),
            ToolFieldPresentation(key="framing", label="Framing", secondary=True),
        ),
        result_fields=(ToolFieldPresentation(key="saved", label="Clips", format="number"),),
    ),
)
async def cut_video_clips(
    ctx: RunContext[RuntimeDeps],
    clips: Annotated[
        list[ClipArgument],
        Field(min_length=1, max_length=MAX_CLIPS, description="The clips to cut, in order."),
    ],
    aspect_ratio: Annotated[
        AspectRatio,
        Field(description="Shape of every clip. 'original' keeps the first video's shape."),
    ] = "original",
    framing: Annotated[
        Literal["center", "fit"],
        Field(description="How a frame of another shape fits: crop to fill, or fit over a blur."),
    ] = "center",
) -> dict[str, object]:
    """Renders each clip from the caller's own videos and saves it next to its first video."""
    stage = progress(ctx)
    videos = await _workspace_videos(ctx, clips)
    sources = await _clip_sources(ctx, clips, videos, stage=stage)
    planned = []
    for index, clip in enumerate(clips, start=1):
        first = sources[clip.segments[0].file_id.entity_id]
        try:
            planned.append(
                plan_clip(
                    [
                        (sources[segment.file_id.entity_id], segment.start_ms, segment.end_ms)
                        for segment in clip.segments
                    ],
                    size=output_size(aspect_ratio, first.metadata),
                    fit=framing == "fit",
                    snap=clip.snap,
                )
            )
        except ValueError as exc:
            raise ModelRetry(f"Clip {index}: {exc}") from exc

    for file, revision in videos.values():
        await record_video_audit(
            ctx,
            file.id,
            revision.id,
            operation="video_clips",
            tool_name="cut_video_clips",
            details={"clips": len(planned)},
        )
    # The analysis and the record are kept even if every render fails.
    await ctx.deps.db.commit()

    await stage("Rendering Clips")
    rendered = await render_clips(ctx.deps.workspace.id, planned)
    await stage("Saving Clips")
    results = []
    for index, (clip, request, outcome) in enumerate(
        zip(clips, planned, rendered, strict=True), start=1
    ):
        first_file = videos[clip.segments[0].file_id.entity_id][0]
        name = _clip_name(clip, request, first_file)
        if isinstance(outcome, MediaRendererError):
            results.append(_failed(index, name, request, outcome.message))
            continue
        results.append(await _save_clip(ctx, index, name, request, outcome, first_file.folder_id))
    await ctx.deps.db.commit()
    for outcome in rendered:
        if isinstance(outcome, MediaOperationResult):
            await discard_staged_outputs(outcome.outputs)

    saved = sum(1 for result in results if result["status"] == "saved")
    if saved == 0:
        raise ToolFailed(
            "No clips were saved. "
            + " ".join(f"Clip {result['index']}: {result['error']}" for result in results)
        )
    return {"count": len(results), "saved": saved, "failed": len(results) - saved, "clips": results}


async def _workspace_videos(
    ctx: RunContext[RuntimeDeps], clips: list[ClipArgument]
) -> dict[UUID, tuple[File, FileRevision]]:
    videos: dict[UUID, tuple[File, FileRevision]] = {}
    for clip in clips:
        for segment in clip.segments:
            file_id = segment.file_id.entity_id
            if file_id not in videos:
                videos[file_id] = await workspace_video(
                    ctx, segment.file_id, tool_name="cut_video_clips"
                )
    return videos


async def _clip_sources(
    ctx: RunContext[RuntimeDeps],
    clips: list[ClipArgument],
    videos: dict[UUID, tuple[File, FileRevision]],
    *,
    stage: Callable[[str], Awaitable[None]],
) -> dict[UUID, ClipSource]:
    """Measures each video, and loads sentences and shot cuts for those a clip snaps."""
    snapped = {
        segment.file_id.entity_id for clip in clips if clip.snap for segment in clip.segments
    }
    sources = {}
    for file_id, (file, revision) in videos.items():
        metadata = probed_video(revision)
        if file_id not in snapped:
            sources[file_id] = ClipSource(revision=revision, metadata=metadata)
            continue
        sentences = ()
        if metadata.has_audio and transcription_provider() is not None:
            transcript = await video_transcript(
                ctx, file, revision, language=None, tool_name="cut_video_clips"
            )
            sentences = transcript.sentences
        await stage("Finding Shot Changes")
        try:
            shot_cuts_ms = await get_video_shot_cuts(ctx.deps.db, revision=revision)
        except MediaRendererError as exc:
            raise ToolFailed(exc.message) from exc
        sources[file_id] = ClipSource(
            revision=revision, metadata=metadata, sentences=sentences, shot_cuts_ms=shot_cuts_ms
        )
    return sources


async def _save_clip(
    ctx: RunContext[RuntimeDeps],
    index: int,
    name: str,
    request: PlannedClip,
    outcome: MediaOperationResult,
    folder_id: UUID | None,
) -> dict[str, object]:
    [output] = outcome.outputs
    try:
        async with ctx.deps.db.begin_nested():
            saved = await save_media_output(
                ctx.deps.db,
                workspace=ctx.deps.workspace,
                user_id=ctx.deps.user.id,
                output=output,
                name=name,
                actor=FileRevisionActor(agent_id=ctx.deps.agent.id),
                folder_id=folder_id,
            )
            # The renderer measured the clip, so it is ready without waiting for a probe.
            saved.revision.media_metadata = outcome.result.model_dump(mode="json")
            saved.file.processing_status = "ready"
            await ctx.deps.db.flush()
    except AppValidationError as exc:
        reason = "The clip is too large to save." if exc.field == "content" else exc.message
        return _failed(index, name, request, reason)
    except MediaRendererError as exc:
        return _failed(index, name, request, exc.message)
    await create_conversation_file_references(
        ctx.deps.db,
        workspace_id=ctx.deps.workspace.id,
        conversation_id=ctx.deps.conversation.id,
        file_ids=[saved.file.id],
        created_by_user_id=ctx.deps.user.id,
    )
    metadata = outcome.result
    return {
        "index": index,
        "status": "saved",
        "name": saved.file.name,
        "file_id": str(saved.file.id),
        "revision_id": str(saved.revision.id),
        "reference": FileReference(
            entity_id=saved.file.id,
            label=saved.file.name,
            description=f"Clip · {format_duration(metadata.duration_ms)}",
        ),
        "media_type": saved.revision.content_type,
        "duration_ms": metadata.duration_ms,
        "width": metadata.width,
        "height": metadata.height,
        "size_bytes": saved.revision.size_bytes,
        "segments": _segments(request),
        "warnings": list(request.warnings),
    }


def _failed(index: int, name: str, request: PlannedClip, reason: str) -> dict[str, object]:
    return {
        "index": index,
        "status": "failed",
        "name": name,
        "error": reason,
        "segments": _segments(request),
        "warnings": list(request.warnings),
    }


def _segments(request: PlannedClip) -> list[dict[str, object]]:
    return [
        {
            "file_id": str(segment.source.revision.file_id),
            "start_ms": segment.start_ms,
            "end_ms": segment.end_ms,
            "start": format_duration(segment.start_ms),
            "end": format_duration(segment.end_ms),
        }
        for segment in request.segments
    ]


def _clip_name(clip: ClipArgument, request: PlannedClip, first_file: File) -> str:
    if clip.name and clip.name.strip():
        return safe_filename(f"{PurePath(clip.name.strip()).stem}.mp4")
    first = request.segments[0]
    times = f"{format_duration(first.start_ms)}-{format_duration(first.end_ms)}".replace(":", ".")
    more = f" +{len(request.segments) - 1}" if len(request.segments) > 1 else ""
    return safe_filename(f"{PurePath(first_file.name).stem} {times}{more}.mp4")
