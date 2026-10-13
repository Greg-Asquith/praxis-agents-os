# apps/api/tests/services/media/test_video_analysis.py

"""Per-revision transcripts and shot cuts: chunking, provider answers, and reuse."""

from collections.abc import Iterator

import pytest
from pydantic import SecretStr
from pydantic_ai.usage import RunUsage

from core.settings import settings
from services.ai_usage.domain import PURPOSE_VIDEO_TRANSCRIPTION, AIUsageEventData
from services.files.utils import sha256_hex
from services.media import get_video_transcript as transcript_module
from services.media.domain import StagedMediaOutput, TranscriptWord
from services.media.get_video_shot_cuts import get_video_shot_cuts
from services.media.get_video_transcript import get_video_transcript
from services.media.transcription_providers import (
    ChunkTranscript,
    GeminiTranscript,
    GeminiWord,
    TranscriptionProvider,
    parse_chirp_operation,
    parse_gemini_transcript,
    transcription_provider,
)
from services.storage.factory import get_storage_provider
from tests.factories.files import build_file, build_file_revision
from tests.factories.workspaces import build_workspace
from tests.support.media import staged_ref, use_fake_renderer
from tests.support.storage import reset_storage_provider_cache

TWO_HOURS_MS = 2 * 60 * 60 * 1000
CHUNKS_MS = [[0, 2_880_400], [2_880_400, 5_760_100], [5_760_100, TWO_HOURS_MS]]


class _Session:
    async def flush(self) -> None:
        return None


@pytest.fixture
def renderer(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[list[dict]]:
    """Answers extract_audio with three chunks and scene_cuts with two cuts."""
    requests: list[dict] = []

    async def fake_post(payload: dict) -> dict:
        requests.append(payload)
        outputs = []
        for target in payload["outputs"]:
            await get_storage_provider().put_object(staged_ref(target["url"]), b"OggS")
            outputs.append({"size_bytes": 4, "sha256": sha256_hex(b"OggS")})
        result = (
            {"duration_ms": TWO_HOURS_MS, "chunks_ms": CHUNKS_MS[: len(outputs)]}
            if payload["operation"] == "extract_audio"
            else {"cuts_ms": [1200, 9800], "duration_ms": TWO_HOURS_MS}
        )
        return {"ok": True, "result": result, "outputs": outputs, "elapsed_ms": 5}

    use_fake_renderer(monkeypatch, tmp_path, fake_post)
    monkeypatch.setattr(transcript_module, "run_metered_helper", _unmetered)
    try:
        yield requests
    finally:
        reset_storage_provider_cache()


async def _unmetered(_event, call):
    return await call(RunUsage())


def _long_video():
    workspace = build_workspace()
    file = build_file(
        workspace=workspace,
        name="talk.mp4",
        category="video",
        content_type="video/mp4",
        extension=".mp4",
        size_bytes=3_000_000_000,
    )
    revision = build_file_revision(file)
    revision.media_metadata = {
        "duration_ms": TWO_HOURS_MS,
        "width": 1920,
        "height": 1080,
        "fps": 25.0,
        "video_codec": "h264",
        "has_audio": True,
        "audio_codec": "aac",
        "rotation": 0,
    }
    return workspace, revision


async def test_long_audio_is_chunked_and_word_times_continue_across_chunks(
    renderer: list[dict],
) -> None:
    workspace, revision = _long_video()

    async def transcribe(
        chunk: StagedMediaOutput, language: str | None, usage: RunUsage
    ) -> ChunkTranscript:
        # Each chunk starts its own clock at zero; the last word runs past the chunk's end.
        usage.requests += 1
        return ChunkTranscript(
            words=(
                TranscriptWord(text="Next.", start_ms=200, end_ms=600),
                TranscriptWord(text="Late.", start_ms=2_880_000, end_ms=2_890_000),
            ),
            language="en",
        )

    provider = TranscriptionProvider("openai", "whisper-1", 60 * 60 * 1000, transcribe)
    usage = AIUsageEventData(
        workspace_id=workspace.id,
        provider="openai",
        model="whisper-1",
        purpose=PURPOSE_VIDEO_TRANSCRIPTION,
    )

    transcript, created = await get_video_transcript(
        _Session(),
        revision=revision,
        provider=provider,
        language=None,
        usage=usage,
        on_stage=_ignore_stage,
    )

    # Two hours at 80% of a 60 minute limit needs three chunks.
    assert renderer[0]["arguments"] == {"chunks": 3}
    assert created and revision.transcript_object_key is not None
    starts = [word.start_ms for word in transcript.words]
    assert starts == [200, 2_880_000, 2_880_600, 5_760_100, 5_760_300, 7_200_000]
    # A word is clamped to its own chunk, so word times never run backwards.
    assert transcript.words[1].end_ms == 2_880_400
    assert starts == sorted(starts)


def test_chirp_answer_becomes_bounded_words_with_speakers() -> None:
    uri = "gs://platform/platform/media-staging/ws/request/output-0.ogg"
    operation = {
        "done": True,
        "response": {
            "results": {
                uri: {
                    "inlineResult": {
                        "transcript": {
                            "results": [
                                {
                                    "languageCode": "en-gb",
                                    "alternatives": [
                                        {
                                            "words": [
                                                {
                                                    "endOffset": "0.400s",
                                                    "word": "Hello",
                                                    "speakerLabel": "1",
                                                },
                                                {
                                                    "startOffset": "0.400s",
                                                    "endOffset": "0.900s",
                                                    "word": "there.\n\n2\n00:00",
                                                    "speakerLabel": "2",
                                                },
                                            ]
                                        }
                                    ],
                                }
                            ]
                        }
                    }
                }
            }
        },
    }

    parsed = parse_chirp_operation(operation, uri)

    assert parsed.language == "en-gb"
    assert [(word.text, word.start_ms, word.end_ms, word.speaker) for word in parsed.words] == [
        ("Hello", 0, 400, "1"),
        # Whitespace from the provider can't start a new SubRip cue.
        ("there. 2 00:00", 400, 900, "2"),
    ]


def test_gemini_transcribes_only_when_no_closer_provider_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_AI", False)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", None)
    # An Anthropic-only deployment has nothing that can transcribe.
    assert transcription_provider() is None

    monkeypatch.setattr(settings, "GOOGLE_API_KEY", SecretStr("google-test"))
    assert transcription_provider().model == "gemini-3.8-flash"

    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("openai-test"))
    assert transcription_provider().model == "whisper-1"


def test_gemini_answer_drops_words_with_negative_times() -> None:
    parsed = parse_gemini_transcript(
        GeminiTranscript(
            language="en",
            words=[
                GeminiWord(word="Hello", start=0.5, end=0.9, speaker="A"),
                GeminiWord(word="ghost", start=-1.0, end=0.2, speaker="A"),
                GeminiWord(word="there.", start=1.2, end=1.1, speaker="B"),
            ],
        )
    )

    assert [(word.text, word.start_ms, word.end_ms, word.speaker) for word in parsed.words] == [
        ("Hello", 500, 900, "A"),
        # A reversed end becomes a zero-length word rather than running backwards.
        ("there.", 1200, 1200, "B"),
    ]


async def test_shot_cuts_are_measured_once_per_revision(renderer: list[dict]) -> None:
    _workspace, revision = _long_video()

    first = await get_video_shot_cuts(_Session(), revision=revision)
    second = await get_video_shot_cuts(_Session(), revision=revision)

    assert first == second == (1200, 9800)
    assert [request["operation"] for request in renderer] == ["scene_cuts"]


async def _ignore_stage(_name: str) -> None:
    return None
