# apps/renderer/media/transitions.py

"""Joining a clip's segments, with hard cuts or crossfades, and fading the whole clip."""

from typing import Any

from driver.server import OperationError

from media.ffmpeg import samples_per_frame

# Every named xfade style and acrossfade curve in the pinned ffmpeg; xfade's custom expression is code.
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


def validate_transitions(arguments: dict[str, Any]) -> None:
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


def join(filters: list[str], lengths: list[int], transitions: list[list[Any]], fps: int) -> int:
    """Joins [vN][aN] into [joined] and [mixed], returning the clip's length in frames."""
    count = len(lengths)
    if all(style == NO_TRANSITION for style, _, _ in transitions):
        pairs = "".join(f"[v{position}][a{position}]" for position in range(count))
        filters.append(f"{pairs}concat=n={count}:v=1:a=1[joined][mixed]")
        return sum(lengths)
    samples = samples_per_frame(fps)
    # A transition overlaps the end of one segment with the start of the next.
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


def fades(video: str, arguments: dict[str, Any], total: int, fps: int) -> list[str]:
    """Fades the clip in from black and silence, and out to them, ending at [v] and [a]."""
    fade_in = round(arguments.get("fade_in_ms", 0) * fps / 1000)
    fade_out = round(arguments.get("fade_out_ms", 0) * fps / 1000)
    if fade_in + fade_out > total:
        raise OperationError("invalid_request", "The fades are longer than the clip.")
    samples = samples_per_frame(fps)
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
