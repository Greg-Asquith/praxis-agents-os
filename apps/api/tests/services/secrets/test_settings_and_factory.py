"""Secrets-provider selection and production gating."""

from typing import Any

import pytest
from cryptography.fernet import Fernet

from core.settings import Settings, settings
from services.secrets import factory


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
        "INTERNAL_SCHEDULE_TRIGGER_SECRET": "test-schedule-secret-value",
        "S3_PUBLIC_ASSETS_BUCKET": "public-assets",
        "S3_PRIVATE_ASSETS_BUCKET": "private-assets",
        "AWS_REGION": "eu-west-2",
        "PUBLIC_ASSETS_BASE_URL": "https://assets.example.com",
    }
    values.update(overrides)
    return Settings(**values)


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
