# apps/api/tests/middleware/test_artifact_host.py

"""Focused tests for artifact host isolation middleware."""

import pytest
from fastapi import FastAPI
from httpx2 import ASGITransport, AsyncClient

from middleware.artifact_host import ArtifactHostMiddleware

ARTIFACT_ORIGIN = "https://praxis-usercontent.example"


def _build_app(artifact_origin: str | None) -> FastAPI:
    app = FastAPI()
    app.add_middleware(ArtifactHostMiddleware, artifact_origin=artifact_origin)

    @app.get("/artifacts/shared/{token}")
    async def shared(token: str) -> dict[str, bool]:
        return {"ok": True}

    @app.get("/artifacts/view/{artifact_id}/{version_id}")
    async def view(artifact_id: str, version_id: str) -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/v1/users/me")
    async def me() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    return app


def _client(app: FastAPI, base_url: str) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url=base_url)


@pytest.mark.asyncio
async def test_artifact_host_serves_only_artifact_paths() -> None:
    app = _build_app(ARTIFACT_ORIGIN)
    async with _client(app, ARTIFACT_ORIGIN) as client:
        shared = await client.get(f"/artifacts/shared/{'a' * 43}")
        view = await client.get("/artifacts/view/artifact-id/version-id")
        api = await client.get("/api/v1/users/me")
        health = await client.get("/healthz")

    assert shared.status_code == 200
    assert view.status_code == 200
    assert api.status_code == 404
    assert api.headers["content-type"].startswith("application/problem+json")
    assert health.status_code == 404


@pytest.mark.asyncio
async def test_api_host_refuses_artifact_paths() -> None:
    app = _build_app(ARTIFACT_ORIGIN)
    async with _client(app, "https://api.praxis.example") as client:
        shared = await client.get(f"/artifacts/shared/{'a' * 43}")
        view = await client.get("/artifacts/view/artifact-id/version-id")
        api = await client.get("/api/v1/users/me")

    assert shared.status_code == 404
    assert view.status_code == 404
    assert api.status_code == 200


@pytest.mark.asyncio
async def test_artifact_host_comparison_ignores_case_and_port() -> None:
    app = _build_app(ARTIFACT_ORIGIN)
    async with _client(app, "https://PRAXIS-USERCONTENT.example:8443") as client:
        shared = await client.get(f"/artifacts/shared/{'a' * 43}")
        api = await client.get("/api/v1/users/me")

    assert shared.status_code == 200
    assert api.status_code == 404


@pytest.mark.asyncio
async def test_gate_inactive_without_artifact_origin() -> None:
    app = _build_app("")
    async with _client(app, "http://localhost:8000") as client:
        shared = await client.get(f"/artifacts/shared/{'a' * 43}")
        api = await client.get("/api/v1/users/me")

    assert shared.status_code == 200
    assert api.status_code == 200
