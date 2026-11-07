# apps/media-renderer/media/cut.py

"""The cut operation: joins segments from one or more inputs into one H.264 and AAC MP4."""

import math
from pathlib import Path
from typing import Any

from driver.server import OperationContext, OperationError

from media.audio import VOICE_FILTERS, normalize_loudness
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
from media.music import mix_music, music_input, validate_music
from media.transitions import fades, join, validate_transitions
from media.zoom import MAX_ZOOM_PERCENT, MIN_ZOOM_PERCENT, zoom_filter

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
# Segment speed in percent; one atempo filter covers this range with the pitch kept.
MIN_SPEED_PERCENT = 50
MAX_SPEED_PERCENT = 200
MAX_FREEZE_MS = 3000


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
            "enhance_voice": bool,
            "normalize_loudness": bool,
            "music": bool,
            "music_volume": int,
            "music_duck": bool,
            "music_start_ms": int,
            "music_fade_in_ms": int,
            "music_fade_out_ms": int,
            "speed_percents": list[int],
            "freeze_end_ms": list[int],
            "zooms": list[list[int]],
            "punch_ins": bool,
        },
    )
    inputs = _validate_segments(arguments["segments"])
    _validate_framing(arguments, inputs)
    _validate_output(arguments)
    _validate_keep(arguments)
    _validate_pace(arguments)
    _validate_zooms(arguments)
    validate_transitions(arguments)
    validate_music(arguments)
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


def _validate_pace(arguments: dict[str, Any]) -> None:
    """Speeds and freezes list one value per segment, when given."""
    count = len(arguments["segments"])
    speeds = arguments.get("speed_percents", [100] * count)
    freezes = arguments.get("freeze_end_ms", [0] * count)
    if len(speeds) != count or len(freezes) != count:
        raise OperationError("invalid_request", "Speeds and freezes must list one per segment.")
    if any(not MIN_SPEED_PERCENT <= speed <= MAX_SPEED_PERCENT for speed in speeds):
        raise OperationError(
            "invalid_request",
            f"speed_percents must be {MIN_SPEED_PERCENT} to {MAX_SPEED_PERCENT}.",
        )
    if any(not 0 <= freeze <= MAX_FREEZE_MS for freeze in freezes):
        raise OperationError("invalid_request", f"freeze_end_ms must be 0 to {MAX_FREEZE_MS}.")


def _validate_zooms(arguments: dict[str, Any]) -> None:
    """Zooms list one [from, to] percent per segment, when given."""
    zooms = arguments.get("zooms")
    if zooms is None:
        return
    if len(zooms) != len(arguments["segments"]) or any(
        len(zoom) != 2 or not all(MIN_ZOOM_PERCENT <= value <= MAX_ZOOM_PERCENT for value in zoom)
        for zoom in zooms
    ):
        raise OperationError(
            "invalid_request",
            f"zooms must list one [from, to] per segment, {MIN_ZOOM_PERCENT} to "
            f"{MAX_ZOOM_PERCENT}.",
        )


def _video_input_count(arguments: dict[str, Any]) -> int:
    return len({item[0] for item in arguments["segments"]})


