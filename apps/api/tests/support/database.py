# apps/api/tests/support/database.py

"""Database helpers for API tests."""

import fcntl
import hashlib
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

TEST_DATABASE_URL_ENV_VAR = "TEST_DATABASE_URL"


def _database_lock_path(database_url: str) -> Path:
    url = make_url(database_url)
    identity = "|".join(
        (
            url.get_backend_name(),
            url.host or "",
            str(url.port or ""),
            url.database or "",
        )
    )
    digest = hashlib.sha256(identity.encode()).hexdigest()[:20]
    return Path(tempfile.gettempdir()) / f"praxis-pytest-{digest}.lock"


@contextmanager
def serialize_test_database(database_url: str) -> Iterator[None]:
    """Prevent concurrent pytest processes from sharing one mutable database."""
    lock_path = _database_lock_path(database_url)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, "a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def require_test_database_url() -> str:
    """Return the configured PostgreSQL test database URL or skip the test."""
    database_url = os.getenv(TEST_DATABASE_URL_ENV_VAR)
    if not database_url:
        pytest.skip(f"Set {TEST_DATABASE_URL_ENV_VAR} to run database-backed API tests")

    url = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        pytest.fail("API database tests must use PostgreSQL, not SQLite")

    return database_url


def make_async_test_database_url(database_url: str) -> str:
    """Return an asyncpg SQLAlchemy URL for the configured PostgreSQL test database."""
    url = make_url(database_url)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+asyncpg")
    return url.render_as_string(hide_password=False)
