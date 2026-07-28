# apps/api/tests/routes/artifacts/test_artifact_routes.py

"""Artifact management and anonymous serving route tests."""

from collections.abc import Iterator
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from core.settings import settings
from models.artifacts import Artifact
from services.artifacts import create_artifact, create_artifact_view_url
from services.artifacts.domain import (
    artifact_frame_ancestors,
    build_html_csp,
    build_plain_csp,
)
from services.storage.errors import StorageNotFoundError
from services.storage.factory import get_storage_provider
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.support.auth import bearer_headers
from tests.support.storage import reset_storage_provider_cache

pytestmark = pytest.mark.asyncio


@pytest.fixture
def local_storage_settings(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "APP_BASE_URL", "http://testserver")
    reset_storage_provider_cache()
    try:
        yield
    finally:
        reset_storage_provider_cache()


def _relative_url(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.path}?{parsed.query}"


async def _seed(
    db: AsyncSession,
    *,
    artifact_type: str = "html",
    content: str = "<h1>Report</h1>",
) -> tuple[dict[str, str], Artifact, UUID, str]:
    user = build_user(email=f"artifact-route-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"artifact-route-{uuid4().hex[:8]}")
    membership = build_workspace_membership(workspace_id=workspace.id, user_id=user.id)
    db.add_all([user, workspace, membership])
    await db.flush()
    user.default_workspace_id = workspace.id
    artifact, revision = await create_artifact(
        db,
        workspace=workspace,
        title="Report",
        artifact_type=artifact_type,
        content=content,
        actor_user_id=user.id,
    )
    session = await session_manager.create_session(db, str(user.id))
    await db.commit()
    headers = bearer_headers(session["session_token"])
    headers["X-Workspace"] = workspace.slug
    return headers, artifact, revision.id, session["session_token"]


async def test_management_routes_and_view_url_round_trip(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    local_storage_settings: None,
) -> None:
    headers, artifact, version_id, _token = await _seed(db_session)
    listed = await db_async_client.get("/api/v1/artifacts/", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["version_count"] == 1
    assert "versions" not in listed.json()["items"][0]
    detail = await db_async_client.get(f"/api/v1/artifacts/{artifact.id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["versions"][0]["id"] == str(version_id)
    content = await db_async_client.get(
        f"/api/v1/artifacts/{artifact.id}/versions/{version_id}/content",
        headers=headers,
    )
    assert content.status_code == 200
    assert content.json()["content"] == "<h1>Report</h1>"
    view = await db_async_client.get(
        f"/api/v1/artifacts/{artifact.id}/versions/{version_id}/view-url",
        headers=headers,
    )
    assert view.status_code == 200
    served = await db_async_client.get(_relative_url(view.json()["url"]))
    assert served.status_code == 200


async def test_management_routes_hide_cross_workspace_artifacts(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    local_storage_settings: None,
) -> None:
    _headers, artifact, version_id, _token = await _seed(db_session)
    other_user = build_user(email=f"artifact-other-{uuid4().hex}@example.com")
    other_workspace = build_workspace(slug=f"artifact-other-{uuid4().hex[:8]}")
    other_membership = build_workspace_membership(
        workspace_id=other_workspace.id,
        user_id=other_user.id,
    )
    db_session.add_all([other_user, other_workspace, other_membership])
    await db_session.flush()
    other_user.default_workspace_id = other_workspace.id
    other_session = await session_manager.create_session(db_session, str(other_user.id))
    await db_session.commit()
    other_headers = bearer_headers(other_session["session_token"])
    other_headers["X-Workspace"] = other_workspace.slug

    for path in (
        f"/api/v1/artifacts/{artifact.id}",
        f"/api/v1/artifacts/{artifact.id}/versions/{version_id}/content",
        f"/api/v1/artifacts/{artifact.id}/versions/{version_id}/view-url",
    ):
        response = await db_async_client.get(path, headers=other_headers)
        assert response.status_code == 404


async def test_html_serving_headers_are_exact_and_cookie_free(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    local_storage_settings: None,
) -> None:
    _headers, artifact, version_id, session_token = await _seed(db_session)
    capability = create_artifact_view_url(artifact=artifact, version_id=version_id)
    db_async_client.cookies.set("session", session_token)
    response = await db_async_client.get(_relative_url(capability.url))
    db_async_client.cookies.delete("session")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert response.headers["content-security-policy"] == build_html_csp(
        connect_src="'none'",
        frame_ancestors=artifact_frame_ancestors(),
    )
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"
    assert "x-frame-options" not in response.headers
    assert "set-cookie" not in response.headers


async def test_signed_serving_fails_closed_for_all_invalid_targets(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    local_storage_settings: None,
) -> None:
    _headers, artifact, version_id, _token = await _seed(db_session)
    capability = create_artifact_view_url(artifact=artifact, version_id=version_id)
    relative = _relative_url(capability.url)
    tampered = relative[:-1] + ("0" if relative[-1] != "0" else "1")
    assert (await db_async_client.get(tampered)).status_code == 404

    unknown_version = uuid4()
    unknown_capability = create_artifact_view_url(
        artifact=artifact,
        version_id=unknown_version,
    )
    assert (await db_async_client.get(_relative_url(unknown_capability.url))).status_code == 404

    unknown_artifact = Artifact(id=uuid4())
    unknown_artifact_capability = create_artifact_view_url(
        artifact=unknown_artifact,
        version_id=uuid4(),
    )
    unknown_response = await db_async_client.get(_relative_url(unknown_artifact_capability.url))
    assert unknown_response.status_code == 404
    assert unknown_response.headers["content-type"].startswith("application/problem+json")

    _other_headers, _other_artifact, other_version_id, _other_token = await _seed(db_session)
    cross_chain_capability = create_artifact_view_url(
        artifact=artifact,
        version_id=other_version_id,
    )
    cross_chain = await db_async_client.get(_relative_url(cross_chain_capability.url))
    assert cross_chain.status_code == 404
    assert cross_chain.headers["content-type"].startswith("application/problem+json")

    artifact.deleted = True
    await db_session.commit()
    deleted = await db_async_client.get(relative)
    assert deleted.status_code == 404
    assert deleted.headers["content-type"].startswith("application/problem+json")


async def test_signed_serving_hides_storage_disappearance(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    local_storage_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _headers, artifact, version_id, _token = await _seed(db_session)
    capability = create_artifact_view_url(artifact=artifact, version_id=version_id)
    provider = get_storage_provider()

    async def missing_after_stat(_ref):
        raise StorageNotFoundError(
            "Storage object not found",
            provider_key=provider.provider_key,
            operation="get_object",
            bucket="private",
            object_key="internal/object/key",
        )

    monkeypatch.setattr(provider, "get_object", missing_after_stat)
    response = await db_async_client.get(_relative_url(capability.url))

    assert response.status_code == 404
    assert response.json() == {
        "type": "https://httpstatuses.com/404",
        "title": "Resource Not Found",
        "status": 404,
        "detail": "Artifact not found",
    }


async def test_expired_serving_capability_returns_uniform_not_found(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    local_storage_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _headers, artifact, version_id, _token = await _seed(db_session)
    monkeypatch.setattr(settings, "ARTIFACT_VIEW_URL_TTL_SECONDS", -1)
    capability = create_artifact_view_url(artifact=artifact, version_id=version_id)

    response = await db_async_client.get(_relative_url(capability.url))

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_plain_artifact_is_sandboxed_and_downloadable(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    local_storage_settings: None,
) -> None:
    _headers, artifact, version_id, _token = await _seed(
        db_session,
        artifact_type="markdown",
        content="# Report",
    )
    capability = create_artifact_view_url(artifact=artifact, version_id=version_id)
    response = await db_async_client.get(_relative_url(capability.url) + "&download=1")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.headers["content-security-policy"] == build_plain_csp(
        frame_ancestors=artifact_frame_ancestors()
    )
    assert response.headers["content-disposition"].startswith("attachment;")
