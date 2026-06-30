# apps/api/tests/conftest.py
"""Shared pytest fixtures for the API test suite."""

import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from tests.support.database import make_async_test_database_url, require_test_database_url
from tests.support.settings import configure_test_environment

configure_test_environment()


@pytest.fixture(scope="session")
def app() -> FastAPI:
    """Return the FastAPI app with test-safe environment defaults applied."""
    from main import app as fastapi_app

    return fastapi_app


@pytest.fixture(scope="session")
def openapi_schema(app: FastAPI) -> dict[str, Any]:
    """Return the generated OpenAPI schema for contract tests."""
    return app.openapi()


@pytest_asyncio.fixture
async def async_client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Return an HTTPX client mounted directly against the ASGI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Return the configured PostgreSQL test database URL or skip cleanly."""
    return require_test_database_url()


@pytest.fixture(scope="session")
def migrated_test_database(test_database_url: str) -> str:
    """Apply migrations once to the configured PostgreSQL test database."""
    from alembic.config import Config

    from alembic import command

    os.environ["DATABASE_URL"] = test_database_url
    api_root = Path(__file__).resolve().parents[1]
    config = Config(str(api_root / "alembic.ini"))
    command.upgrade(config, "heads")
    return test_database_url


@pytest_asyncio.fixture
async def db_session_factory(
    migrated_test_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Bind app database sessions to a per-test rollback-only Postgres transaction."""
    from core import database as database_module

    engine = create_async_engine(
        make_async_test_database_url(migrated_test_database),
        poolclass=NullPool,
    )
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session_factory = async_sessionmaker(
            bind=connection,
            class_=AsyncSession,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        monkeypatch.setattr(database_module, "_async_engine", engine)
        monkeypatch.setattr(database_module, "_async_session_factory", session_factory)

        try:
            yield session_factory
        finally:
            if transaction.is_active:
                await transaction.rollback()

    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Return a database session isolated inside the current test transaction."""
    async with db_session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def db_async_client(
    app: FastAPI,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    """Return an ASGI client whose app database sessions use the test transaction."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
