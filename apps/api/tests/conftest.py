# apps/api/tests/conftest.py
"""Shared pytest fixtures for the API test suite."""

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from tests.support.database import require_test_database_url
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
