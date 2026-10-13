# apps/renderer/tests/test_media_operations.py

"""Media operations through the driver, against real ffmpeg on Linux."""

from typing import Any

import pytest
from driver.server import DriverConfig, OperationError, handle_request
from media.operations import OPERATIONS

from tests.conftest import FakeStorage


def _request(
    storage: FakeStorage,
    operation: str,
    *,
    source: str = "sample.mp4",
    outputs: int = 0,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "operation": operation,
        "timeout_seconds": 60,
        "input": storage.source(source),
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


def test_cut_copies_from_a_keyframe_and_encodes_otherwise(
    storage: FakeStorage, config: DriverConfig
) -> None:
    on_keyframe = _run(
        storage, config, "cut", outputs=1, arguments={"start_ms": 1000, "end_ms": 3000}
    )
    off_keyframe = _run(
        storage, config, "cut", outputs=1, arguments={"start_ms": 500, "end_ms": 1500}
    )

    assert on_keyframe["result"]["mode"] == "copy"
    assert abs(on_keyframe["result"]["duration_ms"] - 2000) <= 100
    assert off_keyframe["result"]["mode"] == "encode"
    assert abs(off_keyframe["result"]["duration_ms"] - 1000) <= 100
    assert storage.uploads["out-0"][4:8] == b"ftyp"
    assert off_keyframe["outputs"][0]["size_bytes"] == len(storage.uploads["out-0"])


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
    webm = _run(storage, config, "probe", source="sample.webm")

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
        source="speech_gaps.mp4",
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
    trimmed = _run(storage, config, "cut", outputs=1, arguments={"start_ms": 3000, "end_ms": 9000})

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
        _run(storage, config, "probe", source="malformed.mp4")

    assert error.value.code == "invalid_media"


@pytest.mark.parametrize(
    "arguments",
    [
        {"start_ms": "/etc/passwd", "end_ms": 1000},
        {"start_ms": 0, "end_ms": 1000, "filter": "movie=http://example.com"},
    ],
)
def test_text_in_arguments_fails_validation_before_anything_runs(
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
    request["input"]["url"] = "http://169.254.169.254/computeMetadata/v1/"

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


def _dimensions(jpeg: bytes) -> tuple[int, int]:
    # Reads the baseline start-of-frame marker: FF C0, length, precision, height, width.
    marker = jpeg.index(b"\xff\xc0")
    height = int.from_bytes(jpeg[marker + 5 : marker + 7])
    width = int.from_bytes(jpeg[marker + 7 : marker + 9])
    return width, height
