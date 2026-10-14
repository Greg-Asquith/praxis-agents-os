# apps/renderer/media/extract_audio.py

"""The extract_audio operation: speech audio, split into chunks at silences."""

import re
from typing import Any

from driver.server import OperationContext, OperationError

from media.ffmpeg import (
    check_arguments,
    check_range,
    clamp_range,
    probe_file,
    range_options,
    run_ffmpeg,
)

# Mono 16 kHz Ogg Opus, about 14 MB an hour, read by every transcription provider.
SPEECH_AUDIO_OPTIONS = ("-ac", "1", "-ar", "16000", "-c:a", "libopus", "-b:a", "32k", "-f", "ogg")
MAX_AUDIO_CHUNKS = 32
SILENCE_NOISE = "-35dB"
SILENCE_MIN_SECONDS = "0.3"
SILENCE_EDGE = re.compile(rb"lavfi\.silence_(start|end)=(-?\d+(?:\.\d+)?)")
# A split moves at most this share of a chunk's length to land in a silence.
CHUNK_SPLIT_REACH = 0.1


def validate_extract_audio(arguments: dict[str, Any]) -> dict[str, Any]:
    check_arguments(
        arguments, required={}, optional={"start_ms": int, "end_ms": int, "chunks": int}
    )
    if not 1 <= arguments.get("chunks", 1) <= MAX_AUDIO_CHUNKS:
        raise OperationError("invalid_request", f"chunks must be 1 to {MAX_AUDIO_CHUNKS}.")
    check_range(arguments)
    return arguments


def run_extract_audio(context: OperationContext, arguments: dict[str, Any]) -> dict[str, Any]:
    path = context.fetch_input()
    summary = probe_file(context, path.name)
    if not summary["has_audio"]:
        raise OperationError("no_audio", "The video has no audio.")
    start, end = clamp_range(summary, arguments.get("start_ms"), arguments.get("end_ms"))
    chunks = arguments.get("chunks", 1)
    audio = context.output_path(0) if chunks == 1 else context.workdir / "audio.ogg"
    run_ffmpeg(
        context,
        *range_options(start, end),
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
    duration = probe_file(context, audio.name)["duration_ms"]
    bounds = [0, *_chunk_bounds(duration, chunks, _silences(context)), duration]
    if chunks > 1:
        # Re-encoding keeps each chunk's start exact, so word times offset cleanly.
        for index in range(chunks):
            run_ffmpeg(
                context,
                *range_options(bounds[index], bounds[index + 1]),
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
