# apps/renderer/media/operations.py

"""Media operations. Arguments are numbers, booleans, and names from a fixed list; the driver
builds every command line.
"""

import json
import math
import re
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any

from driver.child import ChildResult
from driver.server import Operation, OperationContext, OperationError

from media.reframe import (
    SAMPLE_INTERVAL_MS,
    Track,
    crop_expression,
    crop_share,
    detection_size,
    subject_track,
)

FFMPEG = "/opt/ffmpeg/bin/ffmpeg"
FFPROBE = "/opt/ffmpeg/bin/ffprobe"
MAX_SCENE_CUTS = 2000
MAX_FRAMES = 20
DEFAULT_MAX_EDGE_PX = 1280
MAX_SEGMENTS = 10
MAX_SHOT_CUTS = 500
MAX_KEEP_RANGES = 500
# Captions arrive as an ASS file the API built; only its styles and dialogue are read.
MAX_CAPTIONS_BYTES = 4 * 1024 * 1024
CAPTION_SECTIONS = frozenset({"[Script Info]", "[V4+ Styles]", "[Events]"})
OUTPUT_AUDIO_RATE = 48000
FACES_SCRIPT = Path(__file__).with_name("faces.py")
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
FIT_BLUR_RADIUS = 8
# Each segment opens its own decoder; a thread per core each would exhaust the child's memory.
SEGMENT_DECODE_THREADS = 2
SCENE_TIME = re.compile(rb"pts_time:(\d+(?:\.\d+)?)")
# Speech audio: mono 16 kHz Ogg Opus, about 14 MB an hour, read by every transcription provider.
SPEECH_AUDIO_OPTIONS = ("-ac", "1", "-ar", "16000", "-c:a", "libopus", "-b:a", "32k", "-f", "ogg")
MAX_AUDIO_CHUNKS = 32
SILENCE_NOISE = "-35dB"
SILENCE_MIN_SECONDS = "0.3"
SILENCE_EDGE = re.compile(rb"lavfi\.silence_(start|end)=(-?\d+(?:\.\d+)?)")
# A split moves at most this share of a chunk's length to land in a silence.
CHUNK_SPLIT_REACH = 0.1
# Transitions between segments: every named xfade style and acrossfade curve in the pinned
# ffmpeg (xfade's custom expression is code, so it's left out), and "none" for a hard cut.
XFADE_STYLES = frozenset({
    "fade", "fadeblack", "fadewhite", "fadegrays", "fadefast", "fadeslow", "dissolve",
    "distance", "pixelize", "radial", "hblur", "zoomin", "squeezeh", "squeezev",
    "wipeleft", "wiperight", "wipeup", "wipedown", "wipetl", "wipetr", "wipebl", "wipebr",
    "slideleft", "slideright", "slideup", "slidedown",
    "smoothleft", "smoothright", "smoothup", "smoothdown",
    "coverleft", "coverright", "coverup", "coverdown",
    "revealleft", "revealright", "revealup", "revealdown",
    "circleopen", "circleclose", "circlecrop", "rectcrop",
    "vertopen", "vertclose", "horzopen", "horzclose",
    "diagtl", "diagtr", "diagbl", "diagbr",
    "hlslice", "hrslice", "vuslice", "vdslice", "hlwind", "hrwind", "vuwind", "vdwind",
})  # fmt: skip
NO_TRANSITION = "none"
ACROSSFADE_CURVES = frozenset({
    "nofade", "tri", "qsin", "esin", "hsin", "log", "ipar", "qua", "cub", "squ", "cbr",
    "par", "exp", "iqsin", "ihsin", "dese", "desi", "losi", "sinc", "isinc", "quat",
    "quatr", "qsin2", "hsin2",
})  # fmt: skip
MIN_TRANSITION_MS = 100
MAX_TRANSITION_MS = 3000
MAX_FADE_MS = 3000
# A source shorter than its range is padded with its last frame for at most this long.
END_PAD_SECONDS = 1


