# apps/media-renderer/media/black_bars.py

"""Finding the picture inside letterboxed or pillarboxed footage, so a crop can remove the bars."""

import re

from driver.server import OperationContext

from media.ffmpeg import run_ffmpeg, seconds

SAMPLE_FRAMES = 5
# Bars narrower than this share of an edge are encoder edges, not letterboxing.
MIN_BAR_SHARE = 0.02
# A picture smaller than this share of an edge is more likely a dark scene than bars.
MIN_PICTURE_SHARE = 0.25
CROP_EDGE = re.compile(rb"lavfi\.cropdetect\.(x1|x2|y1|y2)=(-?\d+)")

# (x, y, width, height) of the picture in the upright frame.
Picture = tuple[int, int, int, int]


def find_picture(
    context: OperationContext, index: int, start: int | None, end: int, size: tuple[int, int]
) -> Picture | None:
    """Returns the picture inside black bars across sampled frames of one segment.

    Frames are sampled across ``start`` to ``end`` of input ``index``, whose upright frame is
    ``size``. Only bars on both opposite edges count, and the narrower of the two is removed
    from each, so a dark edge of the picture itself is kept. Returns None when there are none.
    """
    start = start or 0
    times = [
        start + (end - start) * (2 * sample + 1) // (2 * SAMPLE_FRAMES)
        for sample in range(SAMPLE_FRAMES)
    ]
    options, chains = [], ""
    for sample, time in enumerate(times):
        options += ["-ss", seconds(time), "-threads", "1", "-i", context.input_path(index).name]
        chains += f"[{sample}:v:0]trim=end_frame=1[s{sample}];"
    joined = "".join(f"[s{sample}]" for sample in range(SAMPLE_FRAMES))
    report = context.workdir / "bars.txt"
    run_ffmpeg(
        context,
        *options,
        "-filter_complex",
        f"{chains}{joined}concat=n={SAMPLE_FRAMES}:v=1:a=0,"
        f"cropdetect=round=2:skip=0,metadata=mode=print:file={report.name}",
        "-f",
        "null",
        "-",
    )
    edges = _edges(report.read_bytes()) if report.is_file() else None
    report.unlink(missing_ok=True)
    if edges is None:
        return None
    width, height = size
    x1, x2, y1, y2 = edges
    side = _bar(min(x1, width - 1 - x2), width)
    top = _bar(min(y1, height - 1 - y2), height)
    if not side and not top:
        return None
    return side, top, width - 2 * side, height - 2 * top


def picture_crop(picture: Picture | None) -> str:
    """Returns the crop filter, with a trailing comma, that keeps only the picture."""
    if picture is None:
        return ""
    x, y, width, height = picture
    return f"crop={width}:{height}:{x}:{y},"


def _edges(report: bytes) -> tuple[int, int, int, int] | None:
    """The widest picture edges any sampled frame reported; None when every frame was black."""
    found: dict[bytes, list[int]] = {}
    for name, value in CROP_EDGE.findall(report):
        found.setdefault(name, []).append(int(value))
    if set(found) != {b"x1", b"x2", b"y1", b"y2"}:
        return None
    x1, x2, y1, y2 = min(found[b"x1"]), max(found[b"x2"]), min(found[b"y1"]), max(found[b"y2"])
    return (x1, x2, y1, y2) if x2 > x1 and y2 > y1 else None


def _bar(band: int, edge: int) -> int:
    """Rounds a bar up to even pixels; 0 when it's too thin or would leave too little picture."""
    band = max(0, band)
    band += band % 2
    if band < edge * MIN_BAR_SHARE or edge - 2 * band < edge * MIN_PICTURE_SHARE:
        return 0
    return band
