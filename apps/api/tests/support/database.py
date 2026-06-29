# apps/api/tests/support/database.py
"""Database helpers for API tests."""

import os

import pytest

TEST_DATABASE_URL_ENV_VAR = "TEST_DATABASE_URL"


def require_test_database_url() -> str:
    """Return the configured PostgreSQL test database URL or skip the test."""
    database_url = os.getenv(TEST_DATABASE_URL_ENV_VAR)
    if not database_url:
        pytest.skip(f"Set {TEST_DATABASE_URL_ENV_VAR} to run database-backed API tests")

    if database_url.startswith("sqlite"):
        pytest.fail("API database tests must use PostgreSQL, not SQLite")

    return database_url
