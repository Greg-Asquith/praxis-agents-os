# apps/api/tests/services/agents/models/test_helper_resolution.py

"""Contracts for shared native helper-model resolution mechanics."""

import re

import pytest
from pydantic_ai import ModelRetry

from services.agents.models import resolution
from services.agents.models.domain import ModelConfigurationError, ModelInfo


def _model_info(*, structured_output: bool = True) -> ModelInfo:
    return ModelInfo(
        provider="openai",
        model="helper-model",
        display_name="Helper model",
        context_window=1_000,
        model_type="standard",
        supports_structured_output=structured_output,
        default_settings={"temperature": 0.2},
    )


def test_require_configured_provider_preserves_helper_error_contract() -> None:
    resolution.require_configured_provider(
        "openai",
        configured=("openai",),
        supported=("openai",),
        tool_name="web_search",
    )

    with pytest.raises(
        ModelRetry,
        match=re.escape(
            "Provider 'google' is not configured for native web_search. "
            "Available configured providers: openai."
        ),
    ):
        resolution.require_configured_provider(
            "google",
            configured=("openai",),
            supported=("google", "openai"),
            tool_name="web_search",
        )

    with pytest.raises(ModelRetry, match="No native web_search providers are configured"):
        resolution.require_configured_provider(
            "openai",
            configured=(),
            supported=("openai",),
            tool_name="web_search",
        )


def test_require_helper_model_rejects_deprecated_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject(_provider: str, _model: str) -> ModelInfo:
        raise ModelConfigurationError("deprecated")

    monkeypatch.setattr(resolution, "_require_active", reject)
    monkeypatch.setattr(resolution, "find_model", lambda _provider, _model: _model_info())

    with pytest.raises(ModelRetry, match="deprecated"):
        resolution.require_helper_model(
            provider="openai",
            model="helper-model",
            supported=("openai",),
            defaults={"openai": "helper-model"},
            tool_name="classify",
        )


def test_require_helper_model_can_require_structured_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        resolution,
        "_require_active",
        lambda _provider, _model: _model_info(structured_output=False),
    )

    with pytest.raises(ModelRetry, match="does not support structured output"):
        resolution.require_helper_model(
            provider="openai",
            model="helper-model",
            supported=("openai",),
            defaults={"openai": "helper-model"},
            tool_name="classify",
            require_structured_output=True,
        )
