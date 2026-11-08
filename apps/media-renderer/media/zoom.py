# apps/media-renderer/media/zoom.py

"""Zooms inside the framed picture: a slow push-in over a segment and punch-ins at jump cuts."""

from collections.abc import Sequence

MIN_ZOOM_PERCENT = 100
MAX_ZOOM_PERCENT = 150
# Every other range kept after pause removal is this much closer, which hides the jump cut.
PUNCH_IN_PERCENT = 110


def zoom_filter(frames: int, zoom: Sequence[int], punched: Sequence[tuple[int, int]]) -> str:
    """Enlarges the centre of each frame by a factor of its frame number in the segment.

    The zoom moves from ``zoom[0]`` to ``zoom[1]`` percent over the segment's ``frames``, and
    frames in the ``punched`` [first, end) ranges are PUNCH_IN_PERCENT closer, up to
    MAX_ZOOM_PERCENT. Returns "" when nothing zooms.
    """
    start, end = zoom
    if start == end == MIN_ZOOM_PERCENT and not punched:
        return ""
    factor = f"{start / 100:g}"
    if end != start:
        factor = f"({factor}+{(end - start) / 100:g}*in/{max(1, frames - 1)})"
    if punched:
        inside = "+".join(f"between(in\\,{first}\\,{last - 1})" for first, last in punched)
        punch, most = PUNCH_IN_PERCENT / 100, MAX_ZOOM_PERCENT / 100
        factor = f"min({most:g}\\,{factor}*if({inside}\\,{punch:g}\\,1))"
    # Sub-pixel corners of the centred 1/factor crop, so a push-in doesn't judder.
    near, far = f"(1-1/{factor})/2", f"(1+1/{factor})/2"
    return (
        f",perspective=x0=W*{near}:y0=H*{near}:x1=W*{far}:y1=H*{near}:"
        f"x2=W*{near}:y2=H*{far}:x3=W*{far}:y3=H*{far}:eval=frame"
    )
