# apps/media-renderer/media/audio.py

"""Audio finishing for cut: voice clean-up per segment and two-pass loudness normalisation."""

import json
import math
import re
from pathlib import Path

from driver.server import OperationContext, OperationError

from media.ffmpeg import FFMPEG, OUTPUT_AUDIO_RATE, require_success

# Rumble cut, steady noise reduced by up to 12 dB, a presence lift, then gentle compression.
VOICE_FILTERS = (
    "highpass=f=80,afftdn=nr=12:nf=-45,equalizer=f=3000:t=q:w=1:g=3,"
    "acompressor=threshold=0.125:ratio=3:attack=20:release=250"
)
# Reels, Shorts, and TikTok play at -14 LUFS; a wide range target keeps most clips linear.
TARGET_LUFS = -14
TARGET_TRUE_PEAK_DB = -1.5
TARGET_RANGE_LU = 20
# Below the EBU R128 absolute gate there is nothing to normalise, such as a silent clip.
SILENCE_LUFS = -70
LOUDNORM = f"loudnorm=I={TARGET_LUFS}:TP={TARGET_TRUE_PEAK_DB}:LRA={TARGET_RANGE_LU}"
LOUDNORM_REPORT = re.compile(r"\{[^{}]*\}")
MEASURED = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")


def normalize_loudness(
    context: OperationContext, mixed: Path, output: Path, audio_options: tuple[str, ...]
) -> float | None:
    """Measures the finished mix, then re-encodes only its audio to the target loudness.

    Returns the clip's integrated loudness, or None for a silent clip, which is kept as it is.
    """
    measured = _loudnorm(
        context, LOUDNORM, MEASURED, "-i", mixed.name, "-vn", "-sn", "-dn", "-f", "null", "-"
    )
    if measured["input_i"] < SILENCE_LUFS:
        mixed.replace(output)
        return None
    second = (
        f"{LOUDNORM}:measured_I={measured['input_i']:.2f}:measured_TP={measured['input_tp']:.2f}:"
        f"measured_LRA={measured['input_lra']:.2f}:"
        f"measured_thresh={measured['input_thresh']:.2f}:"
        f"offset={measured['target_offset']:.2f}:linear=true"
    )
    report = _loudnorm(
        context,
        second,
        ("output_i",),
        "-i",
        mixed.name,
        "-map",
        "0:v:0",
        "-map",
        "0:a:0",
        "-c:v",
        "copy",
        *audio_options,
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        output.name,
    )
    mixed.unlink()
    return round(report["output_i"], 1)


def _loudnorm(
    context: OperationContext, loudnorm: str, keys: tuple[str, ...], *options: str
) -> dict[str, float]:
    """Runs ffmpeg with a loudnorm filter and returns the numbers from the report it logs."""
    # Dynamic mode works at 192 kHz, so resample back to the clip's rate.
    audio_filter = f"{loudnorm}:print_format=json,aresample={OUTPUT_AUDIO_RATE}"
    *inputs, output = options
    result = context.run(
        [
            FFMPEG, "-nostdin", "-hide_banner", "-nostats", "-loglevel", "info",
            *inputs, "-af", audio_filter, output,
        ]
    )  # fmt: skip
    require_success(result)
    try:
        report = json.loads(LOUDNORM_REPORT.findall(result.stderr_tail)[-1])
        return {key: _number(report[key]) for key in keys}
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise OperationError("invalid_media", "The clip's sound couldn't be measured.") from exc


def _number(value: str) -> float:
    """Reads a reported level; silence is reported as -inf."""
    number = float(value)
    if math.isnan(number):
        raise ValueError(value)
    return max(number, -99.0)
