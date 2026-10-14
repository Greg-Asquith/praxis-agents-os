# apps/renderer/media/frames.py

"""The frames operation: one bounded JPEG per requested time."""

from typing import Any

from driver.server import OperationContext, OperationError

from media.ffmpeg import check_arguments, probe_file, require_video, run_ffmpeg, seconds

MAX_FRAMES = 20
MIN_FRAME_EDGE_PX = 64
MAX_FRAME_EDGE_PX = 1920
DEFAULT_MAX_EDGE_PX = 1280


def validate_frames(arguments: dict[str, Any]) -> dict[str, Any]:
    check_arguments(arguments, required={"times_ms": list[int]}, optional={"max_edge_px": int})
    times = arguments["times_ms"]
    if not 1 <= len(times) <= MAX_FRAMES or any(time < 0 for time in times):
        raise OperationError("invalid_request", f"times_ms must list 1 to {MAX_FRAMES} times.")
    if (
        not MIN_FRAME_EDGE_PX
        <= arguments.get("max_edge_px", DEFAULT_MAX_EDGE_PX)
        <= MAX_FRAME_EDGE_PX
    ):
        raise OperationError(
            "invalid_request", f"max_edge_px must be {MIN_FRAME_EDGE_PX} to {MAX_FRAME_EDGE_PX}."
        )
    return arguments


def run_frames(context: OperationContext, arguments: dict[str, Any]) -> dict[str, Any]:
    path = context.fetch_input()
    summary = probe_file(context, path.name)
    require_video(summary)
    # A frame exists only strictly before the end.
    if any(time >= summary["duration_ms"] for time in arguments["times_ms"]):
        raise OperationError("invalid_request", "A time is past the end of the video.")
    edge = arguments.get("max_edge_px", DEFAULT_MAX_EDGE_PX)
    scale = (
        f"scale=w='min({edge},iw)':h='min({edge},ih)':force_original_aspect_ratio=decrease,"
        "format=yuvj420p"
    )
    for index, time_ms in enumerate(arguments["times_ms"]):
        run_ffmpeg(
            context,
            "-ss",
            seconds(time_ms),
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
