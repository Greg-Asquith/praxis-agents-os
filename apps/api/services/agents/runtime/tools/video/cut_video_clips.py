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
from models.files import File, FileFolder, FileRevision
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
from services.files import (
    create_conversation_file_references,
    ensure_source_file_folder,
    resolve_folder_by_name,
)
from services.files.revision_actor import FileRevisionActor
from services.files.utils import format_duration
from services.media import discard_staged_outputs, save_media_output
from services.media.captions import (
    CaptionPreset,
    CaptionStyle,
    CaptionTextStyle,
    PlacedOverlay,
    TextOverlay,
)
from services.media.clips import (
    RENDER_CONCURRENCY,
    AspectRatio,
    ClipSource,
    Framing,
    PlannedClip,
    TransitionOptions,
    output_size,
    plan_clip,
    render_clips,
)
from services.media.domain import (
    MAX_CUT_SEGMENTS,
    MAX_FADE_MS,
    MediaOperationResult,
    MediaRendererError,
)
from services.media.get_video_shot_cuts import get_video_shot_cuts
from services.media.run_media_operation import REQUEST_ALLOWANCE_SECONDS
from services.media.transcription_providers import transcription_provider
from services.storage.paths import safe_filename
from utils.validation import normalize_optional_text

MAX_CLIPS = 5
MAX_TEXT_OVERLAYS = 5
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
    transition_in: TransitionOptions | None = Field(
        default=None,
        description=(
            "How the previous segment joins this one, overriding the clip's transition. "
            "Ignored on the first segment."
        ),
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
    transition: TransitionOptions | None = Field(
        default=None, description="How this clip's segments join, overriding the call's."
    )
    fade_in_ms: int = Field(
        default=0, ge=0, le=MAX_FADE_MS, description="Fade in from black and silence."
    )
    fade_out_ms: int = Field(default=0, ge=0, le=MAX_FADE_MS, description="Fade out to black.")
    text_overlays: list[TextOverlay] = Field(
        default_factory=list,
        max_length=MAX_TEXT_OVERLAYS,
        description=(
            "Text burned into the clip, such as a hook, a title, a label, or a call to action. "
            "Each shows for the whole clip unless given times."
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
        "rather than inventing times. aspect_ratio 9:16 suits Reels, Shorts, and TikTok. When "
        "the shape changes, framing 'auto' (the default) crops to follow the speaker's face, "
        "'center' crops the middle, and 'fit' shows the whole frame over a blurred fill. "
        "captions burns in the spoken words: 'bold' for punchy reels, 'clean' for a subtle "
        "boxed line, 'highlight' to pick out each word as it's spoken; caption_style overrides "
        "any part of the preset, such as the font or colours, when the person asks. "
        "remove_silences cuts pauses between words with hard jump cuts; leave it off unless the "
        "person asks for tighter pacing or no pauses. Both apply to every clip. Segments join "
        "with hard cuts unless transition says otherwise, for every clip, one clip, or one "
        "segment's transition_in; any ffmpeg xfade style, 400 ms by default. Use transitions "
        "and fade_in_ms or fade_out_ms only when the person asks for them. A clip's "
        "text_overlays add text such as a hook or a call to action, at the top by default; "
        "the 'title' preset suits a hook. Clips save in a "
        "folder named after their first video unless folder names another. One clip failing "
        "doesn't stop the others; the result reports each clip."
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
            ToolFieldPresentation(key="captions", label="Captions", secondary=True),
            ToolFieldPresentation(key="folder", label="Folder", secondary=True),
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
        Framing,
        Field(
            description=(
                "How a frame of another shape fits: follow the face, crop the middle, or fit "
                "over a blur."
            )
        ),
    ] = "auto",
    captions: Annotated[
        CaptionPreset | Literal["none"],
        Field(description="Burned-in captions from the transcript, or 'none'."),
    ] = "none",
    caption_style: Annotated[
        CaptionTextStyle | None,
        Field(
            description=(
                "Optional overrides for the captions preset: font, size, colours, outline, "
                "box, uppercase, words per caption, lines, and position. Omit to use the "
                "preset as it is."
            )
        ),
    ] = None,
    remove_silences: Annotated[
        bool,
        Field(
            description=(
                "Cut pauses longer than 0.6 s between words. Off unless the person asks; it "
                "makes jump cuts."
            )
        ),
    ] = False,
    transition: Annotated[
        TransitionOptions | None,
        Field(
            description=(
                "How segments join in every clip, so a set looks consistent. Omit for hard cuts."
            )
        ),
    ] = None,
    folder: Annotated[
        str | None,
        Field(
            max_length=255,
            description=(
                "Optional folder name for every clip, created if needed. Omit to save each clip "
                "in the folder named after its first video."
            ),
        ),
    ] = None,
) -> dict[str, object]:
    """Renders each clip from the caller's own videos and saves it in its output folder."""
    stage = progress(ctx)
    videos = await _workspace_videos(ctx, clips)
    style = (
        None
        if captions == "none"
        else CaptionStyle(preset=captions, options=caption_style or CaptionTextStyle())
    )
    sources = await _clip_sources(
        ctx,
        clips,
        videos,
        framing=framing,
        needs_words=style is not None or remove_silences,
        stage=stage,
    )
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
                    framing=framing,
                    snap=clip.snap,
                    captions=style,
                    remove_silences=remove_silences,
                    transition=clip.transition or transition,
                    transitions_in=[segment.transition_in for segment in clip.segments],
                    fade_in_ms=clip.fade_in_ms,
                    fade_out_ms=clip.fade_out_ms,
                    overlays=clip.text_overlays,
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
    folders = _ClipFolders(normalize_optional_text(folder))
    results = []
    for index, (clip, request, outcome) in enumerate(
        zip(clips, planned, rendered, strict=True), start=1
    ):
        first_file = videos[clip.segments[0].file_id.entity_id][0]
        name = _clip_name(clip, request, first_file)
        if isinstance(outcome, MediaRendererError):
            results.append(_failed(index, name, request, outcome.message))
            continue
        clip_folder = await folders.get(ctx, first_file)
        results.append(await _save_clip(ctx, index, name, request, outcome, clip_folder))
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
    framing: Framing,
    needs_words: bool,
    stage: Callable[[str], Awaitable[None]],
) -> dict[UUID, ClipSource]:
    """Measures each video and loads what its clips need: a transcript to snap, caption, or
    remove pauses, and shot cuts to snap or follow a face.
    """
    if needs_words and transcription_provider() is None:
        raise ToolFailed(
            "Captions and removing pauses need speech transcription, which isn't set up."
        )
    snapped = {
        segment.file_id.entity_id for clip in clips if clip.snap for segment in clip.segments
    }
    sources = {}
    for file_id, (file, revision) in videos.items():
        metadata = probed_video(revision)
        transcript = None
        if (
            (needs_words or file_id in snapped)
            and metadata.has_audio
            and transcription_provider() is not None
        ):
            transcript = await video_transcript(
                ctx, file, revision, language=None, tool_name="cut_video_clips"
            )
        shot_cuts_ms: tuple[int, ...] = ()
        if file_id in snapped or framing == "auto":
            await stage("Finding Shot Changes")
            try:
                shot_cuts_ms = await get_video_shot_cuts(ctx.deps.db, revision=revision)
            except MediaRendererError as exc:
                raise ToolFailed(exc.message) from exc
        sources[file_id] = ClipSource(
            revision=revision, metadata=metadata, transcript=transcript, shot_cuts_ms=shot_cuts_ms
        )
    return sources


