# apps/renderer/media/cut.py

"""The cut operation: joins segments from one or more inputs into one H.264 and AAC MP4."""

import math
from pathlib import Path
from typing import Any

from driver.server import OperationContext, OperationError

from media.ffmpeg import (
    OUTPUT_AUDIO_RATE,
    check_arguments,
    check_range,
    clamp_range,
    probe_file,
    require_video,
    run_ffmpeg,
    samples_per_frame,
    segment_input,
)
from media.framing import fill_filter, fit_filter, follow_filter, subject_tracks
from media.transitions import fades, join, validate_transitions

MAX_SEGMENTS = 10
MAX_SHOT_CUTS = 500
MAX_KEEP_RANGES = 500
MIN_OUTPUT_EDGE_PX = 64
MAX_OUTPUT_EDGE_PX = 3840
MIN_OUTPUT_FPS = 24
MAX_OUTPUT_FPS = 60
# About 61 MB a minute at most; the API derives its longest clip from these caps.
OUTPUT_VIDEO_OPTIONS = (
    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
    "-maxrate", "8M", "-bufsize", "16M", "-pix_fmt", "yuv420p",
)  # fmt: skip
OUTPUT_AUDIO_OPTIONS = ("-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2")
# Captions arrive as an ASS file the API built; only its styles and dialogue are read.
MAX_CAPTIONS_BYTES = 4 * 1024 * 1024
CAPTION_SECTIONS = frozenset({"[Script Info]", "[V4+ Styles]", "[Events]"})
# A source shorter than its range is padded with its last frame for at most this long.
END_PAD_SECONDS = 1


def validate_cut(arguments: dict[str, Any]) -> dict[str, Any]:
    check_arguments(
        arguments,
        required={
            "segments": list[list[int]],
            "width": int,
            "height": int,
            "fps": int,
            "fit": bool,
        },
        optional={
            "reframe": bool,
            "shot_cuts": list[list[int]],
            "keep": list[list[int]],
            "captions": bool,
            "transitions": list[tuple[str, int, str]],
            "fade_in_ms": int,
            "fade_out_ms": int,
        },
    )
    inputs = _validate_segments(arguments["segments"])
    _validate_framing(arguments, inputs)
    _validate_output(arguments)
    _validate_keep(arguments)
    validate_transitions(arguments)
    return arguments


def _validate_segments(segments: list[list[int]]) -> set[int]:
    """Segments are [input, start_ms, end_ms] and must use every input from 0."""
    if not 1 <= len(segments) <= MAX_SEGMENTS or any(len(item) != 3 for item in segments):
        raise OperationError(
            "invalid_request", f"segments must list 1 to {MAX_SEGMENTS} [input, start, end]."
        )
    for _, start, end in segments:
        check_range({"start_ms": start, "end_ms": end})
    inputs = {item[0] for item in segments}
    if inputs != set(range(len(inputs))):
        raise OperationError("invalid_request", "segments must use every input from 0.")
    return inputs


def _validate_framing(arguments: dict[str, Any], inputs: set[int]) -> None:
    if arguments.get("reframe") and arguments["fit"]:
        raise OperationError("invalid_request", "reframe and fit can't both be set.")
    shot_cuts = arguments.get("shot_cuts", [])
    if shot_cuts and not arguments.get("reframe"):
        raise OperationError("invalid_request", "shot_cuts need reframe.")
    if len(shot_cuts) > MAX_SHOT_CUTS or any(
        len(item) != 2 or item[0] not in inputs or item[1] < 0 for item in shot_cuts
    ):
        raise OperationError(
            "invalid_request", f"shot_cuts must list up to {MAX_SHOT_CUTS} [input, time]."
        )


def _validate_output(arguments: dict[str, Any]) -> None:
    if not MIN_OUTPUT_FPS <= arguments["fps"] <= MAX_OUTPUT_FPS:
        raise OperationError(
            "invalid_request", f"fps must be {MIN_OUTPUT_FPS} to {MAX_OUTPUT_FPS}."
        )
    for edge in (arguments["width"], arguments["height"]):
        if not MIN_OUTPUT_EDGE_PX <= edge <= MAX_OUTPUT_EDGE_PX or edge % 2:
            raise OperationError(
                "invalid_request",
                f"width and height must be even, {MIN_OUTPUT_EDGE_PX} to {MAX_OUTPUT_EDGE_PX}.",
            )


def _validate_keep(arguments: dict[str, Any]) -> None:
    """Keep ranges are [segment, first frame, end frame), in order and inside the segment."""
    keep, segments = arguments.get("keep", []), arguments["segments"]
    if len(keep) > MAX_KEEP_RANGES or any(len(item) != 3 for item in keep):
        raise OperationError(
            "invalid_request", f"keep must list up to {MAX_KEEP_RANGES} [segment, first, end]."
        )
    previous = (-1, 0)
    for position, first, end in keep:
        if not 0 <= position < len(segments) or (position, first) < previous:
            raise OperationError("invalid_request", "keep ranges must be in segment order.")
        _, start_ms, end_ms = segments[position]
        if not 0 <= first < end <= _frame_count(end_ms - start_ms, arguments["fps"]):
            raise OperationError("invalid_request", "keep ranges must be inside their segment.")
        previous = (position, end)


