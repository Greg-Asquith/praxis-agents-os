# apps/api/services/media/clips.py

"""Plans and renders video clips: segments of workspace videos joined into one MP4 each."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from core.settings import settings
from models.files import FileRevision
from services.files.contract import contract_for_content_type, stored_max_size_bytes
from services.files.domain import VideoMetadata
from services.files.utils import format_duration
from services.media.captions import CaptionStyle, PlacedOverlay, TextOverlay, subtitle_file
from services.media.domain import (
    MAX_CUT_KEEP_RANGES,
    MAX_CUT_SHOT_CUTS,
    MAX_OUTPUT_EDGE_PX,
    MAX_OUTPUT_FPS,
    MAX_TRANSITION_MS,
    MIN_OUTPUT_FPS,
    MIN_TRANSITION_MS,
    AudioCurve,
    CutOperation,
    CutSegment,
    CutTransition,
    MediaOperationResult,
    MediaRendererError,
    Transcript,
    TranscriptWord,
    TransitionStyle,
)
from services.media.run_media_operation import run_media_operation
from services.media.snapping import SnapLimits, snap_range
from services.media.transcription_providers import WORD_TIMED_MODELS
from services.media.utils import discard_staged_outputs, stage_media_input

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
# Pauses between words longer than this are cut, leaving this much either side of speech.
SILENCE_MIN_MS = 600
SILENCE_PAD_MS = 150
DEFAULT_TRANSITION_MS = 400
# Dipping through black or white reads better a little slower.
DEFAULT_DIP_TRANSITION_MS = 500
DIP_STYLES = frozenset({"fadeblack", "fadewhite"})


class TransitionOptions(BaseModel):
    """How segments join: an ffmpeg xfade style, its length, and the audio crossfade curve."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    style: TransitionStyle = Field(
        description=(
            "'none' is a hard cut. 'fade' or 'fadeblack' suit talking heads; slides, wipes, "
            "and covers suit B-roll."
        )
    )
    duration_ms: int | None = Field(
        default=None,
        ge=MIN_TRANSITION_MS,
        le=MAX_TRANSITION_MS,
        description="Omit for 400 ms (500 ms for fadeblack and fadewhite).",
    )
    audio_curve: AudioCurve = Field(
        default="tri", description="The audio crossfade's shape; 'tri' is linear."
    )

    def cut_transition(self) -> CutTransition:
        if self.style == "none":
            return CutTransition()
        default = DEFAULT_DIP_TRANSITION_MS if self.style in DIP_STYLES else DEFAULT_TRANSITION_MS
        return CutTransition(
            style=self.style,
            duration_ms=self.duration_ms or default,
            audio_curve=self.audio_curve,
        )


HARD_CUT = TransitionOptions(style="none")


@dataclass(frozen=True)
class ClipSource:
    """An authorised workspace video revision with what snapping, framing, and captions read."""

    revision: FileRevision
    metadata: VideoMetadata
    transcript: Transcript | None = None
    shot_cuts_ms: Sequence[int] = ()


@dataclass(frozen=True)
class PlannedSegment:
    source: ClipSource
    start_ms: int
    end_ms: int
    # Output frame ranges [first, end) left after removing pauses; empty keeps every frame.
    keep_frames: tuple[tuple[int, int], ...] = ()

    def output_ms(self, fps: int) -> int:
        if not self.keep_frames:
            return self.end_ms - self.start_ms
        return round(sum(end - first for first, end in self.keep_frames) * 1000 / fps)


@dataclass(frozen=True)
class PlannedClip:
    """One clip ready to render: its sources in input order, the cut operation, and its
    captions and overlays file.
    """

    segments: tuple[PlannedSegment, ...]
    sources: tuple[FileRevision, ...]
    operation: CutOperation
    warnings: tuple[str, ...]
    # The ASS file with the clip's captions and text overlays.
    captions: str | None = None
    overlays: tuple[PlacedOverlay, ...] = ()

    @property
    def duration_ms(self) -> int:
        fps = self.operation.fps
        overlaps = sum(transition.duration_ms for transition in self.operation.transitions)
        return sum(segment.output_ms(fps) for segment in self.segments) - overlaps


