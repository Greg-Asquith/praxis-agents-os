from typing import Any

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from core import observability
from core.settings import Settings


def test_settings_reject_agent_trace_content_in_production() -> None:
    with pytest.raises(ValidationError, match="AGENT_TRACING_INCLUDE_CONTENT"):
        _production_settings(AGENT_TRACING_INCLUDE_CONTENT=True)


def test_settings_allow_agent_trace_content_in_production_with_explicit_override() -> None:
    settings = _production_settings(
        AGENT_TRACING_INCLUDE_CONTENT=True,
        AGENT_TRACING_ALLOW_CONTENT_IN_PRODUCTION=True,
    )

    assert settings.AGENT_TRACING_INCLUDE_CONTENT is True
    assert settings.AGENT_TRACING_ALLOW_CONTENT_IN_PRODUCTION is True


def test_settings_allow_agent_trace_content_outside_production() -> None:
    settings = Settings(
        ENVIRONMENT="local",
        STORAGE_PROVIDER="local_fs",
        EMAIL_PROVIDER="console",
        SECRET_KEY="x" * 40,
        ENCRYPTION_KEY=Fernet.generate_key().decode(),
        AGENT_TRACING_INCLUDE_CONTENT=True,
    )

    assert settings.AGENT_TRACING_INCLUDE_CONTENT is True


def test_setup_agent_tracing_noops_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_calls: list[dict[str, Any]] = []
    instrument_calls: list[Any] = []

    monkeypatch.setattr(observability, "_agent_tracing_configured", False)
    monkeypatch.setattr(observability.settings, "AGENT_TRACING_ENABLED", False)
    monkeypatch.setattr(
        observability.logfire,
        "configure",
        lambda **kwargs: configure_calls.append(kwargs),
    )
    monkeypatch.setattr(
        observability.PydanticAgent,
        "instrument_all",
        staticmethod(lambda instrument=True: instrument_calls.append(instrument)),
    )

    observability.setup_agent_tracing()

    assert configure_calls == []
    assert instrument_calls == []
    assert observability._agent_tracing_configured is False


def test_setup_agent_tracing_configures_once(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_calls: list[dict[str, Any]] = []
    instrument_calls: list[Any] = []

    monkeypatch.setattr(observability, "_agent_tracing_configured", False)
    monkeypatch.setattr(observability.settings, "AGENT_TRACING_ENABLED", True)
    monkeypatch.setattr(observability.settings, "AGENT_TRACING_INCLUDE_CONTENT", True)
    monkeypatch.setattr(
        observability.logfire,
        "configure",
        lambda **kwargs: configure_calls.append(kwargs),
    )
    monkeypatch.setattr(
        observability.PydanticAgent,
        "instrument_all",
        staticmethod(lambda instrument=True: instrument_calls.append(instrument)),
    )

    observability.setup_agent_tracing()
    observability.setup_agent_tracing()

    assert configure_calls == [{"send_to_logfire": "if-token-present"}]
    assert len(instrument_calls) == 1
    instrumentation_settings = instrument_calls[0]
    assert instrumentation_settings.include_content is True
    assert instrumentation_settings.include_binary_content is False
    assert observability._agent_tracing_configured is True


def _production_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "ENVIRONMENT": "production",
        "STORAGE_PROVIDER": "s3",
        "EMAIL_PROVIDER": "ses",
        "DATABASE_URL": "postgresql+asyncpg://postgres:postgres@db.example.com/postgres?sslmode=require",
        "SECRET_KEY": "x" * 40,
        "ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "INTERNAL_SCHEDULE_TRIGGER_SECRET": "not-a-secret-test-schedule-secret",
        "OPENAI_API_KEY": "sk-test",
        "S3_PUBLIC_ASSETS_BUCKET": "public-assets",
        "S3_PRIVATE_ASSETS_BUCKET": "private-assets",
        "AWS_REGION": "eu-west-2",
        "PUBLIC_ASSETS_BASE_URL": "https://assets.example.com",
    }
    values.update(overrides)
    return Settings(**values)
