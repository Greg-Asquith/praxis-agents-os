"""Transport-aware model settings and credential configuration."""

import pytest
from pydantic import SecretStr, ValidationError

from core.settings import Settings, settings
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
    vertex_project,
)
from tests.support.settings import production_settings


def test_vertex_transport_settings_have_safe_defaults() -> None:
    resolved = Settings(_env_file=None)

    assert resolved.ANTHROPIC_VERTEX_AI is False
    assert resolved.ANTHROPIC_VERTEX_LOCATION == "global"
    assert resolved.VERTEX_PARTNER_MODELS_ENABLED is False
    assert resolved.VERTEX_PARTNER_MODEL_LOCATIONS == {}


@pytest.mark.parametrize(
    ("vertex_project_value", "gcp_project_id", "expected_project"),
    [
        ("vertex-project", "deployment-project", "vertex-project"),
        (None, "deployment-project", "deployment-project"),
        ("  ", "deployment-project", "deployment-project"),
        (None, None, None),
    ],
)
def test_vertex_project_uses_explicit_project_then_deployment_fallback(
    monkeypatch: pytest.MonkeyPatch,
    vertex_project_value: str | None,
    gcp_project_id: str | None,
    expected_project: str | None,
) -> None:
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", vertex_project_value)
    monkeypatch.setattr(settings, "GCP_PROJECT_ID", gcp_project_id)

    assert vertex_project() == expected_project


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
    ("provider", "switch_setting", "key_setting"),
    [
        (PROVIDER_GOOGLE, "GOOGLE_VERTEX_AI", "GOOGLE_API_KEY"),
        (PROVIDER_ANTHROPIC, "ANTHROPIC_VERTEX_AI", "ANTHROPIC_API_KEY"),
    ],
)
def test_first_party_vertex_configuration_requires_only_project(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    switch_setting: str,
    key_setting: str,
) -> None:
    monkeypatch.setattr(settings, switch_setting, True)
    monkeypatch.setattr(settings, key_setting, None)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", None)
    monkeypatch.setattr(settings, "GCP_PROJECT_ID", "deployment-project")

    assert is_provider_configured(provider) is True

    monkeypatch.setattr(settings, "GCP_PROJECT_ID", None)
    assert is_provider_configured(provider) is False


