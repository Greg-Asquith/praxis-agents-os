# apps/api/services/media/clips.py

"""Plans and renders video clips: segments of workspace videos joined into one MP4 each."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from core.settings import settings
from models.files import FileRevision
from services.files.contract import contract_for_content_type, max_size_bytes
from services.files.domain import VideoMetadata
from services.files.utils import format_duration
from services.media.domain import (
    MAX_CUT_SHOT_CUTS,
    MAX_OUTPUT_EDGE_PX,
    MAX_OUTPUT_FPS,
    MIN_OUTPUT_FPS,
    CutOperation,
    CutSegment,
    MediaOperationResult,
    MediaRendererError,
    TranscriptSentence,
)
from services.media.run_media_operation import run_media_operation
from services.media.snapping import SnapLimits, snap_range

AspectRatio = Literal["original", "9:16", "1:1", "4:5", "16:9"]
# auto follows the largest face per shot; center crops the middle; fit shows the whole frame.
Framing = Literal["auto", "center", "fit"]
ASPECT_RATIOS: dict[str, tuple[int, int]] = {
    "9:16": (9, 16),
    "1:1": (1, 1),
    "4:5": (4, 5),
    "16:9": (16, 9),
}
OUTPUT_SHORT_EDGE_PX = 1080
# The renderer caps clips at 8 Mbit/s video and 128 kbit/s audio.
MAX_OUTPUT_BITS_PER_SECOND = 8_128_000
DEFAULT_OUTPUT_FPS = 30
# The renderer's default maximum instances.
RENDER_CONCURRENCY = 3
# A snap that moves a cut by this much is worth telling the agent about.
SNAP_NOTICE_MS = 1000


@dataclass(frozen=True)
class ClipSource:
    """An authorised workspace video revision with what snapping and framing read."""

    revision: FileRevision
    metadata: VideoMetadata
    sentences: Sequence[TranscriptSentence] = ()
    shot_cuts_ms: Sequence[int] = ()


@dataclass(frozen=True)
class PlannedSegment:
    source: ClipSource
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class PlannedClip:
    """One clip ready to render: its sources in input order and the cut operation."""

    segments: tuple[PlannedSegment, ...]
    sources: tuple[FileRevision, ...]
    operation: CutOperation
    warnings: tuple[str, ...]

    @property
    def duration_ms(self) -> int:
        return sum(segment.end_ms - segment.start_ms for segment in self.segments)


def max_clip_ms() -> int:
    """Returns the longest clip a File can hold at the renderer's bitrate caps."""
    limit_bytes = min(
        max_size_bytes(contract_for_content_type("video/mp4")),
        settings.MEDIA_RENDERER_MAX_OUTPUT_BYTES,
    )
    return min(
        settings.VIDEO_MAX_SOURCE_DURATION_SECONDS * 1000,
        limit_bytes * 8 * 1000 // MAX_OUTPUT_BITS_PER_SECOND,
    )


def output_size(aspect_ratio: AspectRatio, first: VideoMetadata) -> tuple[int, int]:
    """Returns even output dimensions, 1080 pixels on the short side."""
    if aspect_ratio == "original":
        if first.width is None or first.height is None:
            raise ValueError("The first video has no dimensions")
        upright = first.rotation in {90, 270}
        width, height = (first.height, first.width) if upright else (first.width, first.height)
    else:
        width, height = ASPECT_RATIOS[aspect_ratio]
    short, long = sorted((width, height))
    long_edge = min(MAX_OUTPUT_EDGE_PX, round(OUTPUT_SHORT_EDGE_PX * long / short / 2) * 2)
    return (
        (OUTPUT_SHORT_EDGE_PX, long_edge) if width <= height else (long_edge, OUTPUT_SHORT_EDGE_PX)
    )


def output_fps(first: VideoMetadata) -> int:
    """Keeps the first video's frame rate, within what the renderer writes."""
    if first.fps is None:
        return DEFAULT_OUTPUT_FPS
    return min(MAX_OUTPUT_FPS, max(MIN_OUTPUT_FPS, round(first.fps)))


