# apps/renderer/media/reframe.py

"""Subject-aware framing: a crop that follows the largest face in each shot.

The crop holds still while the face stays in its middle third, pans when it
leaves, and only jumps at a shot cut. A shot with no face is centred.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

SAMPLE_INTERVAL_MS = 500
DETECTION_LONG_EDGE_PX = 640
PAN_MS = 400
# A frame this close to a cut may belong to either shot, so it's ignored.
CUT_GUARD_MS = 100
CENTRE = 0.5

# A face as YuNet reports it: x, y, width, and height in detection pixels.
Face = Sequence[float]


@dataclass(frozen=True)
class Move:
    """The crop moves to ``position`` between two times; a move with no length is a jump."""

    start_ms: int
    end_ms: int
    position: float


@dataclass(frozen=True)
class Track:
    """Crop positions along the axis it can travel: 0 is one edge, 1 the other."""

    initial: float
    moves: tuple[Move, ...]


def detection_size(width: int, height: int) -> tuple[int, int]:
    """Returns even frame dimensions for face detection, 640 pixels on the long side."""
    scale = DETECTION_LONG_EDGE_PX / max(width, height)
    return max(2, round(width * scale / 2) * 2), max(2, round(height * scale / 2) * 2)


def crop_share(source: tuple[int, int], output: tuple[int, int]) -> tuple[float, float]:
    """Returns the share of the source's width and height a crop filling the output keeps."""
    source_ratio, output_ratio = source[0] / source[1], output[0] / output[1]
    if source_ratio > output_ratio:
        return output_ratio / source_ratio, 1.0
    return 1.0, source_ratio / output_ratio


def subject_track(
    samples: Sequence[Sequence[Face]],
    *,
    axis: int,
    frame_size: tuple[int, int],
    share: float,
    shot_cuts_ms: Sequence[int],
    duration_ms: int,
) -> Track:
    """Plans the crop for one segment from faces sampled every SAMPLE_INTERVAL_MS.

    ``axis`` is 0 when the crop travels across and 1 when it travels down;
    ``share`` is the share of the frame the crop keeps on that axis.
    ``shot_cuts_ms`` are relative to the segment's start.
    """
    cuts = sorted(cut for cut in set(shot_cuts_ms) if 0 < cut < duration_ms)
    detected = [
        (index * SAMPLE_INTERVAL_MS, centre)
        for index, faces in enumerate(samples)
        if (centre := _subject_centre(faces, axis, frame_size[axis])) is not None
    ]
    initial, moves = None, []
    for shot_start, shot_end in pairwise([0, *cuts, duration_ms]):
        first = shot_start + CUT_GUARD_MS if shot_start else 0
        last = shot_end - CUT_GUARD_MS if shot_end < duration_ms else shot_end
        found = [(time_ms, centre) for time_ms, centre in detected if first <= time_ms < last]
        position = _position(found[0][1], share) if found else CENTRE
        if initial is None:
            initial = position
        else:
            moves.append(Move(shot_start, shot_start, position))
        for time_ms, centre in found[1:]:
            crop_centre = position * (1 - share) + share / 2
            target = _position(centre, share)
            # Move only once the subject leaves the crop's middle third and the crop can follow.
            if abs(centre - crop_centre) <= share / 6 or target == position:
                continue
            position = target
            moves.append(Move(time_ms, min(time_ms + PAN_MS, shot_end), position))
    return Track(initial=CENTRE if initial is None else initial, moves=tuple(moves))


def crop_expression(track: Track) -> str:
    """Writes the track as an ffmpeg expression of t, in seconds from the segment's start."""
    terms, previous = [f"{track.initial:.4f}"], track.initial
    for move in track.moves:
        change, previous = move.position - previous, move.position
        if abs(change) < 0.0001:
            continue
        start = move.start_ms / 1000
        if move.end_ms <= move.start_ms:
            ramp = f"gte(t\\,{start:.3f})"
        else:
            ramp = f"clip((t-{start:.3f})/{(move.end_ms - move.start_ms) / 1000:.3f}\\,0\\,1)"
        terms.append(f"({change:+.4f})*{ramp}")
    return "+".join(terms)


def _subject_centre(faces: Sequence[Face], axis: int, extent: int) -> float | None:
    if not faces:
        return None
    largest = max(faces, key=lambda face: face[2] * face[3])
    return (largest[axis] + largest[axis + 2] / 2) / extent


def _position(centre: float, share: float) -> float:
    """Places the crop's centre on the subject, kept inside the frame."""
    return min(1.0, max(0.0, (centre - share / 2) / (1 - share)))
