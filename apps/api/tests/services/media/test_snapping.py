# apps/api/tests/services/media/test_snapping.py

"""Snapping model-chosen ranges to sentences and shots, and keeping the best of overlaps."""

from dataclasses import dataclass
from itertools import pairwise

from services.media.domain import TranscriptSentence
from services.media.snapping import SnapLimits, drop_overlaps, snap_range
from services.media.utils import video_windows

# Four sentences with pauses between them, in milliseconds.
SENTENCES = (
    TranscriptSentence(text="Pricing is simple.", start_ms=1_000, end_ms=9_000),
    TranscriptSentence(text="You pay per seat.", start_ms=10_000, end_ms=30_000),
    TranscriptSentence(text="Annual plans save more.", start_ms=31_000, end_ms=52_000),
    TranscriptSentence(text="Questions?", start_ms=55_000, end_ms=58_000),
)
LIMITS = SnapLimits(min_ms=5_000, max_ms=60_000, shot_tolerance_ms=700)


def _snap(start_ms: int, end_ms: int, *, cuts: tuple[int, ...] = (), limits: SnapLimits = LIMITS):
    return snap_range(
        start_ms,
        end_ms,
        sentences=SENTENCES,
        shot_cuts_ms=cuts,
        duration_ms=60_000,
        limits=limits,
    )


def test_a_start_inside_a_sentence_snaps_back_to_its_start() -> None:
    assert _snap(12_400, 30_000) == (10_000, 30_000)


def test_an_end_inside_a_sentence_snaps_on_to_its_end() -> None:
    assert _snap(10_000, 40_000) == (10_000, 52_000)


def test_cuts_in_pauses_move_inward_to_the_sentences_inside_the_range() -> None:
    # The model's start sits in the pause before sentence two, its end in the pause after it.
    assert _snap(9_400, 30_600) == (10_000, 30_000)


def test_a_cut_moves_to_a_shot_boundary_inside_the_tolerance_only() -> None:
    assert _snap(10_000, 30_000, cuts=(9_500, 31_000)) == (9_500, 30_000)


def test_a_short_moment_runs_on_to_the_next_sentence_end_or_is_dropped() -> None:
    # Sentence one is 8 seconds; 15 seconds needs sentence two as well.
    assert _snap(1_000, 9_000, limits=SnapLimits(15_000, 60_000, 700)) == (1_000, 30_000)
    assert _snap(1_000, 9_000, limits=SnapLimits(15_000, 20_000, 700)) is None


def test_overlapping_moments_keep_the_higher_score() -> None:
    @dataclass(frozen=True)
    class Moment:
        start_ms: int
        end_ms: int
        score: int

    kept = drop_overlaps(
        [Moment(0, 30_000, 60), Moment(20_000, 50_000, 90), Moment(50_000, 60_000, 40)]
    )

    assert kept == [Moment(20_000, 50_000, 90), Moment(50_000, 60_000, 40)]


def test_windows_overlap_and_cover_a_four_hour_video() -> None:
    windows = video_windows(0, 14_400_000, window_ms=2_400_000, overlap_ms=60_000)

    assert windows[0][0] == 0 and windows[-1][1] == 14_400_000
    assert all(end - start <= 2_400_000 for start, end in windows)
    assert all(later[0] == earlier[1] - 60_000 for earlier, later in pairwise(windows))
