# apps/api/tests/services/media/test_omni.py

"""Omni requests and responses, from interactions recorded on 2026-10-01 and 2026-11-17."""

import base64
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from google.genai._interactions import APIStatusError
from google.genai.interactions import Interaction

from services.media import omni
from services.media.generation import (
    ChainExpiredError,
    VideoEditRequest,
    VideoGenerationError,
    VideoGenerationRequest,
    VideoReference,
)

CLIP = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64


def _recorded(**changes) -> Interaction:
    """A completed 4 second 720p generation, with the clip and signature shortened."""
    return Interaction.model_validate(
        {
            "id": "ChAxNzgxMzQ3NjEzNjg1MmI2EAgaAmE2KgRtYWlu",
            "status": "completed",
            "model": "gemini-omni-1.2-flash",
            "output_text": "",
            "steps": [
                {
                    "type": "thought",
                    "signature": "AY89a1",
                    "summary": [
                        {"type": "text", "text": "**Developing Video Prompt**\n\nA vertical shot."}
                    ],
                },
                {
                    "type": "model_output",
                    "content": [
                        {
                            "type": "video",
                            "mime_type": "video/mp4",
                            "data": base64.b64encode(CLIP).decode(),
                        }
                    ],
                },
            ],
            "output_video": {
                "type": "video",
                "mime_type": "video/mp4",
                "data": base64.b64encode(CLIP).decode(),
            },
            "usage": {
                "total_input_tokens": 38,
                "total_output_tokens": 23168,
                "total_thought_tokens": 1125,
                "total_tokens": 24331,
            },
            **changes,
        }
    )


def test_a_recorded_generation_returns_its_clip_tokens_and_notes() -> None:
    video = omni.generated_video(_recorded(), max_bytes=1024)

    assert video.content == CLIP
    assert (video.input_tokens, video.output_tokens) == (38, 23168 + 1125)
    assert video.thought_summary == "**Developing Video Prompt**\n\nA vertical shot."


def test_a_clip_over_the_limit_is_refused_before_it_is_decoded() -> None:
    with pytest.raises(VideoGenerationError, match="too large"):
        omni.generated_video(_recorded(), max_bytes=len(CLIP) - 1)


def test_a_failed_interaction_for_safety_is_a_refusal_the_agent_can_revise() -> None:
    interaction = _recorded(
        status="failed",
        output_video=None,
        errors=[{"code": "safety", "message": "The prompt was blocked by safety filters."}],
    )

    with pytest.raises(VideoGenerationError) as raised:
        omni.generated_video(interaction, max_bytes=1024)

    assert raised.value.refused


async def test_start_sends_one_background_stored_generation(monkeypatch) -> None:
    sent: list[dict] = []

    async def create(**kwargs):
        sent.append(kwargs)
        return SimpleNamespace(id="interaction-1")

    @asynccontextmanager
    async def client(_model):
        yield SimpleNamespace(interactions=SimpleNamespace(create=create))

    monkeypatch.setattr(omni, "_client", client)
    request = VideoGenerationRequest(
        provider_model="gemini-omni-1.2-flash",
        prompt="A paper boat on a pond at dusk.",
        aspect_ratio="9:16",
        resolution="1080p",
        duration_seconds=4,
    )

    assert await omni.OmniBackend().start(request) == "interaction-1"
    [body] = sent
    assert body["background"] is True
    assert body["store"] is True
    assert body["response_format"] == {
        "type": "video",
        "aspect_ratio": "9:16",
        "resolution": "1080p",
        "duration": "4s",
    }
    assert body["generation_config"] == {"video_config": {"task": "text_to_video"}}