def _arguments(
    arguments: dict[str, Any],
    *,
    required: dict[str, type],
    optional: dict[str, type] | None = None,
) -> dict[str, Any]:
    """Checks argument names and exact types.

    Strings appear only in transitions, whose names the operation checks against fixed lists.
    """
    optional = optional or {}
    unknown = set(arguments) - set(required) - set(optional)
    missing = set(required) - set(arguments)
    if unknown or missing:
        raise OperationError("invalid_request", "The operation has the wrong arguments.")
    for name, value in arguments.items():
        expected = required.get(name) or optional[name]
        if expected is list:
            if not isinstance(value, list) or any(type(item) is not int for item in value):
                raise OperationError("invalid_request", f"{name} must be a list of integers.")
        elif expected == list[list[int]]:
            if not isinstance(value, list) or any(
                not isinstance(row, list) or any(type(item) is not int for item in row)
                for row in value
            ):
                raise OperationError("invalid_request", f"{name} must be lists of integers.")
        elif expected == list[tuple[str, int, str]]:
            if not isinstance(value, list) or any(
                not isinstance(row, list) or [type(item) for item in row] != [str, int, str]
                for row in value
            ):
                raise OperationError("invalid_request", f"{name} must be [name, number, name].")
        elif expected is float:
            if type(value) not in {int, float}:
                raise OperationError("invalid_request", f"{name} must be a number.")
        elif type(value) is not expected:
            raise OperationError("invalid_request", f"{name} has the wrong type.")
    return arguments


def _range(arguments: dict[str, Any]) -> tuple[int | None, int | None]:
    start, end = arguments.get("start_ms"), arguments.get("end_ms")
    if start is not None and start < 0:
        raise OperationError("invalid_request", "start_ms must not be negative.")
    if end is not None and end <= (start or 0):
        raise OperationError("invalid_request", "end_ms must be after start_ms.")
    return start, end


def _seconds(milliseconds: int) -> str:
    return f"{milliseconds / 1000:.3f}"


def _range_options(start: int | None, end: int | None) -> list[str]:
    options = []
    if start is not None:
        options += ["-ss", _seconds(start)]
    if end is not None:
        options += ["-to", _seconds(end)]
    return options


