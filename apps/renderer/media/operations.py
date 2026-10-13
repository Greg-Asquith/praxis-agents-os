# apps/renderer/media/operations.py

"""Media operations. Arguments are numbers only; the driver builds every command line."""

import json
import re
from fractions import Fraction
from typing import Any

from driver.child import ChildResult
from driver.server import Operation, OperationContext, OperationError

FFMPEG = "/opt/ffmpeg/bin/ffmpeg"
FFPROBE = "/opt/ffmpeg/bin/ffprobe"
MAX_SCENE_CUTS = 2000
MAX_FRAMES = 20
DEFAULT_MAX_EDGE_PX = 1280
# Start times within this distance of a keyframe are cut by stream copy.
KEYFRAME_TOLERANCE_MS = 20
KEYFRAME_SEARCH_MS = 1000
COPYABLE_VIDEO_CODECS = {"h264", "hevc"}
SCENE_TIME = re.compile(rb"pts_time:(\d+(?:\.\d+)?)")


def _arguments(
    arguments: dict[str, Any],
    *,
    required: dict[str, type],
    optional: dict[str, type] | None = None,
) -> dict[str, Any]:
    """Checks argument names and exact types. Strings are never accepted."""
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
    _arguments(arguments, required={"start_ms": int, "end_ms": int})
    _range(arguments)
    return arguments


def _starts_on_keyframe(context: OperationContext, path: str, start_ms: int) -> bool:
    if start_ms == 0:
        return True
    search_start = max(0, start_ms - KEYFRAME_SEARCH_MS)
    window = f"{_seconds(search_start)}%{_seconds(start_ms + KEYFRAME_SEARCH_MS)}"
    report = _ffprobe(
        context,
        "-select_streams",
        "v:0",
        "-read_intervals",
        window,
        "-show_entries",
        "packet=pts_time,flags",
        path,
    )
    packets = report.get("packets") or []
    for packet in packets:
        if (
            "K" in packet.get("flags", "")
            and packet.get("pts_time") is not None
            and abs(round(float(packet["pts_time"]) * 1000) - start_ms) <= KEYFRAME_TOLERANCE_MS
        ):
            return True
    return False


def _run_cut(context: OperationContext, arguments: dict[str, Any]) -> dict[str, Any]:
    start, end = arguments["start_ms"], arguments["end_ms"]
    path = context.fetch_input()
    summary = _probe_file(context, path.name)
    _require_video(summary)
    start, end = _clamp_range(summary, start, end)
    copy = (
        summary["video_codec"] in COPYABLE_VIDEO_CODECS
        and summary["audio_codec"] in {None, "aac"}
        and _starts_on_keyframe(context, path.name, start)
    )
    if copy:
        codec_options = ["-c", "copy"]
        if summary["video_codec"] == "hevc":
            codec_options += ["-tag:v", "hvc1"]
    else:
        codec_options = [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
        ]
    output = context.output_path(0)
    _ffmpeg(
        context,
        *_range_options(start, end),
        "-i",
        path.name,
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        *codec_options,
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        output.name,
    )
    clip = _probe_file(context, output.name)
    return {"mode": "copy" if copy else "encode", **clip}


# extract_audio


def _validate_extract_audio(arguments: dict[str, Any]) -> dict[str, Any]:
    _arguments(arguments, required={}, optional={"start_ms": int, "end_ms": int})
    _range(arguments)
    return arguments


def _run_extract_audio(context: OperationContext, arguments: dict[str, Any]) -> dict[str, Any]:
    start, end = arguments.get("start_ms"), arguments.get("end_ms")
    path = context.fetch_input()
    summary = _probe_file(context, path.name)
    if not summary["has_audio"]:
        raise OperationError("no_audio", "The video has no audio.")
    start, end = _clamp_range(summary, start, end)
    output = context.output_path(0)
    # Mono 16 kHz AAC: small, and enough for speech transcription.
    _ffmpeg(
        context,
        *_range_options(start, end),
        "-i",
        path.name,
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "aac",
        "-b:a",
        "64k",
        "-movflags",
        "+faststart",
        "-f",
        "ipod",
        output.name,
    )
    audio = _probe_file(context, output.name)
    return {"duration_ms": audio["duration_ms"]}


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
    "cut": Operation(validate=_validate_cut, output_count=lambda arguments: 1, run=_run_cut),
    "extract_audio": Operation(
        validate=_validate_extract_audio,
        output_count=lambda arguments: 1,
        run=_run_extract_audio,
    ),
    "frames": Operation(
        validate=_validate_frames,
        output_count=lambda arguments: len(arguments["times_ms"]),
        run=_run_frames,
    ),
}