async def test_references_go_before_the_prompt_with_no_task(monkeypatch) -> None:
    sent: list[dict] = []

    async def create(**kwargs):
        sent.append(kwargs)
        return SimpleNamespace(id="interaction-1")

    monkeypatch.setattr(omni, "_client", _fake_client(create))
    request = VideoGenerationRequest(
        provider_model="gemini-omni-1.2-flash",
        prompt="The cup from the first image on the table from the second.",
        aspect_ratio="9:16",
        resolution="720p",
        duration_seconds=8,
        references=(
            VideoReference(kind="image", content=b"cup", media_type="image/png"),
            VideoReference(kind="video", content=b"pour", media_type="video/quicktime"),
        ),
    )

    await omni.OmniBackend().start(request)

    [body] = sent
    assert body["input"] == [
        {"type": "image", "data": base64.b64encode(b"cup").decode(), "mime_type": "image/png"},
        # Google names QuickTime video/mov.
        {"type": "video", "data": base64.b64encode(b"pour").decode(), "mime_type": "video/mov"},
        {"type": "text", "text": request.prompt},
    ]
    # Google reads from the prompt how each reference is used; a task would constrain it.
    assert "generation_config" not in body
    assert body["response_format"]["duration"] == "8s"


def _fake_client(create):
    @asynccontextmanager
    async def client(_model):
        yield SimpleNamespace(interactions=SimpleNamespace(create=create))

    return client


async def test_an_edit_chains_without_a_task_or_uploads_with_one(monkeypatch) -> None:
    sent: list[dict] = []

    async def create(**kwargs):
        sent.append(kwargs)
        return SimpleNamespace(id=f"interaction-{len(sent)}")

    monkeypatch.setattr(omni, "_client", _fake_client(create))
    backend = omni.OmniBackend()

    await backend.start_edit(
        VideoEditRequest(
            "gemini-omni-1.2-flash",
            "Make it dusk.",
            previous_id="interaction-0",
            resolution="1080p",
        )
    )
    await backend.start_edit(VideoEditRequest("gemini-omni-1.2-flash", "Make it dusk.", video=CLIP))

    chained, uploaded = sent
    # Google refuses previous_interaction_id alongside a task (HTTP 400, 2026-10-01).
    assert chained["previous_interaction_id"] == "interaction-0"
    assert chained["input"] == "Make it dusk."
    assert "generation_config" not in chained
    # Google returns 720p unless the edit names the source's resolution (2026-11-17).
    assert chained["response_format"] == {"type": "video", "resolution": "1080p"}
    assert uploaded["generation_config"] == {"video_config": {"task": "edit"}}
    assert uploaded["input"][0] == {
        "type": "video",
        "data": base64.b64encode(CLIP).decode(),
        "mime_type": "video/mp4",
    }
    assert "previous_interaction_id" not in uploaded
    assert all(body["store"] and body["background"] for body in sent)


async def test_a_chain_google_no_longer_holds_is_reported_as_expired(monkeypatch) -> None:
    # Both recorded on Vertex, 2026-11-17: an unknown ID, and a foreground interaction.
    errors = iter([(404, "Requested entity was not found."), (400, "Precondition check failed.")])

    async def create(**_kwargs):
        status, message = next(errors)
        request = httpx.Request("POST", "https://aiplatform.googleapis.com/v1beta1/interactions")
        raise APIStatusError(message, response=httpx.Response(status, request=request), body=None)

    monkeypatch.setattr(omni, "_client", _fake_client(create))

    for _ in range(2):
        with pytest.raises(ChainExpiredError):
            await omni.OmniBackend().start_edit(
                VideoEditRequest("gemini-omni-1.2-flash", "Make it dusk.", previous_id="old")
            )


def test_an_upload_the_gemini_api_fails_from_this_region_says_so(monkeypatch) -> None:
    monkeypatch.setattr(omni.settings, "GOOGLE_VERTEX_AI", False)
    # Recorded with a UK Gemini API key, 2026-11-17: accepted, then failed with no reason.
    failed = _recorded(
        status="failed",
        output_video=None,
        errors=[
            {
                "code": "INVALID_ARGUMENT",
                "message": "There was a problem processing your request. You will only be "
                "charged for tokens successfully generated.",
            }
        ],
        steps=[
            {
                "type": "user_input",
                "content": [
                    {"type": "video", "mime_type": "video/mp4"},
                    {"type": "text", "text": "Make it dusk."},
                ],
            }
        ],
    )

    with pytest.raises(VideoGenerationError, match="region"):
        omni.generated_video(failed, max_bytes=10_000_000)
