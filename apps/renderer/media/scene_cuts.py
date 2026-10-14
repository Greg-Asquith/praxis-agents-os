# apps/renderer/media/scene_cuts.py

"""The scene_cuts operation: times where the picture changes past a threshold."""

import re
from typing import Any

from driver.server import OperationContext, OperationError

from media.ffmpeg import (
    check_arguments,
    check_range,
    clamp_range,
    probe_file,
    range_options,
    require_video,
    run_ffmpeg,
)

MAX_SCENE_CUTS = 2000
MIN_SCENE_THRESHOLD = 0.05
MAX_SCENE_THRESHOLD = 0.95
SCENE_TIME = re.compile(rb"pts_time:(\d+(?:\.\d+)?)")


def validate_scene_cuts(arguments: dict[str, Any]) -> dict[str, Any]:
    check_arguments(
        arguments,
        required={"threshold": float},
        optional={"start_ms": int, "end_ms": int, "max_cuts": int},
    )
    if not MIN_SCENE_THRESHOLD <= arguments["threshold"] <= MAX_SCENE_THRESHOLD:
        raise OperationError(
            "invalid_request",
            f"threshold must be between {MIN_SCENE_THRESHOLD} and {MAX_SCENE_THRESHOLD}.",
        )
    if not 1 <= arguments.get("max_cuts", MAX_SCENE_CUTS) <= MAX_SCENE_CUTS:
        raise OperationError("invalid_request", f"max_cuts must be 1 to {MAX_SCENE_CUTS}.")
    check_range(arguments)
    return arguments


def run_scene_cuts(context: OperationContext, arguments: dict[str, Any]) -> dict[str, Any]:
    path = context.fetch_input()
    summary = probe_file(context, path.name)
    require_video(summary)
    start, end = clamp_range(summary, arguments.get("start_ms"), arguments.get("end_ms"))
    threshold = f"{arguments['threshold']:.3f}"
    run_ffmpeg(
        context,
        *range_options(start, end),
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
