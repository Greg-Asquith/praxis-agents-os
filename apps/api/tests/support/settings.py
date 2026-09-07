# apps/api/tests/support/settings.py

"""Test environment defaults used before importing application settings."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from cryptography.fernet import Fernet

if TYPE_CHECKING:
    from core.settings import Settings


def production_settings(**overrides: Any) -> Settings:
    """Creates valid production settings with caller-owned overrides."""
    from core.settings import Settings

    values: dict[str, Any] = {
        "ENVIRONMENT": "production",
        "STORAGE_PROVIDER": "s3",
        "EMAIL_PROVIDER": "ses",
        "SECRET_PROVIDER": "aws_secrets_manager",
        "CREDENTIAL_MASTER_KEYS": None,
        "DATABASE_URL": (
            "postgresql+asyncpg://praxis_app:postgres@db.example.com/postgres?sslmode=require"
        ),
        "DATABASE_MAINTENANCE_URL": (
            "postgresql+asyncpg://maintenance:postgres@db.example.com/postgres?sslmode=require"
        ),
        "SECRET_KEY": "x" * 40,
        "ENCRYPTION_KEYS": Fernet.generate_key().decode(),
        "SECURE_COOKIES": True,
        "OPENAI_API_KEY": "sk-openai-test",
        "GOOGLE_VERTEX_AI": False,
        "S3_PUBLIC_ASSETS_BUCKET": "public-assets",
        "WORKSPACE_BUCKET_PREFIX": "praxis-test",
        "AWS_REGION": "eu-west-2",
        "AWS_ACCOUNT_ID": "123456789012",
        "PUBLIC_ASSETS_BASE_URL": "https://assets.example.com",
        "APP_BASE_URL": "https://api.example.com",
        "FRONTEND_URL": "https://app.example.com",
        "INTEGRATIONS_OAUTH_REDIRECT_URI": ("https://api.example.com/integrations/oauth/callback"),
        "ARTIFACT_SHARING_ENABLED": False,
        "RATE_LIMIT_ENABLED": True,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def configure_test_environment() -> None:
    """Set safe local defaults needed to import the API app in tests."""
    test_database_url = os.getenv("TEST_DATABASE_URL")
    if test_database_url:
        if test_database_url.startswith("postgresql://"):
            test_database_url = test_database_url.replace(
                "postgresql://", "postgresql+asyncpg://", 1
            )
        os.environ.setdefault("DATABASE_URL", test_database_url)
        os.environ.setdefault("DATABASE_MAINTENANCE_URL", test_database_url)

    os.environ.setdefault("ENVIRONMENT", "local")
    os.environ.setdefault("STORAGE_PROVIDER", "local_fs")
    os.environ.setdefault("EMAIL_PROVIDER", "console")
    os.environ.setdefault("SECRET_KEY", "x" * 40)
    os.environ.setdefault("ENCRYPTION_KEYS", Fernet.generate_key().decode())
    os.environ.setdefault("CREDENTIAL_MASTER_KEYS", Fernet.generate_key().decode())
    os.environ.setdefault("SECURE_COOKIES", "false")
    os.environ.setdefault("SUPER_ADMIN_EMAILS", "admin@example.com")
    os.environ.setdefault(
        "INTEGRATIONS_ENABLED_PROVIDERS",
        '["gmail", "google_ads", "google_analytics", "google_search_console", "airtable", "bigquery", "notion"]',
    )
    os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")
    os.environ.setdefault("GOOGLE_API_KEY", "google-test")
    os.environ.setdefault("OPENAI_API_KEY", "sk-openai-test")
