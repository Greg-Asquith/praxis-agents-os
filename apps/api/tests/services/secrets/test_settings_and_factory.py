"""Secrets-provider selection and production gating."""

from typing import Any

import pytest
from cryptography.fernet import Fernet

from core.settings import Settings, settings
from services.secrets import factory

LOCAL_EXAMPLE_SECRET_KEY = "not-a-secret-local-development-secret-key-change-me"
LOCAL_EXAMPLE_ENCRYPTION_KEY = "bm90LWEtc2VjcmV0LWxvY2FsLWRldi1rZXktMDAwMDA="


def _production_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "ENVIRONMENT": "production",
        "STORAGE_PROVIDER": "s3",
        "EMAIL_PROVIDER": "ses",
        "DATABASE_URL": (
            "postgresql+asyncpg://postgres:postgres@db.example.com/postgres?sslmode=require"
        ),
        "SECRET_KEY": "x" * 40,
        "ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "SECURE_COOKIES": True,
        "INTERNAL_SCHEDULE_TRIGGER_SECRET": "test-schedule-secret-value",
        "S3_PUBLIC_ASSETS_BUCKET": "public-assets",
        "S3_PRIVATE_ASSETS_BUCKET": "private-assets",
        "AWS_REGION": "eu-west-2",
        "PUBLIC_ASSETS_BASE_URL": "https://assets.example.com",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.mark.parametrize(
    ("provider", "overrides", "expected"),
    [
        ("local", {}, "only allowed"),
        ("gcp_secret_manager", {"GCP_PROJECT_ID": ""}, "GCP_PROJECT_ID"),
        ("azure_key_vault", {"AZURE_KEY_VAULT_URL": ""}, "AZURE_KEY_VAULT_URL"),
        ("aws_secrets_manager", {"AWS_REGION": ""}, "AWS_REGION"),
    ],
)
def test_production_secret_provider_validation(provider, overrides, expected) -> None:
    with pytest.raises(ValueError, match=expected):
        _production_settings(SECRET_PROVIDER=provider, **overrides)


def test_local_master_keys_cannot_leave_local() -> None:
    with pytest.raises(ValueError, match="CREDENTIAL_MASTER_KEYS"):
        _production_settings(
            SECRET_PROVIDER="aws_secrets_manager",  # noqa: S106 - provider selector
            CREDENTIAL_MASTER_KEYS=Fernet.generate_key().decode(),
        )


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"SECRET_KEY": LOCAL_EXAMPLE_SECRET_KEY}, "SECRET_KEY"),
        ({"ENCRYPTION_KEY": LOCAL_EXAMPLE_ENCRYPTION_KEY}, "ENCRYPTION_KEY"),
        ({"SECURE_COOKIES": False}, "SECURE_COOKIES"),
    ],
)
def test_public_local_security_defaults_cannot_leave_local(overrides, expected) -> None:
    with pytest.raises(ValueError, match=expected):
        _production_settings(**overrides)


def test_public_local_security_defaults_are_allowed_in_local_environment() -> None:
    resolved = Settings(
        _env_file=None,
        ENVIRONMENT="local",
        SECRET_KEY=LOCAL_EXAMPLE_SECRET_KEY,
        ENCRYPTION_KEY=LOCAL_EXAMPLE_ENCRYPTION_KEY,
        SECURE_COOKIES=False,
    )

    assert resolved.SECRET_KEY.get_secret_value() == LOCAL_EXAMPLE_SECRET_KEY
    assert resolved.ENCRYPTION_KEY.get_secret_value() == LOCAL_EXAMPLE_ENCRYPTION_KEY
    assert resolved.SECURE_COOKIES is False


def test_non_local_integration_oauth_redirect_requires_https() -> None:
    with pytest.raises(ValueError, match="INTEGRATIONS_OAUTH_REDIRECT_URI must use HTTPS"):
        _production_settings(
            SECRET_PROVIDER="aws_secrets_manager",  # noqa: S106 - provider selector
            CREDENTIAL_MASTER_KEYS=None,
            INTEGRATIONS_OAUTH_REDIRECT_URI="http://api.example.test/callback",
        )


def test_local_integration_oauth_redirect_may_use_http() -> None:
    resolved = Settings(INTEGRATIONS_OAUTH_REDIRECT_URI="http://localhost:8000/callback")
    assert resolved.INTEGRATIONS_OAUTH_REDIRECT_URI.startswith("http://")


def test_factory_supports_all_four_backends(monkeypatch) -> None:
    cases = {
        "local": "LocalSecretsProvider",
        "gcp_secret_manager": "GcpSecretManagerProvider",
        "azure_key_vault": "AzureKeyVaultProvider",
        "aws_secrets_manager": "AwsSecretsManagerProvider",
    }
    monkeypatch.setattr(settings, "GCP_PROJECT_ID", "project")
    monkeypatch.setattr(settings, "AZURE_KEY_VAULT_URL", "https://vault.example")
    monkeypatch.setattr(settings, "AWS_REGION", "eu-west-2")
    for provider_key, class_name in cases.items():
        monkeypatch.setattr(settings, "SECRET_PROVIDER", provider_key)
        factory._provider = None
        factory._provider_key = None
        assert type(factory.get_secrets_provider()).__name__ == class_name
    factory._provider = None
    factory._provider_key = None
