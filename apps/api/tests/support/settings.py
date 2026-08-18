# apps/api/tests/support/settings.py

"""Test environment defaults used before importing application settings."""

import os

from cryptography.fernet import Fernet


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
        '["gmail", "google_ads", "google_analytics", "airtable", "bigquery"]',
    )
    os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")
    os.environ.setdefault("GOOGLE_API_KEY", "google-test")
    os.environ.setdefault("OPENAI_API_KEY", "sk-openai-test")
