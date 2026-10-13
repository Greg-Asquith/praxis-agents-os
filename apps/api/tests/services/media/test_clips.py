# apps/api/tests/services/media/test_clips.py

"""Planning clips: bounds, snapping, input numbering, framing, pauses, captions, transitions,
text overlays, and size.
"""

import pytest

from services.files.domain import VideoMetadata
from services.media.captions import CaptionStyle, OverlayTextStyle, TextOverlay, subtitle_file
from services.media.clips import (
    ClipSource,
    TransitionOptions,
    output_fps,
    output_size,
    plan_clip,
)
from services.media.domain import CutTransition, Transcript, TranscriptSentence, TranscriptWord
from tests.factories import build_file, build_file_revision, build_workspace

SENTENCES = (
    TranscriptSentence(text="Pricing is simple.", start_ms=1_000, end_ms=9_000),
    TranscriptSentence(text="You pay per seat.", start_ms=10_000, end_ms=30_000),
)
# Two sentences with a 2.8 s pause between them, inside an 8 s segment.
WORDS = (
    TranscriptWord(text="Pricing", start_ms=1_050, end_ms=1_400),
    TranscriptWord(text="is", start_ms=1_450, end_ms=1_600),
    TranscriptWord(text="simple.", start_ms=1_650, end_ms=2_250),
    TranscriptWord(text="You", start_ms=5_050, end_ms=5_300),
    TranscriptWord(text="pay.", start_ms=5_350, end_ms=5_850),
)


def _transcript(*, model: str = "chirp_3", words=WORDS, sentences=SENTENCES) -> Transcript:
    return Transcript(
        provider="google",
        model=model,
        duration_ms=60_000,
        words=words,
        sentences=sentences,
    )


def _source(duration_ms: int, **analysis) -> ClipSource:
    workspace = build_workspace()
    file = build_file(workspace=workspace, category="video", content_type="video/mp4")
    metadata = VideoMetadata(
        duration_ms=duration_ms, width=1920, height=1080, has_audio=True, rotation=0
    )
    return ClipSource(revision=build_file_revision(file), metadata=metadata, **analysis)


def test_snapped_cuts_land_on_sentences_and_each_video_is_one_input() -> None:
    talk = _source(60_000, transcript=_transcript(words=()), shot_cuts_ms=(29_600,))
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


