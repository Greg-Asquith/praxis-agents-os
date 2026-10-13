# apps/renderer/tests/test_reframe.py

"""Planning the crop that follows a face: holds, pans, jumps at cuts, and centring."""

import pytest
from media.reframe import PAN_MS, SAMPLE_INTERVAL_MS, Move, Track, subject_track

FRAME = (640, 360)
# A 9:16 crop of a 16:9 frame keeps about a third of its width.
SHARE = (360 * 9 / 16) / 640


def _face(centre_x: float) -> list[list[float]]:
    return [[centre_x * FRAME[0] - 20, 100, 40, 50]]


def _track(samples: list[list[list[float]]], cuts: tuple[int, ...] = ()) -> Track:
    return subject_track(
        samples,
        axis=0,
        frame_size=FRAME,
        share=SHARE,
        shot_cuts_ms=cuts,
        duration_ms=len(samples) * SAMPLE_INTERVAL_MS,
    )


def test_the_crop_holds_inside_the_dead_zone_and_pans_once_the_face_leaves_it() -> None:
    # The crop is about 0.32 of the width; its middle third spans 0.11 around its centre.
    track = _track([_face(0.50), _face(0.53), _face(0.47), _face(0.70), _face(0.70)])

    assert track.initial == pytest.approx(0.5)
    [pan] = track.moves
    assert (pan.start_ms, pan.end_ms) == (3 * SAMPLE_INTERVAL_MS, 3 * SAMPLE_INTERVAL_MS + PAN_MS)
    assert pan.position > 0.5


def test_the_crop_jumps_at_a_shot_cut_and_never_pans_across_it() -> None:
    # Left, then a pan starting 300 ms before the cut at 1.8 s; right after the cut.
    samples = [_face(0.2), _face(0.2), _face(0.2), _face(0.45), _face(0.8), _face(0.8)]

    track = _track(samples, cuts=(1800,))

    pan, jump = track.moves
    assert (pan.start_ms, pan.end_ms) == (1500, 1800)
    assert (jump.start_ms, jump.end_ms) == (1800, 1800)
    assert jump.position > pan.position


def test_a_shot_with_no_face_is_centred() -> None:
    track = _track([_face(0.1), _face(0.1), [], [], []], cuts=(1000,))

    assert track.initial == 0
    assert track.moves == (Move(1000, 1000, 0.5),)
