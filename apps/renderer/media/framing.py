# apps/renderer/media/framing.py

"""Fitting each segment to the output frame: fill, fit over a blur, or follow the subject."""

import sys
from pathlib import Path
from typing import Any

from driver.server import OperationContext, OperationError

from media.ffmpeg import clamp_range, read_json, run_ffmpeg, segment_input
from media.reframe import (
    SAMPLE_INTERVAL_MS,
    Track,
    crop_expression,
    crop_share,
    detection_size,
    subject_track,
)

FIT_BLUR_RADIUS = 8
FACES_SCRIPT = Path(__file__).with_name("faces.py")


def fill_filter(width: int, height: int) -> str:
    # Centre crop: fill the frame and trim what overhangs.
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1"
    )


def fit_filter(width: int, height: int, position: int) -> str:
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


def follow_filter(width: int, height: int, axis: int, track: Track) -> str:
    # Crops the source to the output's shape, moving along one axis as the track says.
    position = crop_expression(track)
    x, y = (position, "0.5") if axis == 0 else ("0.5", position)
    return (
        f"setpts=PTS-STARTPTS,crop=w=min(iw\\,trunc(ih*{width}/{height}/2)*2):"
        f"h=min(ih\\,trunc(iw*{height}/{width}/2)*2):x=(iw-ow)*({x}):y=(ih-oh)*({y}),"
        f"scale={width}:{height},setsar=1"
    )


def subject_tracks(
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
        start, end = clamp_range(summary, start, end)
        size = detection_size(*source)
        run_ffmpeg(
            context,
            *segment_input(start, end, context.input_path(index)),
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
    found = read_json(
        context.run(
            [sys.executable, "-I", str(FACES_SCRIPT), str(size[0]), str(size[1])]
            + [path.name for path in files]
        )
    )
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