def _ffmpeg(context: OperationContext, *options: str) -> None:
    result = context.run([FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", *options])
    _require_success(result)


def _ffprobe(context: OperationContext, *options: str) -> dict[str, Any]:
    result = context.run([FFPROBE, "-v", "error", "-print_format", "json", *options])
    _require_success(result)
    try:
        return json.loads(result.stdout_path.read_bytes())
    except json.JSONDecodeError as exc:
        raise OperationError("invalid_media", "The video couldn't be read.") from exc


def _require_success(result: ChildResult) -> None:
    if result.returncode == 0:
        return
    if result.signal is not None or "Cannot allocate memory" in result.stderr_tail:
        raise OperationError("resource_limit", "The operation exceeded the renderer's limits.")
    raise OperationError("invalid_media", "The video couldn't be read.")


def _probe_file(context: OperationContext, path: str) -> dict[str, Any]:
    return _summarise_probe(_ffprobe(context, "-show_format", "-show_streams", path))


def _summarise_probe(report: dict[str, Any]) -> dict[str, Any]:
    streams = report.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video" and not _is_cover(s)), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    try:
        duration = float((report.get("format") or {}).get("duration") or 0)
    except ValueError:
        duration = 0
    return {
        "duration_ms": round(duration * 1000),
        "width": video.get("width"),
        "height": video.get("height"),
        "fps": _frame_rate(video.get("avg_frame_rate")),
        "video_codec": video.get("codec_name"),
        "has_audio": audio is not None,
        "audio_codec": audio.get("codec_name") if audio else None,
        "rotation": _rotation(video),
    }


def _is_cover(stream: dict[str, Any]) -> bool:
    return bool((stream.get("disposition") or {}).get("attached_pic"))


def _frame_rate(value: Any) -> float | None:
    try:
        rate = Fraction(str(value))
    except (ValueError, ZeroDivisionError):
        return None
    return round(float(rate), 3) if rate > 0 else None


def _rotation(stream: dict[str, Any]) -> int:
    for item in stream.get("side_data_list") or []:
        if "rotation" in item:
            return int(item["rotation"]) % 360
    return 0


def _require_video(summary: dict[str, Any]) -> None:
    if summary["video_codec"] is None or summary["duration_ms"] <= 0:
        raise OperationError("no_video", "The file has no video stream.")


def _clamp_range(
    summary: dict[str, Any], start: int | None, end: int | None
) -> tuple[int | None, int | None]:
    """Requires the start before the end of the video and trims the end to it."""
    duration = summary["duration_ms"]
    if start is not None and start >= duration:
        raise OperationError("invalid_request", "start_ms is past the end of the video.")
    return start, None if end is None else min(end, duration)


# probe


def _run_probe(context: OperationContext, arguments: dict[str, Any]) -> dict[str, Any]:
    # Container metadata can sit anywhere in the file, so probe the whole input.
    return _probe_file(context, context.fetch_input().name)


# scene_cuts


def _validate_scene_cuts(arguments: dict[str, Any]) -> dict[str, Any]:
    _arguments(
        arguments,
        required={"threshold": float},
        optional={"start_ms": int, "end_ms": int, "max_cuts": int},
    )
    if not 0.05 <= arguments["threshold"] <= 0.95:
        raise OperationError("invalid_request", "threshold must be between 0.05 and 0.95.")
    if not 1 <= arguments.get("max_cuts", MAX_SCENE_CUTS) <= MAX_SCENE_CUTS:
        raise OperationError("invalid_request", f"max_cuts must be 1 to {MAX_SCENE_CUTS}.")
    _range(arguments)
    return arguments


def _run_scene_cuts(context: OperationContext, arguments: dict[str, Any]) -> dict[str, Any]:
    start, end = arguments.get("start_ms"), arguments.get("end_ms")
    path = context.fetch_input()
    summary = _probe_file(context, path.name)
    _require_video(summary)
    start, end = _clamp_range(summary, start, end)
    threshold = f"{arguments['threshold']:.3f}"
    _ffmpeg(
        context,
        *_range_options(start, end),
        "-i",
        path.name,
        "-an",
        "-sn",
        "-dn",
        "-vf",
        f"scale=320:-2,select=gt(scene\\,{threshold}),metadata=mode=print:file=scenes.txt",
        "-f",
        "null",
        "-",
    )
    scenes = context.workdir / "scenes.txt"
    offset = start or 0
    cuts = []
    if scenes.is_file():
        for match in SCENE_TIME.finditer(scenes.read_bytes()):
            cuts.append(offset + round(float(match.group(1)) * 1000))
            if len(cuts) >= arguments.get("max_cuts", MAX_SCENE_CUTS):
                break
    return {"cuts_ms": cuts, "duration_ms": summary["duration_ms"]}


# cut


def _validate_cut(arguments: dict[str, Any]) -> dict[str, Any]:
    _arguments(
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
    segments = arguments["segments"]
    if not 1 <= len(segments) <= MAX_SEGMENTS or any(len(item) != 3 for item in segments):
        raise OperationError(
            "invalid_request", f"segments must list 1 to {MAX_SEGMENTS} [input, start, end]."
        )
    for _, start, end in segments:
        _range({"start_ms": start, "end_ms": end})
    inputs = {item[0] for item in segments}
    if inputs != set(range(len(inputs))):
        raise OperationError("invalid_request", "segments must use every input from 0.")
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
    _validate_keep(arguments)
    _validate_transitions(arguments)
    return arguments


def _validate_transitions(arguments: dict[str, Any]) -> None:
    """One [style, duration_ms, audio curve] per junction between segments, by name."""
    transitions = arguments.get("transitions", [])
    if transitions and len(transitions) != len(arguments["segments"]) - 1:
        raise OperationError("invalid_request", "transitions must list one per junction.")
    for style, duration, curve in transitions:
        if style not in XFADE_STYLES | {NO_TRANSITION} or curve not in ACROSSFADE_CURVES:
            raise OperationError("invalid_request", "A transition isn't one the renderer offers.")
        if style == NO_TRANSITION:
            if duration != 0:
                raise OperationError("invalid_request", "A hard cut has no duration.")
        elif not MIN_TRANSITION_MS <= duration <= MAX_TRANSITION_MS:
            raise OperationError(
                "invalid_request",
                f"A transition must last {MIN_TRANSITION_MS} to {MAX_TRANSITION_MS} ms.",
            )
    for name in ("fade_in_ms", "fade_out_ms"):
        if not 0 <= arguments.get(name, 0) <= MAX_FADE_MS:
            raise OperationError("invalid_request", f"{name} must be 0 to {MAX_FADE_MS}.")


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


def _cut_input_count(arguments: dict[str, Any]) -> int:
    # The captions file, when there is one, follows the videos.
    return _video_input_count(arguments) + int(arguments.get("captions", False))


def _run_cut(context: OperationContext, arguments: dict[str, Any]) -> dict[str, Any]:
    """Joins segments from one or more inputs into one H.264 and AAC MP4 at a fixed size.

    Every segment is scaled to the output size and frame rate, and 48 kHz stereo, with
    silence for an input without audio, so mismatched sources join cleanly. ``keep``
    drops the frames between its ranges, and ``captions`` burns in the last input's ASS file.
    """
    summaries = []
    for index in range(_video_input_count(arguments)):
        summary = _probe_file(context, context.fetch_input(index).name)
        _require_video(summary)
        summaries.append(summary)
    width, height, fps = arguments["width"], arguments["height"], arguments["fps"]
    tracks = _subject_tracks(context, arguments, summaries) if arguments.get("reframe") else {}
    keep: dict[int, list[tuple[int, int]]] = {}
    for position, first, end in arguments.get("keep", []):
        keep.setdefault(position, []).append((first, end))
    samples = round(OUTPUT_AUDIO_RATE / fps)
    options, filters, lengths = [], [], []
    for position, (index, start, end) in enumerate(arguments["segments"]):
        summary = summaries[index]
        start, end = _clamp_range(summary, start, end)
        frames = _frame_count(end - start, fps)
        lengths.append(sum(last - first for first, last in keep.get(position, [])) or frames)
        options += [
            *_range_options(start, end),
            "-threads",
            str(SEGMENT_DECODE_THREADS),
            "-i",
            context.input_path(index).name,
        ]
        if arguments["fit"]:
            framing = _fit_filter(width, height, position)
        elif position in tracks:
            framing = _follow_filter(width, height, *tracks[position])
        else:
            framing = _fill_filter(width, height)
        video_keep, audio_keep = _keep_filters(keep.get(position), fps)
        # Both streams last exactly the segment's frames, so transitions line up.
        filters.append(
            f"[{position}:v:0]{framing},fps={fps},format=yuv420p,"
            f"tpad=stop_mode=clone:stop_duration={END_PAD_SECONDS},trim=end_frame={frames},"
            f"setpts=PTS-STARTPTS{video_keep}[v{position}]"
        )
        audio = (
            f"[{position}:a:0]"
            if summary["has_audio"]
            else f"anullsrc=r={OUTPUT_AUDIO_RATE}:cl=stereo,"
        )
        filters.append(
            f"{audio}aresample={OUTPUT_AUDIO_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"apad,atrim=end_sample={frames * samples},asetpts=PTS-STARTPTS{audio_keep}[a{position}]"
        )
    total = _join(filters, lengths, arguments.get("transitions", []), fps)
    video = "[joined]"
    if arguments.get("captions"):
        captions = _captions_input(context, len(summaries))
        filters.append(f"{video}ass=filename={captions.name}[captioned]")
        video = "[captioned]"
    filters += _fades(video, arguments, total, fps)
    output = context.output_path(0)
    _ffmpeg(
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
    return _probe_file(context, output.name)


def _frame_count(duration_ms: int, fps: int) -> int:
    return math.ceil(duration_ms * fps / 1000)


def _join(filters: list[str], lengths: list[int], transitions: list[list[Any]], fps: int) -> int:
    """Joins the segments into [joined] and [mixed], returning the clip's length in frames.

    A transition overlaps the end of one segment with the start of the next: xfade blends the
    video and acrossfade the audio over the same frames.
    """
    count = len(lengths)
    if all(style == NO_TRANSITION for style, _, _ in transitions):
        pairs = "".join(f"[v{position}][a{position}]" for position in range(count))
        filters.append(f"{pairs}concat=n={count}:v=1:a=1[joined][mixed]")
        return sum(lengths)
    samples = round(OUTPUT_AUDIO_RATE / fps)
    overlaps = [
        0 if style == NO_TRANSITION else max(1, round(duration * fps / 1000))
        for style, duration, _ in transitions
    ]
    edges = [0, *overlaps, 0]
    if any(edges[position] + edges[position + 1] > lengths[position] for position in range(count)):
        raise OperationError("invalid_request", "A transition is longer than its segments.")
    video, audio, elapsed = "[v0]", "[a0]", lengths[0]
    for position, ((style, _, curve), overlap) in enumerate(
        zip(transitions, overlaps, strict=True), start=1
    ):
        last = position == count - 1
        joined_video = "[joined]" if last else f"[jv{position}]"
        joined_audio = "[mixed]" if last else f"[ja{position}]"
        if overlap == 0:
            filters.append(
                f"{video}{audio}[v{position}][a{position}]concat=n=2:v=1:a=1"
                f"{joined_video}{joined_audio}"
            )
        else:
            filters.append(
                f"{video}[v{position}]xfade=transition={style}:"
                f"duration={overlap / fps:.6f}:offset={(elapsed - overlap) / fps:.6f}{joined_video}"
            )
            filters.append(
                f"{audio}[a{position}]acrossfade=ns={overlap * samples}:c1={curve}:c2={curve}"
                f"{joined_audio}"
            )
        video, audio = joined_video, joined_audio
        elapsed += lengths[position] - overlap
    return elapsed


def _fades(video: str, arguments: dict[str, Any], total: int, fps: int) -> list[str]:
    """Fades the clip in from black and silence, and out to them, ending at [v] and [a]."""
    fade_in = round(arguments.get("fade_in_ms", 0) * fps / 1000)
    fade_out = round(arguments.get("fade_out_ms", 0) * fps / 1000)
    if fade_in + fade_out > total:
        raise OperationError("invalid_request", "The fades are longer than the clip.")
    samples = round(OUTPUT_AUDIO_RATE / fps)
    video_fades, audio_fades = [], []
    if fade_in:
        video_fades.append(f"fade=t=in:s=0:n={fade_in}")
        audio_fades.append(f"afade=t=in:ss=0:ns={fade_in * samples}")
    if fade_out:
        video_fades.append(f"fade=t=out:s={total - fade_out}:n={fade_out}")
        audio_fades.append(f"afade=t=out:ss={(total - fade_out) * samples}:ns={fade_out * samples}")
    return [
        f"{video}{','.join(video_fades) or 'null'}[v]",
        f"[mixed]{','.join(audio_fades) or 'anull'}[a]",
    ]


def _keep_filters(ranges: list[tuple[int, int]] | None, fps: int) -> tuple[str, str]:
    """Keeps only the given output frames of a segment, and the audio under them.

    Audio is cut into frames one video frame long, so both streams select the same indices
    and stay in sync however many pauses are removed.
    """
    if not ranges:
        return "", ""
    chosen = "+".join(f"between(n\\,{first}\\,{end - 1})" for first, end in ranges)
    samples = round(OUTPUT_AUDIO_RATE / fps)
    return (
        f",select={chosen},setpts=N/FRAME_RATE/TB",
        f",asetnsamples=n={samples}:p=0,aselect={chosen},asetpts=N/SR/TB",
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


def _fill_filter(width: int, height: int) -> str:
    # Centre crop: fill the frame and trim what overhangs.
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1"
    )


def _fit_filter(width: int, height: int, position: int) -> str:
    # The whole frame over a blurred, filled copy of itself; blurring a small copy is cheap.
    small_width, small_height = max(2, width // 8 // 2 * 2), max(2, height // 8 // 2 * 2)
    radius = max(1, min(FIT_BLUR_RADIUS, min(small_width, small_height) // 4))
    return (
        f"split[back{position}][front{position}];"
        f"[back{position}]scale={small_width}:{small_height}:force_original_aspect_ratio=increase,"
        f"crop={small_width}:{small_height},boxblur={radius}:2,scale={width}:{height},"
        f"setsar=1[blur{position}];"
        f"[front{position}]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"setsar=1[sharp{position}];"
        f"[blur{position}][sharp{position}]overlay=(W-w)/2:(H-h)/2"
    )


def _follow_filter(width: int, height: int, axis: int, track: Track) -> str:
    # Crops the source to the output's shape, moving along one axis as the track says.
    position = crop_expression(track)
    x, y = (position, "0.5") if axis == 0 else ("0.5", position)
    return (
        f"setpts=PTS-STARTPTS,crop=w=min(iw\\,trunc(ih*{width}/{height}/2)*2):"
        f"h=min(ih\\,trunc(iw*{height}/{width}/2)*2):x=(iw-ow)*({x}):y=(ih-oh)*({y}),"
        f"scale={width}:{height},setsar=1"
    )


def _subject_tracks(
    context: OperationContext, arguments: dict[str, Any], summaries: list[dict[str, Any]]
) -> dict[int, tuple[int, Track]]:
    """Finds faces in each segment the crop can travel across and plans its (axis, track)."""
    output = (arguments["width"], arguments["height"])
    sampled: dict[tuple[int, int], list[tuple[int, int, float, int, list[int]]]] = {}
    for position, (index, start, end) in enumerate(arguments["segments"]):
        summary = summaries[index]
        source = _upright_size(summary)
        if source is None:
            continue
        shares = crop_share(source, output)
        if min(shares) >= 1:
            continue
        start, end = _clamp_range(summary, start, end)
        size = detection_size(*source)
        _ffmpeg(
            context,
            *_range_options(start, end),
            "-threads",
            str(SEGMENT_DECODE_THREADS),
            "-i",
            context.input_path(index).name,
            "-an",
            "-sn",
            "-dn",
            "-vf",
            f"fps={1000 // SAMPLE_INTERVAL_MS},scale={size[0]}:{size[1]},format=bgr24",
            "-f",
            "rawvideo",
            f"frames-{position}.raw",
        )
        axis = 0 if shares[0] < 1 else 1
        cuts = [
            time - start for cut_input, time in arguments.get("shot_cuts", []) if cut_input == index
        ]
        sampled.setdefault(size, []).append((position, axis, shares[axis], end - start, cuts))

    tracks = {}
    for size, segments in sampled.items():
        files = [context.workdir / f"frames-{segment[0]}.raw" for segment in segments]
        found = _faces(context, size, files)
        for (position, axis, share, duration_ms, cuts), samples in zip(
            segments, found, strict=True
        ):
            tracks[position] = (
                axis,
                subject_track(
                    samples,
                    axis=axis,
                    frame_size=size,
                    share=share,
                    shot_cuts_ms=cuts,
                    duration_ms=duration_ms,
                ),
            )
        for path in files:
            path.unlink()
    return tracks


def _faces(
    context: OperationContext, size: tuple[int, int], files: list[Path]
) -> list[list[list[list[float]]]]:
    """Runs YuNet in its own isolated child and checks the shape of what it reports."""
    result = context.run(
        [sys.executable, "-I", str(FACES_SCRIPT), str(size[0]), str(size[1])]
        + [path.name for path in files]
    )
    _require_success(result)
    try:
        found = json.loads(result.stdout_path.read_bytes())
    except json.JSONDecodeError as exc:
        raise OperationError("invalid_media", "The video couldn't be read.") from exc
    valid = (
        isinstance(found, list)
        and len(found) == len(files)
        and all(
            isinstance(frames, list)
            and all(
                isinstance(faces, list)
                and all(
                    isinstance(face, list)
                    and len(face) == 4
                    and all(type(value) in {int, float} for value in face)
                    for face in faces
                )
                for faces in frames
            )
            for frames in found
        )
    )
    if not valid:
        raise OperationError("invalid_media", "The video couldn't be read.")
    return found


def _upright_size(summary: dict[str, Any]) -> tuple[int, int] | None:
    width, height = summary["width"], summary["height"]
    if not width or not height:
        return None
    return (height, width) if summary["rotation"] in {90, 270} else (width, height)


# extract_audio


def _validate_extract_audio(arguments: dict[str, Any]) -> dict[str, Any]:
    _arguments(arguments, required={}, optional={"start_ms": int, "end_ms": int, "chunks": int})
    if not 1 <= arguments.get("chunks", 1) <= MAX_AUDIO_CHUNKS:
        raise OperationError("invalid_request", f"chunks must be 1 to {MAX_AUDIO_CHUNKS}.")
    _range(arguments)
    return arguments


def _run_extract_audio(context: OperationContext, arguments: dict[str, Any]) -> dict[str, Any]:
    start, end = arguments.get("start_ms"), arguments.get("end_ms")
    path = context.fetch_input()
    summary = _probe_file(context, path.name)
    if not summary["has_audio"]:
        raise OperationError("no_audio", "The video has no audio.")
    start, end = _clamp_range(summary, start, end)
    chunks = arguments.get("chunks", 1)
    audio = context.output_path(0) if chunks == 1 else context.workdir / "audio.ogg"
    _ffmpeg(
        context,
        *_range_options(start, end),
        "-i",
        path.name,
        "-map",
        "0:a:0",
        "-vn",
        "-af",
        f"silencedetect=noise={SILENCE_NOISE}:duration={SILENCE_MIN_SECONDS},"
        "ametadata=mode=print:file=silences.txt",
        *SPEECH_AUDIO_OPTIONS,
        audio.name,
    )
    duration = _probe_file(context, audio.name)["duration_ms"]
    bounds = [0, *_chunk_bounds(duration, chunks, _silences(context)), duration]
    if chunks > 1:
        # Re-encoding keeps each chunk's start exact, so word times offset cleanly.
        for index in range(chunks):
            _ffmpeg(
                context,
                *_range_options(bounds[index], bounds[index + 1]),
                "-i",
                audio.name,
                *SPEECH_AUDIO_OPTIONS,
                context.output_path(index).name,
            )
    offset = start or 0
    return {
        "duration_ms": duration,
        "chunks_ms": [
            [offset + bounds[index], offset + bounds[index + 1]] for index in range(chunks)
        ],
    }


def _silences(context: OperationContext) -> list[tuple[int, int]]:
    report = context.workdir / "silences.txt"
    if not report.is_file():
        return []
    silences, opened = [], None
    for match in SILENCE_EDGE.finditer(report.read_bytes()):
        time_ms = round(float(match.group(2)) * 1000)
        if match.group(1) == b"start":
            opened = time_ms
        elif opened is not None:
            silences.append((opened, time_ms))
            opened = None
    return silences


def _chunk_bounds(duration_ms: int, chunks: int, silences: list[tuple[int, int]]) -> list[int]:
    """Splits near equal shares, moving each split into the longest silence close by."""
    share = duration_ms / chunks
    reach = share * CHUNK_SPLIT_REACH
    bounds = []
    for index in range(1, chunks):
        target = share * index
        nearby = [gap for gap in silences if abs((gap[0] + gap[1]) / 2 - target) <= reach]
        if nearby:
            gap_start, gap_end = max(nearby, key=lambda gap: gap[1] - gap[0])
            bounds.append((gap_start + gap_end) // 2)
        else:
            bounds.append(round(target))
    return bounds


# frames


def _validate_frames(arguments: dict[str, Any]) -> dict[str, Any]:
    _arguments(arguments, required={"times_ms": list}, optional={"max_edge_px": int})
    times = arguments["times_ms"]
    if not 1 <= len(times) <= MAX_FRAMES or any(time < 0 for time in times):
        raise OperationError("invalid_request", f"times_ms must list 1 to {MAX_FRAMES} times.")
    if not 64 <= arguments.get("max_edge_px", DEFAULT_MAX_EDGE_PX) <= 1920:
        raise OperationError("invalid_request", "max_edge_px must be 64 to 1920.")
    return arguments


def _run_frames(context: OperationContext, arguments: dict[str, Any]) -> dict[str, Any]:
    path = context.fetch_input()
    summary = _probe_file(context, path.name)
    _require_video(summary)
    # A frame exists only strictly before the end.
    if any(time >= summary["duration_ms"] for time in arguments["times_ms"]):
        raise OperationError("invalid_request", "A time is past the end of the video.")
    edge = arguments.get("max_edge_px", DEFAULT_MAX_EDGE_PX)
    scale = (
        f"scale=w='min({edge},iw)':h='min({edge},ih)':force_original_aspect_ratio=decrease,"
        "format=yuvj420p"
    )
    for index, time_ms in enumerate(arguments["times_ms"]):
        _ffmpeg(
            context,
            "-ss",
            _seconds(time_ms),
            "-i",
            path.name,
            "-frames:v",
            "1",
            "-vf",
            scale,
            "-q:v",
            "3",
            "-c:v",
            "mjpeg",
            "-f",
            "image2",
            "-update",
            "1",
            context.output_path(index).name,
        )
    return {"times_ms": arguments["times_ms"]}


OPERATIONS: dict[str, Operation] = {
    "probe": Operation(
        validate=lambda arguments: _arguments(arguments, required={}),
        output_count=lambda arguments: 0,
        run=_run_probe,
    ),
    "scene_cuts": Operation(
        validate=_validate_scene_cuts, output_count=lambda arguments: 0, run=_run_scene_cuts
    ),
    "cut": Operation(
        validate=_validate_cut,
        output_count=lambda arguments: 1,
        run=_run_cut,
        input_count=_cut_input_count,
    ),
    "extract_audio": Operation(
        validate=_validate_extract_audio,
        output_count=lambda arguments: arguments.get("chunks", 1),
        run=_run_extract_audio,
    ),
    "frames": Operation(
        validate=_validate_frames,
        output_count=lambda arguments: len(arguments["times_ms"]),
        run=_run_frames,
    ),
}
