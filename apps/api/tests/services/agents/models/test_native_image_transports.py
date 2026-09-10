"""Image-only Vertex model construction stays outside the chat catalogue."""

import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from pydantic import SecretStr
from pydantic_ai import ModelRetry
from pydantic_ai.messages import BinaryContent

from core.settings import settings
from services.agents.models import build_model
from services.agents.models.domain import ModelConfigurationError
from services.agents.models.registry import find_model
from services.agents.models.vertex_clients import close_vertex_clients
from services.agents.runtime.tools.native.image_generation import (
    configured_native_image_providers,
    resolve_image_generation_model,
    run_native_image_generation,
)
from tests.support.google_native import mock_google_native
from tests.support.openai_images import IMAGE_BYTES


@pytest.mark.parametrize("location", ["auto", "global", "eu", "us"])
async def test_vertex_image_model_uses_supported_location_without_chat_entry(monkeypatch, location):
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_AI", True)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", "image-test")
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_LOCATION", location)
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", None)
    assert find_model("google", "gemini-3.1-flash-image") is None
    try:
        model = build_model(resolve_image_generation_model(model_provider="google"))
        assert model.model_name == "gemini-3.1-flash-image"
        assert model.provider.client._api_client.vertexai is True
        assert model.provider.client._api_client.project == "image-test"
        assert model.provider.client._api_client.location == (
            "eu" if location == "auto" else location
        )
    finally:
        await close_vertex_clients()


@pytest.mark.parametrize(
    "vertex,location", [(False, "global"), (True, "auto"), (True, "eu"), (True, "us")]
)
@pytest.mark.parametrize("action", ["generate", "edit", "video_to_image"])
async def test_google_image_adapter_preserves_media_and_transport(
    monkeypatch, vertex, location, action
):
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", None if vertex else SecretStr("image-key"))
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", "image-test")
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_LOCATION", location)
    meter = AsyncMock()
    monkeypatch.setattr("services.ai_usage.run_metered_helper.record_ai_usage_durable", meter)
    deps = SimpleNamespace(
        **{
            name: SimpleNamespace(id=uuid4())
            for name in (
                "workspace",
                "agent",
                "user",
                "run",
                "conversation",
            )
        }
    )
    media = (
        ()
        if action == "generate"
        else (
            (BinaryContent(data=IMAGE_BYTES, media_type="image/png"),) * 2
            if action == "edit"
            else (BinaryContent(data=b"video", media_type="video/mp4"),)
        )
    )
    async with mock_google_native(monkeypatch, vertex=vertex) as requests:
        spec = resolve_image_generation_model(model_provider="google")
        image = await run_native_image_generation(
            deps=deps,
            prompt="A fox",
            aspect_ratio="3:2",
            model_spec=spec,
            action=action,
            input_media=media,
        )
    assert image.data == IMAGE_BYTES
    [request] = requests
    body = json.loads(request.content)
    assert request.url.path.endswith("/gemini-3.1-flash-image:generateContent")
    if vertex:
        effective_location = "eu" if location == "auto" else location
        assert f"/projects/image-test/locations/{effective_location}/" in request.url.path
        assert request.headers["authorization"] == "Bearer test-adc"
        assert "x-goog-api-key" not in request.headers
        assert request.url.host == (
            "aiplatform.googleapis.com"
            if effective_location == "global"
            else f"aiplatform.{effective_location}.rep.googleapis.com"
        )
    else:
        assert request.url.host == "generativelanguage.googleapis.com"
        assert request.headers["x-goog-api-key"] == "image-key"
    parts = body["contents"][0]["parts"]
    assert len(parts) == 1 + len(media)
    for part, source in zip(parts[1:], media, strict=True):
        assert part["inlineData"]["mime_type" if vertex else "mimeType"] == source.media_type
        assert base64.urlsafe_b64decode(part["inlineData"]["data"]) == source.data
    assert body["generationConfig"]["responseModalities"] == ["IMAGE"]
    assert body["generationConfig"]["imageConfig"]["aspectRatio"] == "3:2"
    event = meter.call_args.args[0]
    assert (event.requests, event.input_tokens, event.output_tokens) == (1, 10, 20)


@pytest.mark.parametrize("failure", ["location", "model", "project"])
async def test_invalid_vertex_image_configuration_never_requests_provider(monkeypatch, failure):
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", SecretStr("must-not-fallback"))
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("openai-control"))
    monkeypatch.setattr(
        settings, "GOOGLE_VERTEX_PROJECT", "" if failure == "project" else "image-test"
    )
    monkeypatch.setattr(settings, "GCP_PROJECT_ID", "")
    monkeypatch.setattr(
        settings, "GOOGLE_VERTEX_LOCATION", "europe-west4" if failure == "location" else "auto"
    )
    constructor = Mock()
    async with mock_google_native(monkeypatch, vertex=True) as requests:
        monkeypatch.setattr("services.agents.models.vertex_clients.Client", constructor)
        with pytest.raises(
            ModelRetry,
            match={
                "location": "GOOGLE_VERTEX_LOCATION",
                "project": "GOOGLE_VERTEX_PROJECT",
                "model": "Omit model",
            }[failure],
        ):
            resolve_image_generation_model(
                model_provider="google",
                model="unknown-image" if failure == "model" else None,
            )
        if failure != "model":
            assert configured_native_image_providers() == ("openai",)
    constructor.assert_not_called()
    assert requests == []


def test_unknown_vertex_models_still_fail_closed(monkeypatch):
    from services.agents.models.vertex_clients import google_vertex_location

    monkeypatch.setattr(settings, "GOOGLE_VERTEX_LOCATION", "auto")
    with pytest.raises(ModelConfigurationError, match="Unknown model"):
        google_vertex_location("unknown-image")


async def test_vertex_inline_image_limit_fails_before_request(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", None)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", "image-test")
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_LOCATION", "auto")
    monkeypatch.setattr("services.ai_usage.run_metered_helper.record_ai_usage_durable", AsyncMock())
    deps = SimpleNamespace(
        **{
            name: SimpleNamespace(id=uuid4())
            for name in (
                "workspace",
                "agent",
                "user",
                "run",
                "conversation",
            )
        }
    )
    async with mock_google_native(monkeypatch, vertex=True) as requests:
        with pytest.raises(ModelRetry, match="7 MB"):
            await run_native_image_generation(
                deps=deps,
                prompt="A fox",
                aspect_ratio=None,
                model_spec=resolve_image_generation_model(model_provider="google"),
                action="edit",
                input_media=(
                    BinaryContent(
                        data=b"a" * 7_000_001,
                        media_type="image/png",
                    ),
                ),
            )
    assert requests == []


async def test_vertex_image_edit_rejects_gif_before_request(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", "image-test")
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_LOCATION", "global")
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", None)
    meter = AsyncMock()
    monkeypatch.setattr("services.ai_usage.run_metered_helper.record_ai_usage_durable", meter)
    deps = SimpleNamespace(
        **{
            name: SimpleNamespace(id=uuid4())
            for name in ("workspace", "agent", "user", "run", "conversation")
        }
    )
    async with mock_google_native(monkeypatch, vertex=True) as requests:
        with pytest.raises(ModelRetry, match="Convert the source image"):
            await run_native_image_generation(
                deps=deps,
                prompt="A fox",
                aspect_ratio=None,
                model_spec=resolve_image_generation_model(model_provider="google"),
                action="edit",
                input_media=(BinaryContent(data=b"GIF89a", media_type="image/gif"),),
            )
    assert requests == []
    meter.assert_not_called()
