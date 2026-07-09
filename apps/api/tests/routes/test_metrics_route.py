"""HTTP-boundary tests for the operational metrics endpoint."""

import pytest
from httpx import AsyncClient

from core.settings import settings

pytestmark = pytest.mark.asyncio


async def test_metrics_route_returns_404_when_disabled(
    db_async_client: AsyncClient,
) -> None:
    response = await db_async_client.get("/api/metrics")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["detail"] == "Not found"


async def test_metrics_route_returns_prometheus_payload_when_enabled(
    db_async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "METRICS_ENABLED", True)
    monkeypatch.setattr(settings, "METRICS_TOKEN", None)

    response = await db_async_client.get("/api/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert b"# HELP" in response.content


async def test_metrics_route_rejects_missing_token(
    db_async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "METRICS_ENABLED", True)
    monkeypatch.setattr(settings, "METRICS_TOKEN", "secret-token")

    response = await db_async_client.get("/api/metrics")

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["detail"] == "Invalid metrics credentials"


async def test_metrics_route_accepts_configured_bearer_token(
    db_async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "METRICS_ENABLED", True)
    monkeypatch.setattr(settings, "METRICS_TOKEN", "secret-token")

    response = await db_async_client.get(
        "/api/metrics",
        headers={"Authorization": "Bearer secret-token"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
