# apps/api/tests/services/embeddings/test_settings.py

"""Embedding settings validation tests."""

from typing import Any

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from core.settings import Settings


def _production_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "ENVIRONMENT": "production",
        "STORAGE_PROVIDER": "s3",
        "EMAIL_PROVIDER": "ses",
        "SECRET_PROVIDER": "aws_secrets_manager",
        "DATABASE_URL": (
            "postgresql+asyncpg://praxis_app:postgres@db.example.com/postgres?sslmode=require"
        ),
        "DATABASE_MAINTENANCE_URL": (
            "postgresql+asyncpg://maintenance:postgres@db.example.com/postgres?sslmode=require"
        ),
        "SECRET_KEY": "x" * 40,
        "ENCRYPTION_KEYS": Fernet.generate_key().decode(),
        "SECURE_COOKIES": True,
        "CREDENTIAL_MASTER_KEYS": None,
        "INTERNAL_SCHEDULE_TRIGGER_SECRET": "test-schedule-secret-value",
        "S3_PUBLIC_ASSETS_BUCKET": "public-assets",
        "WORKSPACE_BUCKET_PREFIX": "praxis-test",
        "AWS_REGION": "eu-west-2",
        "AWS_ACCOUNT_ID": "123456789012",
        "PUBLIC_ASSETS_BASE_URL": "https://assets.example.com",
        "OPENAI_API_KEY": "sk-openai-test",
        "ARTIFACT_SHARING_ENABLED": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_embedding_settings_defaults() -> None:
    resolved = Settings()

    assert resolved.EMBEDDINGS_PROVIDER == "openai"
    assert resolved.EMBEDDINGS_MODEL == "text-embedding-3-small"
    assert resolved.EMBEDDINGS_DIMENSIONS == 1024


@pytest.mark.parametrize("dimensions", [511, 1025])
def test_embedding_dimensions_are_bounded(dimensions: int) -> None:
    with pytest.raises(ValidationError):
        Settings(EMBEDDINGS_DIMENSIONS=dimensions)


def test_ollama_requires_explicit_base_url() -> None:
    with pytest.raises(ValidationError, match="EMBEDDINGS_OLLAMA_BASE_URL"):
        Settings(EMBEDDINGS_PROVIDER="ollama", EMBEDDINGS_OLLAMA_BASE_URL=None)


def test_production_openai_embeddings_require_api_key() -> None:
    with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
        _production_settings(OPENAI_API_KEY=None)


@pytest.mark.parametrize("api_key", [None, " "])
def test_production_google_embeddings_require_api_key(api_key: str | None) -> None:
    with pytest.raises(ValidationError, match="GOOGLE_API_KEY"):
        _production_settings(
            EMBEDDINGS_PROVIDER="google",
            EMBEDDINGS_MODEL="gemini-embedding-2",
            GOOGLE_API_KEY=api_key,
        )