@pytest.mark.parametrize(
    (
        "provider",
        "switch_setting",
        "key_setting",
        "environment",
        "enabled",
        "project",
        "api_key",
        "expected_error",
    ),
    [
        (
            PROVIDER_GOOGLE,
            "GOOGLE_VERTEX_AI",
            "GOOGLE_API_KEY",
            "production",
            False,
            "vertex-project",
            "direct-key",
            None,
        ),
        (
            PROVIDER_GOOGLE,
            "GOOGLE_VERTEX_AI",
            "GOOGLE_API_KEY",
            "production",
            False,
            None,
            "direct-key",
            None,
        ),
        (
            PROVIDER_GOOGLE,
            "GOOGLE_VERTEX_AI",
            "GOOGLE_API_KEY",
            "production",
            False,
            None,
            None,
            "GOOGLE_API_KEY",
        ),
        (
            PROVIDER_GOOGLE,
            "GOOGLE_VERTEX_AI",
            "GOOGLE_API_KEY",
            "production",
            True,
            "vertex-project",
            None,
            None,
        ),
        (
            PROVIDER_GOOGLE,
            "GOOGLE_VERTEX_AI",
            "GOOGLE_API_KEY",
            "production",
            True,
            None,
            None,
            "GOOGLE_VERTEX_PROJECT or GCP_PROJECT_ID",
        ),
        (PROVIDER_GOOGLE, "GOOGLE_VERTEX_AI", "GOOGLE_API_KEY", "local", False, None, None, None),
        (PROVIDER_GOOGLE, "GOOGLE_VERTEX_AI", "GOOGLE_API_KEY", "local", True, None, None, None),
        (
            PROVIDER_ANTHROPIC,
            "ANTHROPIC_VERTEX_AI",
            "ANTHROPIC_API_KEY",
            "production",
            False,
            "vertex-project",
            "direct-key",
            None,
        ),
        (
            PROVIDER_ANTHROPIC,
            "ANTHROPIC_VERTEX_AI",
            "ANTHROPIC_API_KEY",
            "production",
            False,
            None,
            "direct-key",
            None,
        ),
        (
            PROVIDER_ANTHROPIC,
            "ANTHROPIC_VERTEX_AI",
            "ANTHROPIC_API_KEY",
            "production",
            False,
            None,
            None,
            "ANTHROPIC_API_KEY",
        ),
        (
            PROVIDER_ANTHROPIC,
            "ANTHROPIC_VERTEX_AI",
            "ANTHROPIC_API_KEY",
            "production",
            True,
            "vertex-project",
            None,
            None,
        ),
        (
            PROVIDER_ANTHROPIC,
            "ANTHROPIC_VERTEX_AI",
            "ANTHROPIC_API_KEY",
            "production",
            True,
            None,
            None,
            "GOOGLE_VERTEX_PROJECT or GCP_PROJECT_ID",
        ),
        (
            PROVIDER_ANTHROPIC,
            "ANTHROPIC_VERTEX_AI",
            "ANTHROPIC_API_KEY",
            "local",
            False,
            None,
            None,
            None,
        ),
        (
            PROVIDER_ANTHROPIC,
            "ANTHROPIC_VERTEX_AI",
            "ANTHROPIC_API_KEY",
            "local",
            True,
            None,
            None,
            None,
        ),
    ],
)
def test_first_party_provider_settings_matrix(
    provider: str,
    switch_setting: str,
    key_setting: str,
    environment: str,
    enabled: bool,
    project: str | None,
    api_key: str | None,
    expected_error: str | None,
) -> None:
    overrides = {
        "ENVIRONMENT": environment,
        "DEFAULT_MODEL_PROVIDER": provider,
        "CONVERSATION_NAMING_PROVIDER": provider,
        "AGENT_HISTORY_SUMMARY_MODEL_PROVIDER": provider,
        switch_setting: enabled,
        key_setting: api_key,
        "GOOGLE_VERTEX_PROJECT": project,
        "GCP_PROJECT_ID": None,
    }

    if expected_error is not None:
        with pytest.raises(ValidationError, match=expected_error):
            production_settings(**overrides)
        return

    resolved = production_settings(**overrides)
    assert provider == resolved.DEFAULT_MODEL_PROVIDER


@pytest.mark.parametrize("provider", [PROVIDER_META, PROVIDER_MISTRAL, PROVIDER_XAI])
@pytest.mark.parametrize(
    ("environment", "enabled", "project", "expected_error"),
    [
        ("production", False, "vertex-project", "VERTEX_PARTNER_MODELS_ENABLED"),
        ("production", False, None, "VERTEX_PARTNER_MODELS_ENABLED"),
        ("production", True, "vertex-project", None),
        ("production", True, None, "GOOGLE_VERTEX_PROJECT or GCP_PROJECT_ID"),
        ("local", False, None, None),
        ("local", True, None, None),
    ],
)
def test_partner_provider_settings_matrix(
    provider: str,
    environment: str,
    enabled: bool,
    project: str | None,
    expected_error: str | None,
) -> None:
    overrides = {
        "ENVIRONMENT": environment,
        "DEFAULT_MODEL_PROVIDER": provider,
        "CONVERSATION_NAMING_PROVIDER": provider,
        "AGENT_HISTORY_SUMMARY_MODEL_PROVIDER": provider,
        "VERTEX_PARTNER_MODELS_ENABLED": enabled,
        "GOOGLE_VERTEX_PROJECT": project,
        "GCP_PROJECT_ID": None,
    }

    if expected_error is not None:
        with pytest.raises(ValidationError, match=expected_error):
            production_settings(**overrides)
        return

    resolved = production_settings(**overrides)
    assert provider == resolved.DEFAULT_MODEL_PROVIDER


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


def test_direct_provider_key_configuration_remains_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("openai-key"))
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", SecretStr("anthropic-key"))
    monkeypatch.setattr(settings, "ANTHROPIC_VERTEX_AI", False)

    assert is_provider_configured(PROVIDER_OPENAI) is True
    assert is_provider_configured(PROVIDER_ANTHROPIC) is True
