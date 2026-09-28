"""Transport-aware model settings and credential configuration."""

import pytest

from core.settings import settings
from services.agents.models.domain import (
    PROVIDER_ANTHROPIC,
    PROVIDER_AZURE,
    PROVIDER_GOOGLE,
    PROVIDER_META,
    PROVIDER_MISTRAL,
    PROVIDER_OPENAI,
    PROVIDER_XAI,
)
from services.agents.models.utils import (
    has_provider_api_key,
    is_provider_configured,
    provider_transport,
)
from tests.support.settings import production_settings


@pytest.mark.parametrize(
    ("provider", "setting", "enabled", "expected_transport"),
    [
        (PROVIDER_OPENAI, None, False, "direct"),
        (PROVIDER_AZURE, None, False, "direct"),
        (PROVIDER_GOOGLE, "GOOGLE_VERTEX_AI", False, "direct"),
        (PROVIDER_GOOGLE, "GOOGLE_VERTEX_AI", True, "google-cloud"),
        (PROVIDER_ANTHROPIC, "ANTHROPIC_VERTEX_AI", False, "direct"),
        (PROVIDER_ANTHROPIC, "ANTHROPIC_VERTEX_AI", True, "google-cloud"),
        (PROVIDER_META, None, False, "google-cloud"),
        (PROVIDER_MISTRAL, None, False, "google-cloud"),
        (PROVIDER_XAI, None, False, "google-cloud"),
    ],
)
def test_provider_transport_reports_active_route(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    setting: str | None,
    enabled: bool,
    expected_transport: str,
) -> None:
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_AI", False)
    monkeypatch.setattr(settings, "ANTHROPIC_VERTEX_AI", False)
    if setting is not None:
        monkeypatch.setattr(settings, setting, enabled)

    assert provider_transport(provider) == expected_transport


@pytest.mark.parametrize("provider", [PROVIDER_META, PROVIDER_MISTRAL, PROVIDER_XAI])
def test_partner_provider_configuration_requires_switch_and_project(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
) -> None:
    monkeypatch.setattr(settings, "VERTEX_PARTNER_MODELS_ENABLED", False)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", "vertex-project")
    monkeypatch.setattr(settings, "GCP_PROJECT_ID", None)
    assert is_provider_configured(provider) is False
    assert has_provider_api_key(provider) is False

    monkeypatch.setattr(settings, "VERTEX_PARTNER_MODELS_ENABLED", True)
    assert is_provider_configured(provider) is True

    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", None)
    assert is_provider_configured(provider) is False


@pytest.mark.parametrize(
    ("provider", "switch_setting"),
    [
        (PROVIDER_GOOGLE, "GOOGLE_VERTEX_AI"),
        (PROVIDER_ANTHROPIC, "ANTHROPIC_VERTEX_AI"),
        (PROVIDER_META, "VERTEX_PARTNER_MODELS_ENABLED"),
    ],
)
def test_production_vertex_provider_accepts_deployment_project_fallback(
    provider: str,
    switch_setting: str,
) -> None:
    resolved = production_settings(
        DEFAULT_MODEL_PROVIDER=provider,
        CONVERSATION_NAMING_PROVIDER=provider,
        AGENT_HISTORY_SUMMARY_MODEL_PROVIDER=provider,
        **{
            switch_setting: True,
            "GOOGLE_VERTEX_PROJECT": None,
            "GCP_PROJECT_ID": "deployment-project",
            "GOOGLE_API_KEY": None,
            "ANTHROPIC_API_KEY": None,
        },
    )

    assert provider == resolved.DEFAULT_MODEL_PROVIDER