def _video_input_count(arguments: dict[str, Any]) -> int:
    return len({item[0] for item in arguments["segments"]})


def cut_input_count(arguments: dict[str, Any]) -> int:
    # The captions file, when there is one, follows the videos.
    return _video_input_count(arguments) + int(arguments.get("captions", False))


def run_cut(context: OperationContext, arguments: dict[str, Any]) -> dict[str, Any]:
    """Scales every segment to the output size, frame rate, and 48 kHz stereo, then joins them."""
    summaries = []
    for index in range(_video_input_count(arguments)):
        summary = probe_file(context, context.fetch_input(index).name)
        require_video(summary)
        summaries.append(summary)
    width, height, fps = arguments["width"], arguments["height"], arguments["fps"]
    tracks = subject_tracks(context, arguments, summaries) if arguments.get("reframe") else {}
    keep: dict[int, list[tuple[int, int]]] = {}
    for position, first, end in arguments.get("keep", []):
        keep.setdefault(position, []).append((first, end))
    options, filters, lengths = [], [], []
    for position, (index, start, end) in enumerate(arguments["segments"]):
        summary = summaries[index]
        start, end = clamp_range(summary, start, end)
        frames = _frame_count(end - start, fps)
        lengths.append(sum(last - first for first, last in keep.get(position, [])) or frames)
        options += segment_input(start, end, context.input_path(index))
        if arguments["fit"]:
            framing = fit_filter(width, height, position)
        elif position in tracks:
            framing = follow_filter(width, height, *tracks[position])
        else:
            framing = fill_filter(width, height)
        filters += _segment_filters(
            position, framing, summary["has_audio"], frames, keep.get(position), fps
        )
    total = join(filters, lengths, arguments.get("transitions", []), fps)
    video = "[joined]"
    if arguments.get("captions"):
        captions = _captions_input(context, len(summaries))
        filters.append(f"{video}ass=filename={captions.name}[captioned]")
        video = "[captioned]"
    filters += fades(video, arguments, total, fps)
    output = context.output_path(0)
    run_ffmpeg(
        context,
        *options,
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[v]",
        "-map",
        "[a]",
        *OUTPUT_VIDEO_OPTIONS,
        "-r",
        str(fps),
        *OUTPUT_AUDIO_OPTIONS,
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        output.name,
    )
    return probe_file(context, output.name)


def _frame_count(duration_ms: int, fps: int) -> int:
    return math.ceil(duration_ms * fps / 1000)


def _segment_filters(
    position: int,
    framing: str,
    has_audio: bool,
    frames: int,
    keep: list[tuple[int, int]] | None,
    fps: int,
) -> list[str]:
    """Builds [vN] and [aN], each exactly the segment's frames long so joins line up."""
    video_keep, audio_keep = _keep_filters(keep, fps)
    # Silence for an input without audio, so mismatched sources join cleanly.
    audio = f"[{position}:a:0]" if has_audio else f"anullsrc=r={OUTPUT_AUDIO_RATE}:cl=stereo,"
    return [
        f"[{position}:v:0]{framing},fps={fps},format=yuv420p,"
        f"tpad=stop_mode=clone:stop_duration={END_PAD_SECONDS},trim=end_frame={frames},"
        f"setpts=PTS-STARTPTS{video_keep}[v{position}]",
        f"{audio}aresample={OUTPUT_AUDIO_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo,"
        f"apad,atrim=end_sample={frames * samples_per_frame(fps)},"
        f"asetpts=PTS-STARTPTS{audio_keep}[a{position}]",
    ]


def _keep_filters(ranges: list[tuple[int, int]] | None, fps: int) -> tuple[str, str]:
    """Keeps only the given frames; audio is cut into frame-long pieces so both stay in sync."""
    if not ranges:
        return "", ""
    chosen = "+".join(f"between(n\\,{first}\\,{end - 1})" for first, end in ranges)
    return (
        f",select={chosen},setpts=N/FRAME_RATE/TB",
        f",asetnsamples=n={samples_per_frame(fps)}:p=0,aselect={chosen},asetpts=N/SR/TB",
    )


def _captions_input(context: OperationContext, index: int) -> Path:
    """Downloads the captions file and refuses anything beyond styles and dialogue."""
    path = context.fetch_input(index)
    data = path.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OperationError("invalid_request", "The captions aren't valid.") from exc
    sections = {line.strip() for line in text.splitlines() if line.startswith("[")}
    if len(data) > MAX_CAPTIONS_BYTES or not sections <= CAPTION_SECTIONS:
        raise OperationError("invalid_request", "The captions aren't valid.")
    return path
