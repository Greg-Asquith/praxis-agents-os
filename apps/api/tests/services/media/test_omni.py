# apps/api/tests/services/media/test_omni.py

"""Omni requests and responses, from interactions recorded on 2026-11-17."""

import base64
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from google.genai.interactions import Interaction

from services.media import omni
from services.media.generation import VideoGenerationError, VideoGenerationRequest

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
