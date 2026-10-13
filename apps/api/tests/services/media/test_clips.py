# apps/api/tests/services/media/test_clips.py

"""Planning clips: bounds, snapping, input numbering, framing, and output size."""

import pytest

from services.files.domain import VideoMetadata
from services.media.clips import ClipSource, output_fps, output_size, plan_clip
from services.media.domain import TranscriptSentence
from tests.factories import build_file, build_file_revision, build_workspace

SENTENCES = (
    TranscriptSentence(text="Pricing is simple.", start_ms=1_000, end_ms=9_000),
    TranscriptSentence(text="You pay per seat.", start_ms=10_000, end_ms=30_000),
)


def _source(duration_ms: int, **analysis) -> ClipSource:
    workspace = build_workspace()
    file = build_file(workspace=workspace, category="video", content_type="video/mp4")
    metadata = VideoMetadata(
        duration_ms=duration_ms, width=1920, height=1080, has_audio=True, rotation=0
    )
    return ClipSource(revision=build_file_revision(file), metadata=metadata, **analysis)


def test_snapped_cuts_land_on_sentences_and_each_video_is_one_input() -> None:
    talk = _source(60_000, sentences=SENTENCES, shot_cuts_ms=(29_600,))
    broll = _source(5_000)

    snapped = plan_clip(
        [(talk, 12_400, 28_000), (broll, None, None), (talk, 0, 5_000)],
        size=(1080, 1920),
        framing="center",
        snap=True,
    )
    exact = plan_clip([(talk, 12_400, 28_000)], size=(1080, 1920), framing="center", snap=False)

    # Back to the sentence start, on to its end then 400 ms back to the shot change.
    assert [
        (segment.input, segment.start_ms, segment.end_ms) for segment in snapped.operation.segments
    ] == [(0, 10_000, 29_600), (1, 0, 5_000), (0, 1_000, 9_000)]
    assert snapped.sources == (talk.revision, broll.revision)
    assert len(snapped.warnings) == 2
    assert [(segment.start_ms, segment.end_ms) for segment in exact.operation.segments] == [
        (12_400, 28_000)
    ]


def test_automatic_framing_sends_each_inputs_shot_cuts_inside_its_segments() -> None:
    talk = _source(60_000, shot_cuts_ms=(5_000, 20_000, 40_000))
    broll = _source(10_000, shot_cuts_ms=(2_000, 8_000))

    clip = plan_clip(
        [(broll, 0, 5_000), (talk, 10_000, 30_000), (talk, 35_000, 45_000)],
        size=(1080, 1920),
        framing="auto",
        snap=False,
    )

    assert clip.operation.reframe
    assert clip.operation.shot_cuts_ms == ((0, 2_000), (1, 20_000), (1, 40_000))


@pytest.mark.parametrize(
    ("start_ms", "end_ms"),
    [(60_000, None), (20_000, 20_000)],
)
def test_a_segment_outside_the_video_fails_before_rendering(
    start_ms: int, end_ms: int | None
) -> None:
    with pytest.raises(ValueError, match="Segment 1"):
        plan_clip(
            [(_source(60_000), start_ms, end_ms)], size=(1080, 1920), framing="center", snap=False
        )


def test_a_clip_longer_than_a_saved_video_can_hold_fails_before_rendering() -> None:
    # 100 MB at 8.128 Mbit/s holds about 1 minute 43 seconds.
    source = _source(600_000)

    with pytest.raises(ValueError, match="Clips can be up to 1:43"):
        plan_clip(
            [(source, 0, 60_000), (source, 200_000, 250_000)],
            size=(1080, 1920),
            framing="center",
            snap=False,
        )


def test_output_is_1080_on_the_short_side_upright_at_the_source_frame_rate() -> None:
    phone = VideoMetadata(
        duration_ms=1_000, width=1920, height=1080, fps=59.94, has_audio=True, rotation=90
    )

    assert output_size("9:16", phone) == (1080, 1920)
    assert output_size("4:5", phone) == (1080, 1350)
    assert output_size("original", phone) == (1080, 1920)
    assert output_fps(phone) == 60
    assert output_fps(phone.model_copy(update={"fps": 15.0})) == 24
