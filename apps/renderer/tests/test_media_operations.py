# apps/renderer/tests/test_media_operations.py

"""Media operations through the driver, against real ffmpeg on Linux."""

import re
import subprocess
from typing import Any

import cv2
import numpy as np
import pytest
from driver.server import DriverConfig, OperationError, handle_request
from media.ffmpeg import FFMPEG
from media.operations import OPERATIONS
from media.transitions import ACROSSFADE_CURVES, XFADE_STYLES

from tests.conftest import FakeStorage


def _request(
    storage: FakeStorage,
    operation: str,
    *,
    sources: tuple[str, ...] = ("sample.mp4",),
    outputs: int = 0,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "operation": operation,
        "timeout_seconds": 60,
        "inputs": [storage.source(source) for source in sources],
        "outputs": [storage.target(f"out-{index}") for index in range(outputs)],
        "arguments": arguments or {},
    }


def _run(storage: FakeStorage, config: DriverConfig, operation: str, **kwargs: Any) -> dict:
    return handle_request(
        _request(storage, operation, **kwargs), config=config, operations=OPERATIONS
    )


def test_probe_reads_the_whole_input(storage: FakeStorage, config: DriverConfig) -> None:
    response = _run(storage, config, "probe")

    assert response["result"] == {
        "duration_ms": 4000,
        "width": 320,
        "height": 180,
        "fps": 30.0,
        "video_codec": "h264",
        "has_audio": True,
        "audio_codec": "aac",
        "rotation": 0,
    }
    # Metadata can sit mid-file, so a sparse head-and-tail read can miss streams.
    assert storage.requests == [("GET", "/objects/sample.mp4", None)]


def test_scene_cuts_finds_the_colour_change(storage: FakeStorage, config: DriverConfig) -> None:
    response = _run(storage, config, "scene_cuts", arguments={"threshold": 0.3})

    assert [round(cut / 100) for cut in response["result"]["cuts_ms"]] == [20]


def test_cut_joins_segments_from_several_inputs_in_order_at_the_output_size(
    storage: FakeStorage, config: DriverConfig
) -> None:
    # sample.mp4 is red then blue from 2 s, 320x180 at 30 fps with audio; sample.webm is
    # grey, 160x90 at 15 fps without audio.
    response = _run(
        storage,
        config,
        "cut",
        sources=("sample.mp4", "sample.webm"),
        outputs=1,
        arguments={
            "segments": [[0, 2000, 3500], [1, 0, 500], [0, 0, 1000]],
            "width": 180,
            "height": 320,
            "fps": 60,
            "fit": True,
        },
    )
    storage.objects["clip.mp4"] = storage.uploads["out-0"]
    cuts = _run(storage, config, "scene_cuts", sources=("clip.mp4",), arguments={"threshold": 0.3})

    clip = response["result"]
    assert (clip["width"], clip["height"], clip["fps"]) == (180, 320, 60.0)
    assert (clip["video_codec"], clip["audio_codec"]) == ("h264", "aac")
    assert abs(clip["duration_ms"] - 3000) <= 100
    # Blue for 1.5 s, grey for 0.5 s, then red: joined in the order given.
    assert [round(cut / 100) for cut in cuts["result"]["cuts_ms"]] == [15, 20]


def test_reframe_keeps_the_face_inside_a_vertical_crop_in_every_shot(
    storage: FakeStorage, config: DriverConfig
) -> None:
    # talking_head.mp4 is 640x360: a face at the left until a cut at 2 s, then at the right.
    # A centred 9:16 crop would miss it in both shots.
    _run(
        storage,
        config,
        "cut",
        sources=("talking_head.mp4",),
        outputs=1,
        arguments={
            "segments": [[0, 0, 4000]],
            "width": 180,
            "height": 320,
            "fps": 30,
            "fit": False,
            "reframe": True,
            "shot_cuts": [[0, 2000], [0, 4000]],
        },
    )
    storage.objects["clip.mp4"] = storage.uploads["out-0"]
    times = [250, 1750, 2250, 3750]
    _run(storage, config, "frames", sources=("clip.mp4",), outputs=4, arguments={"times_ms": times})

    for index in range(len(times)):
        frame = cv2.imdecode(np.frombuffer(storage.uploads[f"out-{index}"], np.uint8), 1)
        detector = cv2.FaceDetectorYN.create(
            "/opt/yunet/face_detection_yunet_2023mar.onnx", "", (180, 320), 0.7
        )
        _, faces = detector.detect(frame)
        assert faces is not None, f"no face at {times[index]} ms"
        x, _, width = faces[0][:3]
        assert x >= 0 and x + width <= 180


