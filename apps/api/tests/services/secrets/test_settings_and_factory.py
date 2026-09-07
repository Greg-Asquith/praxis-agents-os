"""Secrets-provider selection and production gating."""

import pytest
from cryptography.fernet import Fernet

from core.settings import Settings, settings
from services.secrets import factory
from tests.support.settings import production_settings

LOCAL_EXAMPLE_SECRET_KEY = "not-a-secret-local-development-secret-key-change-me"
LOCAL_EXAMPLE_ENCRYPTION_KEY = "bm90LWEtc2VjcmV0LWxvY2FsLWRldi1rZXktMDAwMDA="


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
        production_settings(SECRET_PROVIDER=provider, **overrides)


def test_local_master_keys_cannot_leave_local() -> None:
    with pytest.raises(ValueError, match="CREDENTIAL_MASTER_KEYS"):
        production_settings(
            SECRET_PROVIDER="aws_secrets_manager",  # noqa: S106 - provider selector
            CREDENTIAL_MASTER_KEYS=Fernet.generate_key().decode(),
        )


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"SECRET_KEY": LOCAL_EXAMPLE_SECRET_KEY}, "SECRET_KEY"),
        ({"ENCRYPTION_KEYS": LOCAL_EXAMPLE_ENCRYPTION_KEY}, "ENCRYPTION_KEYS"),
        ({"SECURE_COOKIES": False}, "SECURE_COOKIES"),
    ],
)
def test_public_local_security_defaults_cannot_leave_local(overrides, expected) -> None:
    with pytest.raises(ValueError, match=expected):
        production_settings(**overrides)


def test_public_local_security_defaults_are_allowed_in_local_environment() -> None:
    resolved = Settings(
        _env_file=None,
        ENVIRONMENT="local",
        SECRET_KEY=LOCAL_EXAMPLE_SECRET_KEY,
        ENCRYPTION_KEYS=LOCAL_EXAMPLE_ENCRYPTION_KEY,
        SECURE_COOKIES=False,
    )

    assert resolved.SECRET_KEY.get_secret_value() == LOCAL_EXAMPLE_SECRET_KEY
    assert resolved.application_encryption_keys == (LOCAL_EXAMPLE_ENCRYPTION_KEY,)
    assert resolved.SECURE_COOKIES is False


@pytest.mark.parametrize(
    "prefix",
    ["Uppercase", "leading-", "-trailing", "contains_underscore", "x" * 27],
)
def test_workspace_bucket_prefix_uses_cross_provider_safe_naming(prefix: str) -> None:
    with pytest.raises(ValueError, match="WORKSPACE_BUCKET_PREFIX"):
        Settings(_env_file=None, WORKSPACE_BUCKET_PREFIX=prefix)


def test_default_local_workspace_bucket_prefix_cannot_leave_local() -> None:
    with pytest.raises(ValueError, match="WORKSPACE_BUCKET_PREFIX"):
        production_settings(WORKSPACE_BUCKET_PREFIX="praxis-local")


def test_s3_storage_requires_account_id() -> None:
    with pytest.raises(ValueError, match="AWS_ACCOUNT_ID"):
        production_settings(
            SECRET_PROVIDER="aws_secrets_manager",  # noqa: S106 - provider selector
            CREDENTIAL_MASTER_KEYS=None,
            AWS_ACCOUNT_ID="",
        )


def test_s3_workspace_prefix_must_fit_account_regional_name() -> None:
    with pytest.raises(ValueError, match="at most 11 characters"):
        production_settings(
            SECRET_PROVIDER="aws_secrets_manager",  # noqa: S106 - provider selector
            CREDENTIAL_MASTER_KEYS=None,
            WORKSPACE_BUCKET_PREFIX="praxis-stage",
        )


def test_gcs_storage_requires_explicit_project_and_location() -> None:
    with pytest.raises(ValueError, match="GCP_PROJECT_ID, GCS_WORKSPACE_BUCKET_LOCATION"):
        Settings(
            _env_file=None,
            STORAGE_PROVIDER="gcs",
            GCS_PUBLIC_ASSETS_BUCKET="public-assets",
            GCP_PROJECT_ID="",
            GCS_WORKSPACE_BUCKET_LOCATION="",
        )


def test_non_local_integration_oauth_redirect_requires_https() -> None:
    with pytest.raises(ValueError, match="INTEGRATIONS_OAUTH_REDIRECT_URI must use HTTPS"):
        production_settings(
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