def cut_input_count(arguments: dict[str, Any]) -> int:
    # The music, then the captions file, follow the videos.
    return (
        _video_input_count(arguments)
        + int(arguments.get("music", False))
        + int(arguments.get("captions", False))
    )


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
    count = len(arguments["segments"])
    speeds = arguments.get("speed_percents", [100] * count)
    freezes = arguments.get("freeze_end_ms", [0] * count)
    zooms = arguments.get("zooms", [[MIN_ZOOM_PERCENT, MIN_ZOOM_PERCENT]] * count)
    options, filters, lengths = [], [], []
    for position, (index, start, end) in enumerate(arguments["segments"]):
        summary = summaries[index]
        start, end = clamp_range(summary, start, end)
        frames = _frame_count(end - start, fps)
        kept = sum(last - first for first, last in keep.get(position, [])) or frames
        pace = _pace_filters(kept, speeds[position], freezes[position], fps)
        lengths.append(pace[2])
        options += segment_input(start, end, context.input_path(index))
        if arguments["fit"]:
            framing = fit_filter(width, height, position)
        elif position in tracks:
            framing = follow_filter(width, height, *tracks[position])
        else:
            framing = fill_filter(width, height)
        # Punch-ins alternate from the second kept range, so every jump cut changes the zoom.
        punched = keep.get(position, [])[1::2] if arguments.get("punch_ins") else []
        zoom = zoom_filter(frames, zooms[position], punched)
        filters += _segment_filters(
            position,
            framing,
            zoom,
            arguments.get("enhance_voice", False),
            summary["has_audio"],
            frames,
            keep.get(position),
            pace,
            fps,
        )
    total = join(filters, lengths, arguments.get("transitions", []), fps)
    audio, extra = "[mixed]", len(summaries)
    # Music runs under the joined clip, so it plays straight through the transitions.
    if arguments.get("music"):
        options += music_input(context, arguments, extra, total, fps)
        # ffmpeg opens each segment as its own input, so the music follows the segments.
        audio = mix_music(filters, arguments, len(arguments["segments"]), total, fps)
        extra += 1
    video = "[joined]"
    if arguments.get("captions"):
        captions = _captions_input(context, extra)
        filters.append(f"{video}ass=filename={captions.name}[captioned]")
        video = "[captioned]"
    filters += fades(video, audio, arguments, total, fps)
    output = context.output_path(0)
    normalize = arguments.get("normalize_loudness", False)
    # Loudness is measured on the finished mix, so it renders to a working file first.
    rendered = context.workdir / "mixed.mp4" if normalize else output
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
        rendered.name,
    )
    loudness = (
        normalize_loudness(context, rendered, output, OUTPUT_AUDIO_OPTIONS) if normalize else None
    )
    return {**probe_file(context, output.name), "loudness_lufs": loudness}


def _frame_count(duration_ms: int, fps: int) -> int:
    return math.ceil(duration_ms * fps / 1000)


def _segment_filters(
    position: int,
    framing: str,
    zoom: str,
    enhance_voice: bool,
    has_audio: bool,
    frames: int,
    keep: list[tuple[int, int]] | None,
    pace: tuple[str, str, int],
    fps: int,
) -> list[str]:
    """Builds [vN] and [aN], each exactly the segment's output frames long so joins line up.

    The zoom counts the segment's frames before pauses are removed, as ``keep`` does.
    """
    video_keep, audio_keep = _keep_filters(keep, fps)
    video_pace, audio_pace, _ = pace
    # Silence for an input without audio, so mismatched sources join cleanly.
    audio = f"[{position}:a:0]" if has_audio else f"anullsrc=r={OUTPUT_AUDIO_RATE}:cl=stereo,"
    voice = f"{VOICE_FILTERS}," if enhance_voice else ""
    return [
        f"[{position}:v:0]{framing},fps={fps},format=yuv420p,"
        f"tpad=stop_mode=clone:stop_duration={END_PAD_SECONDS},trim=end_frame={frames},"
        f"setpts=PTS-STARTPTS{zoom}{video_keep}{video_pace}[v{position}]",
        f"{audio}aresample={OUTPUT_AUDIO_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo,"
        f"{voice}apad,atrim=end_sample={frames * samples_per_frame(fps)},"
        f"asetpts=PTS-STARTPTS{audio_keep}{audio_pace}[a{position}]",
    ]


def _pace_filters(
    frames: int, speed_percent: int, freeze_ms: int, fps: int
) -> tuple[str, str, int]:
    """Plays a segment's kept frames at a speed, pitch kept, then holds its last frame silent.

    Returns the video and audio filters and the segment's length in output frames.
    """
    samples = samples_per_frame(fps)
    length, video, audio = frames, "", ""
    if speed_percent != 100:
        length = max(1, round(frames * 100 / speed_percent))
        # Retimed frames are resampled to the output rate, then padded and trimmed exactly.
        video = (
            f",setpts=PTS*100/{speed_percent},fps={fps},"
            f"tpad=stop_mode=clone:stop_duration={END_PAD_SECONDS},trim=end_frame={length},"
            "setpts=PTS-STARTPTS"
        )
        audio = (
            f",atempo={speed_percent / 100:g},apad,atrim=end_sample={length * samples},"
            "asetpts=PTS-STARTPTS"
        )
    freeze = round(freeze_ms * fps / 1000)
    if freeze:
        video += f",tpad=stop_mode=clone:stop={freeze}"
        audio += f",apad=pad_len={freeze * samples}"
    return video, audio, length + freeze


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