def test_cut_keeps_only_the_given_frames_and_burns_in_captions(
    storage: FakeStorage, config: DriverConfig
) -> None:
    # Keeps 0 to 1 s of red and 2.5 to 3.5 s of blue; the caption shows for the first second.
    storage.objects["captions.ass"] = _captions(
        "Dialogue: 0,0:00:00.00,0:00:01.00,Caption,,0,0,0,,HELLO"
    )
    response = _run(
        storage,
        config,
        "cut",
        sources=("sample.mp4", "captions.ass"),
        outputs=1,
        arguments={
            "segments": [[0, 0, 4000]],
            "width": 320,
            "height": 180,
            "fps": 30,
            "fit": False,
            "keep": [[0, 0, 30], [0, 75, 105]],
            "captions": True,
        },
    )
    storage.objects["clip.mp4"] = storage.uploads["out-0"]
    cuts = _run(storage, config, "scene_cuts", sources=("clip.mp4",), arguments={"threshold": 0.3})
    _run(
        storage,
        config,
        "frames",
        sources=("clip.mp4",),
        outputs=2,
        arguments={"times_ms": [500, 1500]},
    )

    assert abs(response["result"]["duration_ms"] - 2000) <= 50
    assert [round(cut / 100) for cut in cuts["result"]["cuts_ms"]] == [10]
    captioned, plain = (
        cv2.imdecode(np.frombuffer(storage.uploads[f"out-{index}"], np.uint8), 0)[70:110, 80:240]
        for index in range(2)
    )
    assert captioned.max() > 200 > plain.max()


def test_a_transition_overlaps_its_segments_and_fades_start_from_black(
    storage: FakeStorage, config: DriverConfig
) -> None:
    # 1.5 s of red then 1.5 s of blue, crossfaded over 500 ms from 1 s, after a 300 ms fade in.
    response = _run(
        storage,
        config,
        "cut",
        outputs=1,
        arguments={
            "segments": [[0, 0, 1500], [0, 2000, 3500]],
            "width": 320,
            "height": 180,
            "fps": 30,
            "fit": False,
            "transitions": [["fade", 500, "tri"]],
            "fade_in_ms": 300,
            "fade_out_ms": 300,
        },
    )
    storage.objects["clip.mp4"] = storage.uploads["out-0"]
    times = [0, 600, 1250, 1900]
    _run(storage, config, "frames", sources=("clip.mp4",), outputs=4, arguments={"times_ms": times})

    assert abs(response["result"]["duration_ms"] - 2500) <= 50
    black, red, blend, blue = (
        cv2.imdecode(np.frombuffer(storage.uploads[f"out-{index}"], np.uint8), 1).mean(axis=(0, 1))
        for index in range(len(times))
    )
    assert black.max() < 30
    # BGR: red alone, then both at once mid-transition, then blue alone.
    assert red[2] > 150 > red[0]
    assert blend[0] > 60 and blend[2] > 60
    assert blue[0] > 150 > blue[2]