async def _save_clip(
    ctx: RunContext[RuntimeDeps],
    index: int,
    name: str,
    request: PlannedClip,
    outcome: MediaOperationResult,
    folder: FileFolder,
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
                folder_id=folder.id,
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
        "folder": {"id": str(folder.id), "name": folder.name},
        "segments": _segments(request),
        "fade_in_ms": request.operation.fade_in_ms,
        "fade_out_ms": request.operation.fade_out_ms,
        "text_overlays": _overlays(request.overlays),
        "warnings": list(request.warnings),
    }


class _ClipFolders:
    """Resolves each clip's folder once per call: the named folder, or its first video's."""

    def __init__(self, name: str | None) -> None:
        self._name = name
        self._resolved: dict[UUID | None, FileFolder] = {}

    async def get(self, ctx: RunContext[RuntimeDeps], first_file: File) -> FileFolder:
        key = None if self._name is not None else first_file.id
        if key not in self._resolved:
            self._resolved[key] = (
                await resolve_folder_by_name(
                    ctx.deps.db,
                    workspace=ctx.deps.workspace,
                    agent=ctx.deps.agent,
                    requested_by=ctx.deps.user,
                    name=self._name,
                )
                if self._name is not None
                else await ensure_source_file_folder(ctx.deps, first_file)
            )
        return self._resolved[key]


def _failed(index: int, name: str, request: PlannedClip, reason: str) -> dict[str, object]:
    return {
        "index": index,
        "status": "failed",
        "name": name,
        "error": reason,
        "segments": _segments(request),
        "fade_in_ms": request.operation.fade_in_ms,
        "fade_out_ms": request.operation.fade_out_ms,
        "text_overlays": _overlays(request.overlays),
        "warnings": list(request.warnings),
    }


def _segments(request: PlannedClip) -> list[dict[str, object]]:
    transitions = request.operation.transitions
    return [
        {
            "file_id": str(segment.source.revision.file_id),
            "start_ms": segment.start_ms,
            "end_ms": segment.end_ms,
            "start": format_duration(segment.start_ms),
            "end": format_duration(segment.end_ms),
            "transition_in": (
                transitions[position - 1].model_dump()
                if position and transitions and transitions[position - 1].duration_ms
                else None
            ),
        }
        for position, segment in enumerate(request.segments)
    ]


def _overlays(overlays: tuple[PlacedOverlay, ...]) -> list[dict[str, object]]:
    return [
        {
            "text": placed.overlay.text,
            "start_ms": placed.start_ms,
            "end_ms": placed.end_ms,
            "start": format_duration(placed.start_ms),
            "end": format_duration(placed.end_ms),
        }
        for placed in overlays
    ]


def _clip_name(clip: ClipArgument, request: PlannedClip, first_file: File) -> str:
    if clip.name and clip.name.strip():
        return safe_filename(f"{PurePath(clip.name.strip()).stem}.mp4")
    first = request.segments[0]
    times = f"{format_duration(first.start_ms)}-{format_duration(first.end_ms)}".replace(":", ".")
    more = f" +{len(request.segments) - 1}" if len(request.segments) > 1 else ""
    return safe_filename(f"{PurePath(first_file.name).stem} {times}{more}.mp4")