def max_clip_ms() -> int:
    """Returns the longest clip a File can hold at the renderer's bitrate caps."""
    limit_bytes = min(
        stored_max_size_bytes(contract_for_content_type("video/mp4")),
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
    captions: CaptionStyle | None = None,
    remove_silences: bool = False,
    transition: TransitionOptions | None = None,
    transitions_in: Sequence[TransitionOptions | None] = (),
    fade_in_ms: int = 0,
    fade_out_ms: int = 0,
    overlays: Sequence[TextOverlay] = (),
) -> PlannedClip:
    """Bounds, snaps, and numbers a clip's segments, removes pauses, and builds captions and
    text overlays.

    ``transition`` joins every pair of segments unless the later segment's own entry in
    ``transitions_in`` (one per segment, the first unused) says otherwise. Raises ValueError
    with a reason to show.
    """
    joins = [
        (own or transition or HARD_CUT).cut_transition()
        for own in (list(transitions_in) or [None] * len(segments))[1:]
    ]
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
                sentences=source.transcript.sentences if source.transcript else (),
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
    planned = _overlap_joins(planned, joins, [edges[1:] for edges in segments], warnings)
    fps = output_fps(planned[0].source.metadata)
    if (remove_silences or (captions and captions.preset == "highlight")) and any(
        segment.source.transcript and segment.source.transcript.model not in WORD_TIMED_MODELS
        for segment in planned
    ):
        raise ValueError(
            "Removing pauses and highlighting words need exact word times, which this "
            "deployment's transcription doesn't give. Use bold or clean captions and keep pauses."
        )
    if remove_silences:
        planned = [replace(segment, keep_frames=_kept_frames(segment, fps)) for segment in planned]
    keep = tuple(
        (position, first, end)
        for position, segment in enumerate(planned)
        for first, end in segment.keep_frames
    )
    if len(keep) > MAX_CUT_KEEP_RANGES:
        raise ValueError("The clip has too many pauses to remove. Cut it shorter or keep pauses.")
    _require_room_for_joins(planned, joins, fps)
    offsets = _segment_offsets(planned, joins, fps)
    clip_ms = offsets[-1] + planned[-1].output_ms(fps)
    words = _timeline_words(planned, joins, offsets, fps) if captions else []
    if captions and not words:
        warnings.append("There's no speech to caption.")
        captions = None
    placed = tuple(
        _place_overlay(overlay, number, planned, offsets, fps, clip_ms)
        for number, overlay in enumerate(overlays, start=1)
    )
    caption_text = None
    if captions or placed:
        caption_text, moved = subtitle_file(
            size=size, words=words, captions=captions, overlays=placed
        )
        warnings += moved

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
            fps=fps,
            fit=framing == "fit",
            reframe=framing == "auto",
            shot_cuts_ms=tuple(sorted(shot_cuts)[:MAX_CUT_SHOT_CUTS]),
            keep_frames=keep,
            captions=caption_text is not None,
            transitions=tuple(joins) if any(join.duration_ms for join in joins) else (),
            fade_in_ms=fade_in_ms,
            fade_out_ms=fade_out_ms,
        ),
        warnings=tuple(warnings),
        captions=caption_text,
        overlays=placed,
    )
    limit_ms = max_clip_ms()
    if clip.duration_ms > limit_ms:
        raise ValueError(
            f"The clip is {format_duration(clip.duration_ms)} long. "
            f"Clips can be up to {format_duration(limit_ms)}."
        )
    if fade_in_ms + fade_out_ms > clip.duration_ms:
        raise ValueError("The fades are longer than the clip.")
    return clip


