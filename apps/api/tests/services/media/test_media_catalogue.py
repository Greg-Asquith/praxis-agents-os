# apps/api/tests/services/media/test_media_catalogue.py

"""Media catalogue validation, route choice, and refusals before any provider call."""

import pytest
from pydantic import SecretStr, ValidationError
from pydantic_ai import ModelRetry

from core.settings import settings
from services.agents.runtime.tools.native import image_generation
from services.media import catalogue
from services.media.catalogue import MediaCatalogue, available_route


def _model(**overrides) -> dict:
    return {
        "id": "test-image",
        "label": "Test Image",
        "tasks": ["text_to_image"],
        "lab": "Test Lab",
        "processing": "global",
        "strengths": "a test model",
        "indemnified": False,
        "routes": [{"route": "google", "model": "test-image-google", "usd_per_image": "0.04"}],
        **overrides,
    }


@pytest.fixture
def both_routes_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_AI", False)
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", SecretStr("google-test"))
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("sk-openai-test"))


@pytest.mark.parametrize(
    "bad",
    [
        {"tasks": ["text_to_audio"]},
        {"routes": [{"route": "google", "model": "test-image-google"}]},
    ],
    ids=["unknown task", "missing price"],
)
def test_catalogue_refuses_an_unknown_task_or_a_missing_price(bad: dict) -> None:
    with pytest.raises(ValidationError):
        MediaCatalogue.model_validate({"models": [_model(**bad)]})


def test_the_cheaper_configured_route_serves_a_model(both_routes_configured: None) -> None:
    [model] = MediaCatalogue.model_validate(
        {
            "models": [
                _model(
                    routes=[
                        {"route": "google", "model": "test-google", "usd_per_image": "0.04"},
                        {"route": "openai", "model": "test-openai", "usd_per_image": "0.02"},
                        {"route": "runway", "model": "test-runway", "usd_per_image": "0.01"},
                    ]
                )
            ]
        }
    ).models

    route = available_route(model, "text_to_image")

    # Runway is cheapest but has no backend, so it's never chosen.
    assert route is not None and route.route == "openai"


def test_a_model_is_refused_for_a_task_it_does_not_list(
    monkeypatch: pytest.MonkeyPatch, both_routes_configured: None
) -> None:
    generate_only = MediaCatalogue.model_validate({"models": [_model()]})
    monkeypatch.setattr(catalogue, "media_catalogue", lambda: generate_only)
    monkeypatch.setattr(image_generation, "media_catalogue", lambda: generate_only)

    with pytest.raises(ModelRetry, match="test-image can't edit images"):
        image_generation.resolve_image_model("test-image", "edit_image")
