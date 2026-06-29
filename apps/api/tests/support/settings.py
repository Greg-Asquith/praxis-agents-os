# apps/api/tests/support/settings.py
"""Test environment defaults used before importing application settings."""

import os

from cryptography.fernet import Fernet


def configure_test_environment() -> None:
    """Set safe local defaults needed to import the API app in tests."""
    os.environ.setdefault("ENVIRONMENT", "local")
    os.environ.setdefault("STORAGE_PROVIDER", "local_fs")
    os.environ.setdefault("EMAIL_PROVIDER", "console")
    os.environ.setdefault("SECRET_KEY", "x" * 40)
    os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
