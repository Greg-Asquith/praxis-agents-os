# apps/renderer/media/ffmpeg.py

"""Shared ffmpeg plumbing: isolated runs, probe summaries, ranges, and argument checks."""

import json
from fractions import Fraction
from pathlib import Path
from typing import Any

from driver.child import ChildResult
from driver.server import OperationContext, OperationError

FFMPEG = "/opt/ffmpeg/bin/ffmpeg"
FFPROBE = "/opt/ffmpeg/bin/ffprobe"
OUTPUT_AUDIO_RATE = 48000
# Each segment opens its own decoder; a thread per core each would exhaust the child's memory.
SEGMENT_DECODE_THREADS = 2


def check_arguments(
    arguments: dict[str, Any],
    *,
    required: dict[str, type],
    optional: dict[str, type] | None = None,
) -> dict[str, Any]:
    """Checks argument names and exact types; the only strings are transition names."""
    optional = optional or {}
    unknown = set(arguments) - set(required) - set(optional)
    missing = set(required) - set(arguments)
    if unknown or missing:
        raise OperationError("invalid_request", "The operation has the wrong arguments.")
    for name, value in arguments.items():
        expected = required.get(name) or optional[name]
        if expected == list[int]:
            if not _is_int_list(value):
                raise OperationError("invalid_request", f"{name} must be a list of integers.")
        elif expected == list[list[int]]:
            if not isinstance(value, list) or not all(_is_int_list(row) for row in value):
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


def _is_int_list(value: Any) -> bool:
    return isinstance(value, list) and all(type(item) is int for item in value)


def check_range(arguments: dict[str, Any]) -> tuple[int | None, int | None]:
    start, end = arguments.get("start_ms"), arguments.get("end_ms")
    if start is not None and start < 0:
        raise OperationError("invalid_request", "start_ms must not be negative.")
    if end is not None and end <= (start or 0):
        raise OperationError("invalid_request", "end_ms must be after start_ms.")
    return start, end


def clamp_range(
    summary: dict[str, Any], start: int | None, end: int | None
) -> tuple[int | None, int | None]:
    """Requires the start before the end of the video and trims the end to it."""
    duration = summary["duration_ms"]
    if start is not None and start >= duration:
        raise OperationError("invalid_request", "start_ms is past the end of the video.")
    return start, None if end is None else min(end, duration)


def seconds(milliseconds: int) -> str:
    return f"{milliseconds / 1000:.3f}"


def range_options(start: int | None, end: int | None) -> list[str]:
    options = []
    if start is not None:
        options += ["-ss", seconds(start)]
    if end is not None:
        options += ["-to", seconds(end)]
    return options


def segment_input(start: int | None, end: int | None, path: Path) -> list[str]:
    """Input options that decode one segment of a source with a bounded thread count."""
    return [
        *range_options(start, end),
        "-threads",
        str(SEGMENT_DECODE_THREADS),
        "-i",
        path.name,
    ]


def samples_per_frame(fps: int) -> int:
    return round(OUTPUT_AUDIO_RATE / fps)


def run_ffmpeg(context: OperationContext, *options: str) -> None:
    result = context.run([FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", *options])
    require_success(result)


def require_success(result: ChildResult) -> None:
    if result.returncode == 0:
        return
    if result.signal is not None or "Cannot allocate memory" in result.stderr_tail:
        raise OperationError("resource_limit", "The operation exceeded the renderer's limits.")
    raise OperationError("invalid_media", "The video couldn't be read.")


def read_json(result: ChildResult) -> Any:
    """Returns a successful child's JSON output."""
    require_success(result)
    try:
        return json.loads(result.stdout_path.read_bytes())
    except json.JSONDecodeError as exc:
        raise OperationError("invalid_media", "The video couldn't be read.") from exc


def probe_file(context: OperationContext, path: str) -> dict[str, Any]:
    report = read_json(
        context.run(
            [FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path]
        )
    )
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


def require_video(summary: dict[str, Any]) -> None:
    if summary["video_codec"] is None or summary["duration_ms"] <= 0:
        raise OperationError("no_video", "The file has no video stream.")
