# apps/api/tests/services/agents/models/test_helper_resolution.py

"""Contracts for shared native helper-model resolution mechanics."""

import re
from collections.abc import Callable

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
        supports_structured_output=structured_output,
        default_settings={"temperature": 0.2},
    )


@pytest.mark.parametrize(
    ("is_configured", "expected"),
    [
        (lambda provider: provider != "google", ("anthropic", "openai")),
        (lambda provider: provider == "google", ("google",)),
    ],
)
def test_configured_helper_providers_uses_caller_predicate_in_stable_order(
    is_configured: Callable[[str], bool],
    expected: tuple[str, ...],
) -> None:
    assert (
        resolution.configured_helper_providers(
            ("anthropic", "google", "openai"),
            is_configured=is_configured,
        )
        == expected
    )


@pytest.mark.parametrize(
    ("providers", "expected"),
    [
        ((), "none"),
        (("openai",), "openai"),
        (("anthropic", "openai"), "anthropic and openai"),
        (("anthropic", "google", "openai"), "anthropic, google, and openai"),
    ],
)
def test_format_provider_list(providers: tuple[str, ...], expected: str) -> None:
    assert resolution.format_provider_list(providers) == expected


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


def test_require_helper_model_resolves_default_and_catalog_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(resolution, "_require_active", lambda _provider, _model: _model_info())

    resolved = resolution.require_helper_model(
        provider=" OPENAI ",
        model=None,
        supported=("openai",),
        defaults={"openai": "helper-model"},
        tool_name="web_search",
    )

    assert resolved.provider == "openai"
    assert resolved.model == "helper-model"
    assert resolved.settings == {"temperature": 0.2}


def test_require_helper_model_rejects_unknown_model(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(_provider: str, _model: str) -> ModelInfo:
        raise ModelConfigurationError("unknown")

    monkeypatch.setattr(resolution, "_require_active", reject)
    monkeypatch.setattr(resolution, "find_model", lambda _provider, _model: None)

    with pytest.raises(
        ModelRetry,
        match=re.escape(
            "Unknown native classify helper model. Choose a model from the "
            "openai model catalog or omit model."
        ),
    ):
        resolution.require_helper_model(
            provider="openai",
            model="missing-model",
            supported=("openai",),
            defaults={"openai": "helper-model"},
            tool_name="classify",
        )


def test_require_helper_model_rejects_deprecated_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject(_provider: str, _model: str) -> ModelInfo:
        raise ModelConfigurationError("deprecated")

    monkeypatch.setattr(resolution, "_require_active", reject)
    monkeypatch.setattr(resolution, "find_model", lambda _provider, _model: _model_info())

    with pytest.raises(ModelRetry, match="Model 'openai:helper-model' is deprecated"):
        resolution.require_helper_model(
            provider="openai",
            model="helper-model",
            supported=("openai",),
            defaults={"openai": "helper-model"},
            tool_name="classify",
        )


def test_require_helper_model_rejects_unsupported_provider() -> None:
    with pytest.raises(
        ModelRetry,
        match="Provider 'azure' does not support native run_code",
    ):
        resolution.require_helper_model(
            provider="azure",
            model=None,
            supported=("openai",),
            defaults={"openai": "helper-model"},
            tool_name="run_code",
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