def _overlap_joins(
    segments: list[PlannedSegment],
    joins: Sequence[CutTransition],
    requested: Sequence[tuple[int | None, int | None]],
    warnings: list[str],
) -> list[PlannedSegment]:
    """Extends each side of a transition by half its length, so the blend sits over the cut.

    Snapped cuts end and start on whole sentences; without this, the overlap would blend
    away their first and last words. At a video's start or end the overlap takes the
    segment's own edge instead, with a warning when the range asked for that edge. A whole
    video, with no start or end given, always blends its edges, so it doesn't warn.
    """
    extended = list(segments)
    for position, join in enumerate(joins):
        half = join.duration_ms // 2
        if not half:
            continue
        before, after = extended[position], extended[position + 1]
        room_after = before.source.metadata.duration_ms - before.end_ms
        extended[position] = replace(before, end_ms=before.end_ms + min(half, room_after))
        extended[position + 1] = replace(after, start_ms=after.start_ms - min(half, after.start_ms))
        if room_after < half and requested[position][1] is not None:
            warnings.append(
                f"Segment {position + 1} ends at the end of its video, so the transition "
                "blends its last moments."
            )
        if after.start_ms < half and requested[position + 1][0] is not None:
            warnings.append(
                f"Segment {position + 2} starts at the start of its video, so the transition "
                "blends its first moments."
            )
    return extended


def _require_room_for_joins(
    segments: Sequence[PlannedSegment], joins: Sequence[CutTransition], fps: int
) -> None:
    """A transition may take at most half of either segment it joins."""
    for position, join in enumerate(joins):
        shorter = min(segments[position].output_ms(fps), segments[position + 1].output_ms(fps))
        if join.duration_ms * 2 > shorter:
            raise ValueError(
                f"The transition before segment {position + 2} lasts "
                f"{join.duration_ms / 1000:g} s, more than half of a {shorter / 1000:g} s "
                "segment beside it. Use a shorter transition."
            )


def _segment_words(segment: PlannedSegment) -> list[TranscriptWord]:
    """The transcript words a segment shows, clamped to it."""
    if segment.source.transcript is None:
        return []
    return [
        word.model_copy(
            update={
                "start_ms": max(word.start_ms, segment.start_ms),
                "end_ms": min(word.end_ms, segment.end_ms),
            }
        )
        for word in segment.source.transcript.words
        if word.start_ms < segment.end_ms and word.end_ms > segment.start_ms
    ]


def _kept_frames(segment: PlannedSegment, fps: int) -> tuple[tuple[int, int], ...]:
    """Cuts pauses longer than SILENCE_MIN_MS to SILENCE_PAD_MS beside speech, in frames.

    A segment without words, such as B-roll, keeps every frame.
    """
    words = _segment_words(segment)
    removed = []
    previous, after = segment.start_ms, 0
    for word in [*words, None] if words else []:
        following, before = (segment.end_ms, 0) if word is None else (word.start_ms, SILENCE_PAD_MS)
        if following - previous > SILENCE_MIN_MS:
            removed.append((previous + after, following - before))
        if word is not None:
            previous, after = max(previous, word.end_ms), SILENCE_PAD_MS
    if not removed:
        return ()
    kept, cursor = [], segment.start_ms
    for gap_start, gap_end in removed:
        kept.append((cursor, gap_start))
        cursor = gap_end
    kept.append((cursor, segment.end_ms))
    frames = (
        (
            round((start - segment.start_ms) * fps / 1000),
            round((end - segment.start_ms) * fps / 1000),
        )
        for start, end in kept
    )
    return tuple((first, end) for first, end in frames if end > first)


def _timeline_ms(segment: PlannedSegment, time_ms: int, fps: int) -> int:
    """Maps a source time inside a segment to its time from the segment's start in the output."""
    relative = time_ms - segment.start_ms
    if not segment.keep_frames:
        return relative
    frame, kept = relative * fps / 1000, 0
    for first, end in segment.keep_frames:
        if frame < end:
            return round((kept + max(0, frame - first)) * 1000 / fps)
        kept += end - first
    return round(kept * 1000 / fps)