def test_transition_names_match_the_ffmpeg_build() -> None:
    def names(filter_name: str, option: str) -> set[str]:
        help_text = subprocess.run(
            [FFMPEG, "-hide_banner", "-h", f"filter={filter_name}"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        # The option's own values, up to the next option at three spaces' indent.
        section = re.split(r"\n {3}(?=\S)", help_text.split(f"\n   {option} ", 1)[1])[0]
        return set(re.findall(r"^\s{5}(\w+)\s+-?\d+\s", section, re.MULTILINE))

    assert names("xfade", "transition") - {"custom"} == XFADE_STYLES
    assert names("acrossfade", "curve1") == ACROSSFADE_CURVES


def test_captions_with_sections_beyond_styles_and_dialogue_are_refused(
    storage: FakeStorage, config: DriverConfig
) -> None:
    storage.objects["captions.ass"] = _captions("[Fonts]\nfontname: evil.ttf")

    with pytest.raises(OperationError) as error:
        _run(
            storage,
            config,
            "cut",
            sources=("sample.mp4", "captions.ass"),
            outputs=1,
            arguments={
                "segments": [[0, 0, 1000]],
                "width": 320,
                "height": 180,
                "fps": 30,
                "fit": False,
                "captions": True,
            },
        )

    assert error.value.code == "invalid_request"


def test_frames_writes_one_bounded_jpeg_per_time(
    storage: FakeStorage, config: DriverConfig
) -> None:
    _run(
        storage,
        config,
        "frames",
        outputs=2,
        arguments={"times_ms": [500, 3500], "max_edge_px": 160},
    )

    for name in ("out-0", "out-1"):
        assert storage.uploads[name][:2] == b"\xff\xd8"
        assert _dimensions(storage.uploads[name]) == (160, 90)


def test_extract_audio_and_webm_input(storage: FakeStorage, config: DriverConfig) -> None:
    audio = _run(storage, config, "extract_audio", outputs=1, arguments={"end_ms": 2000})
    webm = _run(storage, config, "probe", sources=("sample.webm",))

    assert abs(audio["result"]["duration_ms"] - 2000) <= 100
    assert storage.uploads["out-0"][:4] == b"OggS"
    assert webm["result"]["video_codec"] == "vp9"
    assert webm["result"]["has_audio"] is False


def test_extract_audio_splits_chunks_inside_the_nearest_silence(
    storage: FakeStorage, config: DriverConfig
) -> None:
    # The fixture is silent from 3.05 s to 3.45 s; an even split would fall at 3.05 s.
    response = _run(
        storage,
        config,
        "extract_audio",
        sources=("speech_gaps.mp4",),
        outputs=2,
        arguments={"start_ms": 100, "chunks": 2},
    )

    first, second = response["result"]["chunks_ms"]
    assert first[0] == 100 and first[1] == second[0]
    assert 3100 <= first[1] <= 3400
    assert abs(second[1] - 6000) <= 100
    assert storage.uploads["out-0"][:4] == storage.uploads["out-1"][:4] == b"OggS"


def test_times_must_start_before_the_end_of_the_video(
    storage: FakeStorage, config: DriverConfig
) -> None:
    trimmed = _run(
        storage,
        config,
        "cut",
        outputs=1,
        arguments={
            "segments": [[0, 3000, 9000]],
            "width": 320,
            "height": 180,
            "fps": 30,
            "fit": False,
        },
    )

    for operation, arguments in (
        ("frames", {"times_ms": [4000]}),
        ("extract_audio", {"start_ms": 4000}),
    ):
        with pytest.raises(OperationError) as error:
            _run(storage, config, operation, outputs=1, arguments=arguments)
        assert error.value.code == "invalid_request"
    assert abs(trimmed["result"]["duration_ms"] - 1000) <= 100


def test_malformed_media_fails_with_a_plain_error(
    storage: FakeStorage, config: DriverConfig
) -> None:
    with pytest.raises(OperationError) as error:
        _run(storage, config, "probe", sources=("malformed.mp4",))

    assert error.value.code == "invalid_media"


@pytest.mark.parametrize(
    "arguments",
    [
        {
            "segments": [[0, "/etc/passwd", 1000]],
            "width": 320,
            "height": 180,
            "fps": 30,
            "fit": False,
        },
        {
            "segments": [[0, 0, 1000]],
            "width": 320,
            "height": 180,
            "fps": 30,
            "fit": False,
            "filter": "movie=http://example.com",
        },
        # Input 1 needs a second signed download the request doesn't have.
        {"segments": [[1, 0, 1000]], "width": 320, "height": 180, "fps": 30, "fit": False},
        # Transitions are names from a fixed list; xfade's custom expression is code.
        {
            "segments": [[0, 0, 1000], [0, 2000, 3000]],
            "width": 320,
            "height": 180,
            "fps": 30,
            "fit": False,
            "transitions": [["custom", 500, "tri"]],
        },
        {
            "segments": [[0, 0, 1000], [0, 2000, 3000]],
            "width": 320,
            "height": 180,
            "fps": 30,
            "fit": False,
            "transitions": [["fade", 500, "tri,movie=/etc/passwd"]],
        },
    ],
)
def test_bad_arguments_fail_validation_before_anything_runs(
    storage: FakeStorage, config: DriverConfig, arguments: dict
) -> None:
    with pytest.raises(OperationError) as error:
        _run(storage, config, "cut", outputs=1, arguments=arguments)

    assert error.value.code == "invalid_request"
    assert storage.requests == []


def test_transfer_outside_the_allowed_storage_is_refused(
    storage: FakeStorage, config: DriverConfig
) -> None:
    request = _request(storage, "probe")
    request["inputs"][0]["url"] = "http://169.254.169.254/computeMetadata/v1/"

    with pytest.raises(OperationError) as error:
        handle_request(request, config=config, operations=OPERATIONS)

    assert error.value.code == "invalid_request"


def test_a_request_succeeds_after_a_child_hits_its_memory_limit(
    storage: FakeStorage, config: DriverConfig
) -> None:
    starved = DriverConfig(**{**config.__dict__, "child_memory_bytes": 16 * 1024**2})

    with pytest.raises(OperationError) as error:
        _run(storage, starved, "probe")
    response = _run(storage, config, "probe")

    assert error.value.code in {"resource_limit", "invalid_media"}
    assert response["result"]["duration_ms"] == 4000


def _captions(events: str) -> bytes:
    return (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 320\nPlayResY: 180\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, "
        "BorderStyle, Outline, Alignment\n"
        "Style: Caption,DejaVu Sans,40,&H00FFFFFF,&H00000000,1,2,5\n\n"
        f"[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, "
        f"Text\n{events}\n"
    ).encode()


def _dimensions(jpeg: bytes) -> tuple[int, int]:
    # Reads the baseline start-of-frame marker: FF C0, length, precision, height, width.
    marker = jpeg.index(b"\xff\xc0")
    height = int.from_bytes(jpeg[marker + 5 : marker + 7])
    width = int.from_bytes(jpeg[marker + 7 : marker + 9])
    return width, height