def test_a_clip_longer_than_the_renderer_can_write_fails_before_rendering() -> None:
    # A 2 GiB renderer output at 8.128 Mbit/s holds about 35 minutes; the 4 GiB File limit
    # no longer binds, because outputs are copied into Files by the storage provider.
    source = _source(3_600_000)

    with pytest.raises(ValueError, match="Clips can be up to 35:13"):
        plan_clip(
            [(source, 0, 1_200_000), (source, 1_800_000, 2_760_000)],
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


def test_removed_pauses_shorten_the_clip_and_captions_keep_to_the_words() -> None:
    talk = _source(60_000, transcript=_transcript())

    clip = plan_clip(
        [(talk, 0, 8_000)],
        size=(1080, 1920),
        framing="center",
        snap=False,
        captions=CaptionStyle(preset="bold"),
        remove_silences=True,
    )

    # 0.9 to 2.4 s and 4.9 to 6 s stay: 150 ms either side of speech, at 30 fps.
    assert clip.operation.keep_frames == ((0, 27, 72), (0, 147, 180))
    assert clip.duration_ms == 2_600
    assert clip.operation.captions
    starts = [
        line.split(",")[1] for line in clip.captions.splitlines() if line.startswith("Dialogue")
    ]
    # "Pricing" starts 150 ms in; "You" starts 150 ms after the 1.5 s first part.
    assert starts == ["0:00:00.15", "0:00:01.65"]


def test_word_highlighting_and_pause_removal_need_exact_word_times() -> None:
    talk = _source(60_000, transcript=_transcript(model="gemini-3.8-flash"))
    plan = {"size": (1080, 1920), "framing": "center", "snap": False}

    for options in (
        {"captions": CaptionStyle(preset="highlight")},
        {"remove_silences": True},
    ):
        with pytest.raises(ValueError, match="exact word times"):
            plan_clip([(talk, 0, 8_000)], **plan, **options)
    assert plan_clip([(talk, 0, 8_000)], **plan, captions=CaptionStyle(preset="bold")).captions


def test_caption_words_cant_style_the_file_and_lines_stay_within_the_bound() -> None:
    words = (
        TranscriptWord(text="{\\fnEvil\\pos(0,0)}Hello\\N", start_ms=0, end_ms=400),
        TranscriptWord(text="x" * 40, start_ms=400, end_ms=800),
        TranscriptWord(text="world.", start_ms=800, end_ms=1_200),
    )

    document, _ = subtitle_file(
        size=(1080, 1920), words=words, captions=CaptionStyle(preset="bold")
    )

    texts = [line.split(",", 9)[9] for line in document.splitlines() if line.startswith("Dialogue")]
    lines = [line for text in texts for line in text.split("\\N")]
    assert all("{" not in line and "\\" not in line for line in lines)
    # Bold Montserrat on a 1080 pixel wide frame fits 15 characters a line.
    assert max(len(line) for line in lines) <= 15
    assert "".join(lines).count("x") == 40


def test_a_segments_transition_overrides_the_clips_and_each_side_extends_over_the_cut() -> None:
    talk = _source(60_000)

    clip = plan_clip(
        [(talk, 10_000, 20_000), (talk, 30_000, 40_000), (talk, 45_000, 50_000)],
        size=(1080, 1920),
        framing="center",
        snap=False,
        transition=TransitionOptions(style="fade"),
        transitions_in=[None, None, TransitionOptions(style="wipeleft", duration_ms=300)],
    )

    assert clip.operation.transitions == (
        CutTransition(style="fade", duration_ms=400),
        CutTransition(style="wipeleft", duration_ms=300),
    )
    # Half of each transition either side of the cut, so no snapped speech is blended away.
    assert [(segment.start_ms, segment.end_ms) for segment in clip.operation.segments] == [
        (10_000, 20_200),
        (29_800, 40_150),
        (44_850, 50_000),
    ]
    assert clip.duration_ms == 25_000
    assert clip.warnings == ()


def test_a_transition_at_a_videos_start_blends_the_segments_edge_with_a_warning() -> None:
    talk, broll = _source(60_000), _source(5_000)

    whole = plan_clip(
        [(talk, 10_000, 20_000), (broll, None, None)],
        size=(1080, 1920),
        framing="center",
        snap=False,
        transition=TransitionOptions(style="fadeblack"),
    )
    clip = plan_clip(
        [(talk, 10_000, 20_000), (broll, 0, 5_000)],
        size=(1080, 1920),
        framing="center",
        snap=False,
        transition=TransitionOptions(style="fadeblack"),
    )

    assert [(segment.start_ms, segment.end_ms) for segment in clip.operation.segments] == [
        (10_000, 20_250),
        (0, 5_000),
    ]
    assert clip.warnings == (
        "Segment 2 starts at the start of its video, so the transition blends its first moments.",
    )
    # A whole video always blends its edges, so it says nothing.
    assert whole.operation.segments == clip.operation.segments
    assert whole.warnings == ()


def test_a_transition_longer_than_half_a_segment_fails_with_a_reason() -> None:
    talk = _source(60_000)

    with pytest.raises(ValueError, match="before segment 2 lasts 3 s, more than half"):
        plan_clip(
            [(talk, 10_000, 20_000), (talk, 30_000, 34_000)],
            size=(1080, 1920),
            framing="center",
            snap=False,
            transition=TransitionOptions(style="slideleft", duration_ms=3_000),
        )


def test_captions_switch_segments_halfway_through_a_transition() -> None:
    talk = _source(60_000, transcript=_transcript())

    clip = plan_clip(
        [(talk, 0, 3_000), (talk, 5_100, 6_000)],
        size=(1080, 1920),
        framing="center",
        snap=False,
        captions=CaptionStyle(preset="bold"),
        transition=TransitionOptions(style="fade"),
    )

    starts = [
        line.split(",")[1] for line in clip.captions.splitlines() if line.startswith("Dialogue")
    ]
    # The blend runs 2.8 to 3.2 s. "You" is spoken 150 ms into the second segment's extra
    # 200 ms, at 2.95 s, so it waits for the blend's middle.
    assert starts == ["0:00:01.05", "0:00:03.00"]


def _dialogue(document: str) -> list[tuple[str, str, str, str]]:
    """(start, end, style, text) for each event in an ASS file."""
    events = [line.split(",", 9) for line in document.splitlines() if line.startswith("Dialogue")]
    return [(event[1], event[2], event[3], event[9]) for event in events]


def test_an_overlay_on_a_segment_keeps_to_its_moment_after_pauses_are_removed() -> None:
    talk = _source(60_000, transcript=_transcript())

    clip = plan_clip(
        [(talk, 0, 8_000), (talk, 20_000, 25_000)],
        size=(1080, 1920),
        framing="center",
        snap=False,
        remove_silences=True,
        overlays=[
            TextOverlay(text="You pay", segment=1, start_ms=5_050, end_ms=6_000),
            TextOverlay(text="Next", segment=2, start_ms=21_000, end_ms=22_000),
        ],
    )

    # The first segment keeps 1.5 s then 1.1 s, so "You" lands 150 ms into the second part,
    # and the second segment starts at 2.6 s.
    assert [event[:3] for event in _dialogue(clip.captions)] == [
        ("0:00:01.65", "0:00:02.60", "Overlay1"),
        ("0:00:03.60", "0:00:04.60", "Overlay2"),
    ]
    assert clip.operation.captions


def test_overlay_text_cant_style_the_file_and_keeps_its_line_breaks() -> None:
    clip = plan_clip(
        [(_source(60_000), 0, 10_000)],
        size=(1080, 1920),
        framing="center",
        snap=False,
        overlays=[TextOverlay(text="{\\fnEvil}3 pricing\nmistakes")],
    )

    [(start, end, _, text)] = _dialogue(clip.captions)
    assert (start, end) == ("0:00:00.00", "0:00:10.00")
    # Bold Montserrat fits 15 characters a line on a 1080 pixel wide frame.
    assert text == "(\N{SET MINUS}fnEvil)3\\Npricing\\Nmistakes"


def test_an_overlay_outside_the_clip_fails_before_rendering() -> None:
    with pytest.raises(ValueError, match="Text overlay 1 ends after the clip, which is 0:10"):
        plan_clip(
            [(_source(60_000), 10_000, 20_000)],
            size=(1080, 1920),
            framing="center",
            snap=False,
            overlays=[TextOverlay(text="Hook", start_ms=9_000, end_ms=11_000)],
        )


def test_a_lower_overlay_moves_above_lower_captions() -> None:
    talk = _source(60_000, transcript=_transcript())

    clip = plan_clip(
        [(talk, 0, 8_000)],
        size=(1080, 1920),
        framing="center",
        snap=False,
        captions=CaptionStyle(preset="bold"),
        overlays=[TextOverlay(text="Follow", style=OverlayTextStyle(position="lower"))],
    )

    margins = {
        line.split(",")[0]: int(line.split(",")[21])
        for line in clip.captions.splitlines()
        if line.startswith("Style: ")
    }
    # Clear of two lines of 81 pixel captions above the caption margin.
    assert margins["Style: Overlay1"] > margins["Style: Caption"] + 2 * 81
    assert clip.warnings == ("Text overlay 1 moved above the captions.",)