def _segment_offsets(
    segments: Sequence[PlannedSegment], joins: Sequence[CutTransition], fps: int
) -> list[int]:
    """Where each segment starts on the joined clip's timeline, less each earlier overlap."""
    offsets, offset = [], 0
    for position, segment in enumerate(segments):
        offsets.append(offset)
        offset += segment.output_ms(fps)
        if position < len(joins):
            offset -= joins[position].duration_ms
    return offsets


def _timeline_words(
    segments: Sequence[PlannedSegment],
    joins: Sequence[CutTransition],
    offsets: Sequence[int],
    fps: int,
) -> list[TranscriptWord]:
    """Every segment's words on the joined clip's timeline.

    Where a transition overlaps two segments, each keeps its words up to the middle of the
    blend, so captions never show both at once.
    """
    words = []
    overlaps = [join.duration_ms for join in joins]
    for position, (segment, offset) in enumerate(zip(segments, offsets, strict=True)):
        before = overlaps[position - 1] if position else 0
        after = overlaps[position] if position < len(overlaps) else 0
        first = offset + before // 2
        last = offset + segment.output_ms(fps) - after + after // 2
        for word in _segment_words(segment):
            start = max(first, offset + _timeline_ms(segment, word.start_ms, fps))
            end = min(last, offset + _timeline_ms(segment, word.end_ms, fps))
            if start < end:
                words.append(word.model_copy(update={"start_ms": start, "end_ms": end}))
    return words


def _place_overlay(
    overlay: TextOverlay,
    number: int,
    segments: Sequence[PlannedSegment],
    offsets: Sequence[int],
    fps: int,
    duration_ms: int,
) -> PlacedOverlay:
    """Puts an overlay on the clip's timeline: clip times as given, or a segment's video times
    mapped through the same timeline as captions.
    """
    if overlay.segment is None:
        start = 0 if overlay.start_ms is None else overlay.start_ms
        end = duration_ms if overlay.end_ms is None else overlay.end_ms
        if end > duration_ms:
            raise ValueError(
                f"Text overlay {number} ends after the clip, which is "
                f"{format_duration(duration_ms)} long."
            )
    else:
        if overlay.segment > len(segments):
            raise ValueError(
                f"Text overlay {number} names segment {overlay.segment}, and the clip has "
                f"{len(segments)}."
            )
        segment = segments[overlay.segment - 1]
        start_ms = segment.start_ms if overlay.start_ms is None else overlay.start_ms
        end_ms = segment.end_ms if overlay.end_ms is None else overlay.end_ms
        if start_ms < segment.start_ms or end_ms > segment.end_ms:
            raise ValueError(
                f"Text overlay {number}'s times must be inside segment {overlay.segment}, "
                f"{format_duration(segment.start_ms)} to {format_duration(segment.end_ms)} of "
                "its video."
            )
        offset = offsets[overlay.segment - 1]
        start = offset + _timeline_ms(segment, start_ms, fps)
        end = offset + _timeline_ms(segment, end_ms, fps)
    if end <= start:
        raise ValueError(f"Text overlay {number} must start before it ends in the clip.")
    if overlay.fade_in_ms + overlay.fade_out_ms > end - start:
        raise ValueError(f"Text overlay {number}'s fades are longer than it shows.")
    return PlacedOverlay(overlay=overlay, start_ms=start, end_ms=end)


async def render_clips(
    workspace_id: UUID, clips: Sequence[PlannedClip]
) -> list[MediaOperationResult | MediaRendererError]:
    """Renders clips a few at a time; one clip's failure doesn't stop the others."""
    gate = asyncio.Semaphore(RENDER_CONCURRENCY)

    async def render(clip: PlannedClip) -> MediaOperationResult | MediaRendererError:
        async with gate:
            staged = (
                [await stage_media_input(workspace_id, clip.captions.encode(), extension=".ass")]
                if clip.captions
                else []
            )
            try:
                return await run_media_operation(
                    workspace_id=workspace_id,
                    sources=clip.sources,
                    operation=clip.operation,
                    staged_inputs=staged,
                )
            except MediaRendererError as exc:
                return exc
            finally:
                await discard_staged_outputs(staged)

    return list(await asyncio.gather(*(render(clip) for clip in clips)))
