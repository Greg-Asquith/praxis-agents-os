"""Operational liveness and readiness contracts."""

from core.exceptions.database import DatabaseError
from core.settings import settings


async def test_liveness_has_version_and_does_not_check_database(async_client, monkeypatch):
    async def fail_if_called() -> None:
        raise AssertionError("liveness must not access the database")

    monkeypatch.setattr("routes.health.readiness.check_database_connection", fail_if_called)

    response = await async_client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": settings.APP_VERSION}


async def test_readiness_reports_ready(async_client, monkeypatch):
    async def ready() -> None:
        return None

    monkeypatch.setattr("routes.health.readiness.check_database_connection", ready)

    response = await async_client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


async def test_readiness_reports_dependency_failure(async_client, monkeypatch):
    async def unavailable() -> None:
        raise DatabaseError("unavailable")

    monkeypatch.setattr("routes.health.readiness.check_database_connection", unavailable)

    response = await async_client.get("/readyz")

    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["title"] == "Service Not Ready"
