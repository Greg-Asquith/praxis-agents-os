# apps/media-renderer/media/music.py

"""A music bed for cut: one audio input, looped, trimmed, faded, and mixed under the speech."""

from typing import Any

from driver.server import OperationContext, OperationError

from media.ffmpeg import OUTPUT_AUDIO_RATE, probe_file, samples_per_frame, seconds
from media.transitions import MAX_FADE_MS

MAX_MUSIC_VOLUME = 100
MUSIC_OPTIONS = (
    "music_volume", "music_duck", "music_start_ms", "music_fade_in_ms", "music_fade_out_ms",
)  # fmt: skip
# Any speech over -50 dBFS compresses the music hard; blending a fifth of it back unchanged
# caps the drop near 14 dB, so quiet and loud speakers duck it about the same.
DUCK_FILTER = "sidechaincompress=threshold=0.003:ratio=20:attack=20:release=400:mix=0.8"


def validate_music(arguments: dict[str, Any]) -> None:
    """Music options come all together with music, and none without it."""
    given = {name for name in MUSIC_OPTIONS if name in arguments}
    if given != (set(MUSIC_OPTIONS) if arguments.get("music") else set()):
        raise OperationError("invalid_request", "Music needs all its options, and only with music.")
    if not given:
        return
    if not 0 <= arguments["music_volume"] <= MAX_MUSIC_VOLUME:
        raise OperationError("invalid_request", f"music_volume must be 0 to {MAX_MUSIC_VOLUME}.")
    if arguments["music_start_ms"] < 0:
        raise OperationError("invalid_request", "music_start_ms must not be negative.")
    for name in ("music_fade_in_ms", "music_fade_out_ms"):
        if not 0 <= arguments[name] <= MAX_FADE_MS:
            raise OperationError("invalid_request", f"{name} must be 0 to {MAX_FADE_MS}.")


def music_input(
    context: OperationContext, arguments: dict[str, Any], index: int, total: int, fps: int
) -> list[str]:
    """Input options that read the track from its start time, looping it past the clip's end."""
    summary = probe_file(context, context.fetch_input(index).name)
    start = arguments["music_start_ms"]
    if not summary["has_audio"] or summary["duration_ms"] <= 0:
        raise OperationError("no_audio", "The music file has no sound.")
    if start >= summary["duration_ms"]:
        raise OperationError("invalid_request", "music_start_ms is past the end of the track.")
    # A loop restarts at the track's beginning; the read stops a second after the clip ends.
    return [
        "-ss", seconds(start), "-stream_loop", "-1",
        "-t", seconds(total * 1000 // fps + 1000), "-i", context.input_path(index).name,
    ]  # fmt: skip


def mix_music(
    filters: list[str], arguments: dict[str, Any], stream: int, total: int, fps: int
) -> str:
    """Mixes the faded track, ffmpeg input `stream`, under [mixed], lowered while someone talks.

    Returns the mix's label.
    """
    samples = samples_per_frame(fps)
    length = total * samples
    fade_in = round(arguments["music_fade_in_ms"] * OUTPUT_AUDIO_RATE / 1000)
    fade_out = round(arguments["music_fade_out_ms"] * OUTPUT_AUDIO_RATE / 1000)
    if fade_in + fade_out > length:
        raise OperationError("invalid_request", "The music fades are longer than the clip.")
    # The volume reads as loudness: 50 is 12 dB under the track, 25 is 24 dB under.
    gain = (arguments["music_volume"] / MAX_MUSIC_VOLUME) ** 2
    fades = ""
    if fade_in:
        fades += f",afade=t=in:ss=0:ns={fade_in}"
    if fade_out:
        fades += f",afade=t=out:ss={length - fade_out}:ns={fade_out}"
    filters.append(
        f"[{stream}:a:0]aresample={OUTPUT_AUDIO_RATE},"
        f"aformat=sample_fmts=fltp:channel_layouts=stereo,volume={gain:.6f},apad,"
        f"atrim=end_sample={length},asetpts=PTS-STARTPTS{fades}[music]"
    )
    music = "[music]"
    speech = "[mixed]"
    if arguments["music_duck"]:
        filters.append("[mixed]asplit=2[speech][key]")
        filters.append(f"[music][key]{DUCK_FILTER}[ducked]")
        music, speech = "[ducked]", "[speech]"
    filters.append(f"{speech}{music}amix=inputs=2:duration=first:normalize=0[scored]")
    return "[scored]"
