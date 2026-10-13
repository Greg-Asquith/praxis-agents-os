# apps/api/services/media/snapping.py

"""Snaps model-chosen video ranges to sentence and shot boundaries.

Understanding models place times about a second out, which would cut words
in half. A range keeps the whole sentences it touches, then each cut moves to
a shot boundary close by, so a clip never opens on a frame of the last shot.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

from services.media.domain import TranscriptSentence


@dataclass(frozen=True)
class SnapLimits:
    min_ms: int
    max_ms: int
    shot_tolerance_ms: int


class _Ranged(Protocol):
    @property
    def start_ms(self) -> int: ...
    @property
    def end_ms(self) -> int: ...
    @property
    def score(self) -> int: ...


def snap_range(
    start_ms: int,
    end_ms: int,
    *,
    sentences: Sequence[TranscriptSentence],
    shot_cuts_ms: Sequence[int],
    duration_ms: int,
    limits: SnapLimits,
) -> tuple[int, int] | None:
    """Returns the snapped range, or None when no range within the limits fits."""
    start_ms, end_ms = max(0, start_ms), min(end_ms, duration_ms)
    if end_ms <= start_ms:
        return None
    start_ms = _sentence_start(start_ms, end_ms, sentences)
    end_ms = _sentence_end(start_ms, end_ms, sentences)
    if end_ms - start_ms < limits.min_ms:
        # Too short: run on to the first sentence end that makes it long enough.
        end_ms = next(
            (
                sentence.end_ms
                for sentence in sentences
                if sentence.end_ms > end_ms and sentence.end_ms - start_ms >= limits.min_ms
            ),
            0,
        )
    if not limits.min_ms <= end_ms - start_ms <= limits.max_ms:
        return None
    # A shot boundary wins only when the range still fits after the move.
    start_cut = _nearest_cut(start_ms, shot_cuts_ms, limits)
    if limits.min_ms <= end_ms - start_cut <= limits.max_ms:
        start_ms = start_cut
    end_cut = _nearest_cut(end_ms, shot_cuts_ms, limits)
    if limits.min_ms <= end_cut - start_ms <= limits.max_ms:
        end_ms = end_cut
    return start_ms, end_ms


def shot_count(start_ms: int, end_ms: int, shot_cuts_ms: Sequence[int]) -> int:
    """Counts the shots a range shows."""
    return 1 + sum(1 for cut in shot_cuts_ms if start_ms < cut < end_ms)


def drop_overlaps[T: _Ranged](moments: Iterable[T]) -> list[T]:
    """Keeps the higher-scored of any two overlapping moments, best first."""
    kept: list[T] = []
    for moment in sorted(moments, key=lambda item: item.score, reverse=True):
        if all(
            moment.end_ms <= other.start_ms or other.end_ms <= moment.start_ms for other in kept
        ):
            kept.append(moment)
    return kept


def _sentence_start(start_ms: int, end_ms: int, sentences: Sequence[TranscriptSentence]) -> int:
    # Back to the start of the sentence the cut falls in; from a pause, on to the next sentence.
    for sentence in sentences:
        if sentence.start_ms <= start_ms < sentence.end_ms:
            return sentence.start_ms
        if start_ms < sentence.start_ms < end_ms:
            return sentence.start_ms
    return start_ms


def _sentence_end(start_ms: int, end_ms: int, sentences: Sequence[TranscriptSentence]) -> int:
    # On to the end of the sentence the cut falls in; from a pause, back to the last sentence.
    for sentence in reversed(sentences):
        if sentence.start_ms < end_ms <= sentence.end_ms:
            return sentence.end_ms
        if start_ms < sentence.end_ms < end_ms:
            return sentence.end_ms
    return end_ms


def _nearest_cut(time_ms: int, shot_cuts_ms: Sequence[int], limits: SnapLimits) -> int:
    nearest = min(shot_cuts_ms, key=lambda cut: abs(cut - time_ms), default=None)
    if nearest is None or abs(nearest - time_ms) > limits.shot_tolerance_ms:
        return time_ms
    return nearest