def plan_clip(
    segments: Sequence[tuple[ClipSource, int | None, int | None]],
    *,
    size: tuple[int, int],
    framing: Framing,
    snap: bool,
) -> PlannedClip:
    """Bounds, snaps, and numbers a clip's segments. Raises ValueError with a reason to show."""
    planned, warnings = [], []
    for position, (source, start_ms, end_ms) in enumerate(segments, start=1):
        duration_ms = source.metadata.duration_ms
        start_ms = 0 if start_ms is None else start_ms
        end_ms = duration_ms if end_ms is None else end_ms
        if start_ms >= duration_ms or end_ms <= start_ms:
            raise ValueError(
                f"Segment {position} must start before it ends, inside the video's "
                f"{format_duration(duration_ms)}."
            )
        end_ms = min(end_ms, duration_ms)
        if snap:
            snapped = snap_range(
                start_ms,
                end_ms,
                sentences=source.sentences,
                shot_cuts_ms=source.shot_cuts_ms,
                duration_ms=duration_ms,
                limits=SnapLimits(
                    min_ms=1,
                    max_ms=duration_ms,
                    shot_tolerance_ms=settings.VIDEO_SNAP_SHOT_TOLERANCE_MS,
                ),
            )
            if snapped is not None:
                if max(abs(snapped[0] - start_ms), abs(snapped[1] - end_ms)) >= SNAP_NOTICE_MS:
                    warnings.append(
                        f"Segment {position} moved to {format_duration(snapped[0])} to "
                        f"{format_duration(snapped[1])} to keep whole sentences and shots."
                    )
                start_ms, end_ms = snapped
        planned.append(PlannedSegment(source=source, start_ms=start_ms, end_ms=end_ms))

    # Each distinct revision is one renderer input, numbered in order of first use.
    inputs: dict[UUID, int] = {}
    for segment in planned:
        inputs.setdefault(segment.source.revision.id, len(inputs))
    revisions = {segment.source.revision.id: segment.source.revision for segment in planned}
    # Automatic framing jumps only at shot cuts, so it needs those inside each segment.
    shot_cuts = {
        (inputs[segment.source.revision.id], cut)
        for segment in planned
        for cut in segment.source.shot_cuts_ms
        if framing == "auto" and segment.start_ms < cut < segment.end_ms
    }
    clip = PlannedClip(
        segments=tuple(planned),
        sources=tuple(revisions[revision_id] for revision_id in inputs),
        operation=CutOperation(
            segments=tuple(
                CutSegment(
                    input=inputs[segment.source.revision.id],
                    start_ms=segment.start_ms,
                    end_ms=segment.end_ms,
                )
                for segment in planned
            ),
            width=size[0],
            height=size[1],
            fps=output_fps(planned[0].source.metadata),
            fit=framing == "fit",
            reframe=framing == "auto",
            shot_cuts_ms=tuple(sorted(shot_cuts)[:MAX_CUT_SHOT_CUTS]),
        ),
        warnings=tuple(warnings),
    )
    limit_ms = max_clip_ms()
    if clip.duration_ms > limit_ms:
        raise ValueError(
            f"The clip is {format_duration(clip.duration_ms)} long. "
            f"Clips can be up to {format_duration(limit_ms)}."
        )
    return clip


async def render_clips(
    workspace_id: UUID, clips: Sequence[PlannedClip]
) -> list[MediaOperationResult | MediaRendererError]:
    """Renders clips a few at a time; one clip's failure doesn't stop the others."""
    gate = asyncio.Semaphore(RENDER_CONCURRENCY)

    async def render(clip: PlannedClip) -> MediaOperationResult | MediaRendererError:
        async with gate:
            try:
                return await run_media_operation(
                    workspace_id=workspace_id, sources=clip.sources, operation=clip.operation
                )
            except MediaRendererError as exc:
                return exc

    return list(await asyncio.gather(*(render(clip) for clip in clips)))
