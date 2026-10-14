# apps/api/tests/scenarios/test_video_transcription.py

"""transcribe_video: one transcription per revision, saved as an SRT File."""

from collections.abc import AsyncIterator

import httpx2 as httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from core.settings import settings
from models.ai_usage_event import AIUsageEvent
from models.audit_event import AuditEvent
from models.files import File, FileRevision
from services.agents.models.utils import _build_retrying_http_client
from services.files.utils import private_ref_from_key, sha256_hex
from services.media import transcription_providers
from services.storage.factory import get_storage_provider
from tests.support.media import (
    file_tool_turn,
    persist_analysed_video,
    staged_ref,
    use_fake_renderer,
)
from tests.support.scenario import (
    build_scenario_agent,
    run_scenario,
    scripted_model,
)
from tests.support.storage import reset_storage_provider_cache

# A trimmed whisper-1 verbose_json answer for a two-speaker recording.
WHISPER_RESPONSE = {
    "task": "transcribe",
    "language": "english",
    "duration": 8.4,
    "text": "Welcome back to the show. Thanks for having me.",
    "words": [
        {"word": "Welcome", "start": 0.5, "end": 0.9},
        {"word": "back", "start": 0.9, "end": 1.1},
        {"word": "to", "start": 1.1, "end": 1.2},
        {"word": "the", "start": 1.2, "end": 1.3},
        {"word": "show", "start": 1.3, "end": 1.7},
        {"word": "Thanks", "start": 2.6, "end": 3.0},
        {"word": "for", "start": 3.0, "end": 3.1},
        {"word": "having", "start": 3.1, "end": 3.4},
        {"word": "me", "start": 3.4, "end": 3.6},
    ],
}


@pytest.fixture
async def services(tmp_path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[dict[str, list]]:
    """A fake renderer that extracts audio, and whisper-1 answering with the recording."""
    calls: dict[str, list] = {"renderer": [], "openai": []}

    async def fake_post(payload: dict) -> dict:
        calls["renderer"].append(payload)
        outputs = []
        for target in payload["outputs"]:
            content = b"OggS-chunk"
            await get_storage_provider().put_object(staged_ref(target["url"]), content)
            outputs.append({"size_bytes": len(content), "sha256": sha256_hex(content)})
        result = {"duration_ms": 8400, "chunks_ms": [[0, 8400]]}
        return {"ok": True, "result": result, "outputs": outputs, "elapsed_ms": 5}

    def respond(request: httpx.Request) -> httpx.Response:
        calls["openai"].append(request)
        return httpx.Response(200, json=WHISPER_RESPONSE)

    use_fake_renderer(monkeypatch, tmp_path, fake_post)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_AI", False)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("openai-test"))
    async with _build_retrying_http_client(httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(transcription_providers, "retrying_http_client", lambda: client)
        try:
            yield calls
        finally:
            reset_storage_provider_cache()


async def _persist_video(db_session_factory, context) -> File:
    return await persist_analysed_video(
        db_session_factory,
        workspace_id=context.workspace_id,
        user_id=context.user_id,
        name="Pricing talk.mp4",
        duration_ms=8400,
        speech=None,
    )


async def test_a_video_is_transcribed_once_and_saved_as_one_srt_file(
    db_session_factory, services: dict[str, list]
) -> None:
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["transcribe_video"],
        tool_policies={"transcribe_video": "auto"},
    )
    video = await _persist_video(db_session_factory, context)

    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                file_tool_turn("transcribe_video", video, "first"),
                file_tool_turn("transcribe_video", video, "second"),
                "Done.",
            ]
        ),
    )

    assert result.run.status == "completed"
    [extract] = services["renderer"]
    assert extract["operation"] == "extract_audio"
    assert extract["arguments"] == {"chunks": 1}
    [request] = services["openai"]
    body = request.content.decode(errors="replace")
    assert 'name="model"\r\n\r\nwhisper-1' in body
    assert 'name="timestamp_granularities[]"\r\n\r\nword' in body
    # Transcript text comes from the video, so it reaches the model framed as untrusted.
    assert [
        part["content"]["opening"]["node"] for part in result.tool_returns("transcribe_video")
    ] == ["praxis_untrusted"] * 2
    async with db_session_factory() as db:
        [transcript] = (
            await db.scalars(select(File).where(File.name == "Pricing talk transcript.srt"))
        ).all()
        assert transcript.revision_count == 2
        revision = await db.get_one(FileRevision, transcript.current_revision_id)
        srt = await get_storage_provider().get_object(private_ref_from_key(revision.object_key))
        assert srt.decode() == (
            "1\n00:00:00,500 --> 00:00:01,700\nWelcome back to the show.\n\n"
            "2\n00:00:02,600 --> 00:00:03,600\nThanks for having me.\n"
        )
        [audit] = (
            await db.scalars(
                select(AuditEvent).where(
                    AuditEvent.workspace_id == context.workspace_id,
                    AuditEvent.details["operation"].astext == "video_transcription",
                )
            )
        ).all()
        assert audit.details["provider"] == "openai"
        [usage] = (
            await db.scalars(
                select(AIUsageEvent).where(
                    AIUsageEvent.run_id == context.run_id,
                    AIUsageEvent.purpose == "video_transcription",
                )
            )
        ).all()
        assert (usage.model, usage.requests) == ("whisper-1", 1)


async def test_another_workspaces_video_is_refused_before_any_audio_leaves(
    db_session_factory, services: dict[str, list]
) -> None:
    other = await build_scenario_agent(db_session_factory)
    foreign = await _persist_video(db_session_factory, other)
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["transcribe_video"],
        tool_policies={"transcribe_video": "auto"},
    )

    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[file_tool_turn("transcribe_video", foreign, "foreign"), "Done."]
        ),
    )

    assert result.run.status == "completed"
    assert services["renderer"] == [] and services["openai"] == []
    assert "File not found" in str([message.parts for message in result.messages])
