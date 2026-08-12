# apps/api/tests/routes/artifacts/test_artifact_routes.py

"""Artifact management and anonymous serving route tests."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from httpx2 import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.auth.sessions import session_manager
from core.database import set_session_tenant_context
from core.rate_limiting import rate_limiter
from core.settings import settings
from models.artifacts import Artifact, ArtifactRevision, ArtifactShare
from models.audit_event import AuditEvent
from models.rate_limiting import RateLimitAttempt
from models.workspace import Workspace, WorkspaceRole
from services.artifacts import create_artifact, create_artifact_view_url, update_artifact
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
from utils.security import hash_token

pytestmark = pytest.mark.asyncio


@pytest.fixture
def local_storage_settings(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "APP_BASE_URL", "http://testserver")
    monkeypatch.setattr(settings, "ARTIFACT_SHARING_ENABLED", True)
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
    role: WorkspaceRole = WorkspaceRole.MEMBER,
) -> tuple[dict[str, str], Artifact, UUID, str]:
    user = build_user(email=f"artifact-route-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"artifact-route-{uuid4().hex[:8]}")
    membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=user.id,
        role=role,
    )
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


async def test_artifact_list_supports_search_sorting_and_pagination(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    local_storage_settings: None,
) -> None:
    headers, report, version_id, _token = await _seed(db_session)
    workspace = await db_session.get(Workspace, report.workspace_id)
    initial_revision = await db_session.get(ArtifactRevision, version_id)
    assert workspace is not None
    assert initial_revision is not None
    assert initial_revision.created_by_user_id is not None

    alpha, _alpha_revision = await create_artifact(
        db_session,
        workspace=workspace,
        title="Alpha plan",
        artifact_type="markdown",
        content="# Alpha",
        actor_user_id=initial_revision.created_by_user_id,
    )
    zulu, _zulu_revision = await create_artifact(
        db_session,
        workspace=workspace,
        title="Zulu summary",
        artifact_type="markdown",
        content="# Zulu",
        actor_user_id=initial_revision.created_by_user_id,
    )
    await update_artifact(
        db_session,
        workspace=workspace,
        artifact_id=zulu.id,
        content="# Zulu revised",
        actor_user_id=initial_revision.created_by_user_id,
    )
    await db_session.commit()

    searched = await db_async_client.get(
        "/api/v1/artifacts/",
        headers=headers,
        params={"search": "alpha"},
    )
    assert searched.status_code == 200
    assert searched.json()["total"] == 1
    assert [item["id"] for item in searched.json()["items"]] == [str(alpha.id)]

    searched_by_type = await db_async_client.get(
        "/api/v1/artifacts/",
        headers=headers,
        params={"search": "markdown"},
    )
    assert searched_by_type.status_code == 200
    assert searched_by_type.json()["total"] == 2

    escaped_wildcard = await db_async_client.get(
        "/api/v1/artifacts/",
        headers=headers,
        params={"search": "%"},
    )
    assert escaped_wildcard.status_code == 200
    assert escaped_wildcard.json()["total"] == 0

    paged = await db_async_client.get(
        "/api/v1/artifacts/",
        headers=headers,
        params={
            "limit": 2,
            "offset": 1,
            "sort_by": "title",
            "sort_direction": "asc",
        },
    )
    assert paged.status_code == 200
    assert paged.json()["total"] == 3
    assert [item["title"] for item in paged.json()["items"]] == [
        "Report",
        "Zulu summary",
    ]

    by_versions = await db_async_client.get(
        "/api/v1/artifacts/",
        headers=headers,
        params={"sort_by": "version_count", "sort_direction": "desc"},
    )
    assert by_versions.status_code == 200
    assert by_versions.json()["items"][0]["id"] == str(zulu.id)
    assert by_versions.json()["items"][0]["version_count"] == 2


@pytest.mark.parametrize(
    ("query", "field"),
    [
        ({"sort_by": "created_at"}, "sort_by"),
        ({"sort_direction": "down"}, "sort_direction"),
    ],
)
async def test_artifact_list_rejects_unknown_sort_options(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    query: dict[str, str],
    field: str,
) -> None:
    headers, _artifact, _version_id, _token = await _seed(db_session)

    response = await db_async_client.get("/api/v1/artifacts/", headers=headers, params=query)

    assert response.status_code == 400
    assert response.json()["field"] == field


async def test_share_is_hashed_pinned_cookie_free_and_revocable(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    local_storage_settings: None,
) -> None:
    headers, artifact, version_id, session_token = await _seed(
        db_session,
        role=WorkspaceRole.ADMIN,
    )
    created = await db_async_client.post(
        f"/api/v1/artifacts/{artifact.id}/shares",
        headers=headers,
        json={"expires_in_days": 7},
    )
    assert created.status_code == 201
    body = created.json()
    token = body["share_url"].rsplit("/", 1)[-1]
    share = await db_session.scalar(select(ArtifactShare).where(ArtifactShare.id == body["id"]))
    assert share is not None
    assert share.token_hash == hash_token(token)
    assert token not in str(share.__dict__)
    assert share.version_id == version_id
    share_id = share.id
    audits = (
        await db_session.scalars(select(AuditEvent).where(AuditEvent.resource_id == str(share_id)))
    ).all()
    assert [audit.action for audit in audits] == ["create"]
    assert all(token not in str(audit.details) for audit in audits)

    updated = await db_async_client.patch(
        f"/api/v1/artifacts/{artifact.id}",
        headers=headers,
        json={"content": "<h1>Changed</h1>"},
    )
    assert updated.status_code == 200
    assert updated.json()["current_version_id"] != str(version_id)

    await set_session_tenant_context(db_session, workspace_id=uuid4())
    db_async_client.cookies.set("session", session_token)
    served = await db_async_client.get(urlsplit(body["share_url"]).path)
    db_async_client.cookies.delete("session")
    assert served.status_code == 200
    assert served.text == "<h1>Report</h1>"
    assert served.headers["content-security-policy"] == build_html_csp(
        connect_src="'none'",
        frame_ancestors=artifact_frame_ancestors(),
    )
    assert served.headers["x-content-type-options"] == "nosniff"
    assert served.headers["referrer-policy"] == "no-referrer"
    assert served.headers["cache-control"] == "no-store"
    assert "set-cookie" not in served.headers

    revoked = await db_async_client.delete(
        f"/api/v1/artifacts/{artifact.id}/shares/{share_id}",
        headers=headers,
    )
    assert revoked.status_code == 204
    listed = await db_async_client.get(
        f"/api/v1/artifacts/{artifact.id}/shares",
        headers=headers,
    )
    assert listed.status_code == 200
    assert listed.json()["items"][0]["revoked_at"] is not None
    audits = (
        await db_session.scalars(select(AuditEvent).where(AuditEvent.resource_id == str(share_id)))
    ).all()
    assert {audit.action for audit in audits} >= {"create", "read", "delete"}
    assert all(token not in str(audit.details) for audit in audits)
    revoked_again = await db_async_client.delete(
        f"/api/v1/artifacts/{artifact.id}/shares/{share_id}",
        headers=headers,
    )
    assert revoked_again.status_code == 204
    assert (await db_async_client.get(urlsplit(body["share_url"]).path)).status_code == 404


async def test_share_rejections_are_uniform_and_access_audit_is_throttled(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    local_storage_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rate_limiter, "enabled", True)
    headers, artifact, _version_id, _session_token = await _seed(
        db_session,
        role=WorkspaceRole.ADMIN,
    )
    created = await db_async_client.post(
        f"/api/v1/artifacts/{artifact.id}/shares",
        headers=headers,
        json={"expires_in_days": 7},
    )
    share_path = urlsplit(created.json()["share_url"]).path
    assert (await db_async_client.get(share_path)).status_code == 200
    assert (await db_async_client.get(share_path)).status_code == 200
    share = await db_session.get(ArtifactShare, UUID(created.json()["id"]))
    assert share is not None
    await db_session.refresh(share)
    assert share.access_count == 2
    read_audits = (
        await db_session.scalars(
            select(AuditEvent).where(
                AuditEvent.resource_id == str(share.id),
                AuditEvent.action == "read",
            )
        )
    ).all()
    assert len(read_audits) == 1
    share.last_accessed_at = datetime.now(UTC) - timedelta(hours=2)
    await db_session.commit()
    assert (await db_async_client.get(share_path)).status_code == 200
    await db_session.refresh(share)
    assert share.access_count == 3
    read_audits = (
        await db_session.scalars(
            select(AuditEvent).where(
                AuditEvent.resource_id == str(share.id),
                AuditEvent.action == "read",
            )
        )
    ).all()
    assert len(read_audits) == 2

    unknown_token = "x" * 43
    unknown = await db_async_client.get("/artifacts/shared/" + unknown_token)
    malformed_short = await db_async_client.get("/artifacts/shared/short")
    malformed_long = await db_async_client.get("/artifacts/shared/" + "z" * 65)
    share.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    expired = await db_async_client.get(share_path)
    share.expires_at = datetime.now(UTC) + timedelta(days=1)
    artifact.deleted = True
    artifact.deleted_at = datetime.now(UTC)
    await db_session.commit()
    deleted = await db_async_client.get(share_path)
    artifact.deleted = False
    artifact.deleted_at = None
    share.revoked_at = datetime.now(UTC)
    await db_session.commit()
    revoked = await db_async_client.get(share_path)
    rejected = {
        "unknown": unknown,
        "malformed_short": malformed_short,
        "malformed_long": malformed_long,
        "expired": expired,
        "deleted": deleted,
        "revoked": revoked,
    }
    assert {name: response.status_code for name, response in rejected.items()} == dict.fromkeys(
        rejected, 404
    )
    assert {str(response.json()) for response in rejected.values()} == {str(unknown.json())}

    limiter_rows = (
        await db_session.scalars(
            select(RateLimitAttempt).where(RateLimitAttempt.endpoint == "/artifacts/shared/{token}")
        )
    ).all()
    assert limiter_rows
    assert all(unknown_token not in row.endpoint for row in limiter_rows)


async def test_share_management_requires_admin_but_member_can_edit_and_restore(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    local_storage_settings: None,
) -> None:
    headers, artifact, first_version_id, _session_token = await _seed(db_session)
    denied = await db_async_client.post(
        f"/api/v1/artifacts/{artifact.id}/shares",
        headers=headers,
        json={"expires_in_days": 7},
    )
    assert denied.status_code == 403

    edited = await db_async_client.patch(
        f"/api/v1/artifacts/{artifact.id}",
        headers=headers,
        json={"content": "<h1>Second</h1>", "title": "Updated report"},
    )
    assert edited.status_code == 200
    original_content = await db_async_client.get(
        f"/api/v1/artifacts/{artifact.id}/versions/{first_version_id}/content",
        headers=headers,
    )
    assert original_content.status_code == 200
    restored = await db_async_client.post(
        f"/api/v1/artifacts/{artifact.id}/versions/{first_version_id}/restore",
        headers=headers,
    )
    assert restored.status_code == 200
    restored_version = await db_session.get(
        ArtifactRevision,
        UUID(restored.json()["current_version_id"]),
    )
    assert restored_version is not None
    assert restored_version.revision_kind == "restore"
    assert restored_version.restored_from_revision_id == first_version_id
    restored_content = await db_async_client.get(
        f"/api/v1/artifacts/{artifact.id}/versions/{restored_version.id}/content",
        headers=headers,
    )
    assert restored_content.status_code == 200
    assert restored_content.json()["content"] == original_content.json()["content"]


async def test_share_defaults_limits_listing_and_disabled_gate(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    local_storage_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, artifact, version_id, _session_token = await _seed(
        db_session,
        role=WorkspaceRole.OWNER,
    )
    before = datetime.now(UTC)
    created_default = await db_async_client.post(
        f"/api/v1/artifacts/{artifact.id}/shares",
        headers=headers,
        json={},
    )
    assert created_default.status_code == 201
    default_expiry = datetime.fromisoformat(created_default.json()["expires_at"])
    assert timedelta(days=6, hours=23) < default_expiry - before < timedelta(days=7, minutes=1)

    created_clamped = await db_async_client.post(
        f"/api/v1/artifacts/{artifact.id}/shares",
        headers=headers,
        json={"expires_in_days": 90},
    )
    assert created_clamped.status_code == 201
    clamped_expiry = datetime.fromisoformat(created_clamped.json()["expires_at"])
    assert timedelta(days=29, hours=23) < clamped_expiry - before < timedelta(days=30, minutes=1)
    assert created_clamped.json()["version_id"] == str(version_id)

    listed = await db_async_client.get(
        f"/api/v1/artifacts/{artifact.id}/shares",
        headers=headers,
    )
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 2
    assert all(
        "token_hash" not in item and "share_url" not in item for item in listed.json()["items"]
    )

    monkeypatch.setattr(settings, "ARTIFACT_SHARING_ENABLED", False)
    disabled = await db_async_client.post(
        f"/api/v1/artifacts/{artifact.id}/shares",
        headers=headers,
        json={},
    )
    assert disabled.status_code == 400
    assert disabled.json()["detail"] == "Artifact sharing is not enabled"


async def test_read_only_members_cannot_edit_or_restore(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    local_storage_settings: None,
) -> None:
    headers, artifact, version_id, _session_token = await _seed(
        db_session,
        role=WorkspaceRole.READ_ONLY,
    )
    edited = await db_async_client.patch(
        f"/api/v1/artifacts/{artifact.id}",
        headers=headers,
        json={"content": "<h1>Denied</h1>"},
    )
    restored = await db_async_client.post(
        f"/api/v1/artifacts/{artifact.id}/versions/{version_id}/restore",
        headers=headers,
    )
    assert edited.status_code == 403
    assert restored.status_code == 403


async def test_share_access_limit_is_shared_across_token_guesses(
    async_client: AsyncClient,
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rate_limiter, "enabled", True)
    monkeypatch.setitem(
        rate_limiter.default_limits,
        "requests_per_minute",
        (1000, 60),
    )
    endpoint = "/artifacts/shared/{token}"
    async with committed_db_session_factory() as db:
        await db.execute(delete(RateLimitAttempt).where(RateLimitAttempt.endpoint == endpoint))
        await db.commit()
    try:
        for attempt in range(120):
            token = f"{attempt:043d}"
            response = await async_client.get(f"/artifacts/shared/{token}")
            assert response.status_code == 404

        async with committed_db_session_factory() as db:
            attempts = await db.scalar(
                select(RateLimitAttempt.attempts).where(
                    RateLimitAttempt.endpoint == endpoint,
                    RateLimitAttempt.window_seconds == 3600,
                )
            )
        assert attempts == 120
        blocked_token = "x" * 43
        blocked = await async_client.get(f"/artifacts/shared/{blocked_token}")
        assert blocked.status_code == 429
        assert blocked.headers["x-ratelimit-limit"] == "120"
        assert blocked.headers["retry-after"]
    finally:
        async with committed_db_session_factory() as db:
            await db.execute(delete(RateLimitAttempt).where(RateLimitAttempt.endpoint == endpoint))
            await db.commit()


async def test_share_creation_rate_limit_is_workspace_scoped(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    local_storage_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rate_limiter, "enabled", True)
    headers, artifact, _version_id, _session_token = await _seed(
        db_session,
        role=WorkspaceRole.ADMIN,
    )
    for _attempt in range(10):
        response = await db_async_client.post(
            f"/api/v1/artifacts/{artifact.id}/shares",
            headers=headers,
            json={"expires_in_days": 7},
        )
        assert response.status_code == 201
    blocked = await db_async_client.post(
        f"/api/v1/artifacts/{artifact.id}/shares",
        headers=headers,
        json={"expires_in_days": 7},
    )
    assert blocked.status_code == 429
    assert blocked.headers["retry-after"]
    assert blocked.headers["x-ratelimit-limit"] == "10"

    other_headers, other_artifact, _version_id, _session_token = await _seed(
        db_session,
        role=WorkspaceRole.ADMIN,
    )
    other = await db_async_client.post(
        f"/api/v1/artifacts/{other_artifact.id}/shares",
        headers=other_headers,
        json={"expires_in_days": 7},
    )
    assert other.status_code == 201


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
    await set_session_tenant_context(db_session, workspace_id=uuid4())
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
    tampered_workspace = relative.replace(
        f"workspace_id={artifact.workspace_id}",
        f"workspace_id={uuid4()}",
    )
    assert (await db_async_client.get(tampered_workspace)).status_code == 404

    unknown_version = uuid4()
    unknown_capability = create_artifact_view_url(
        artifact=artifact,
        version_id=unknown_version,
    )
    assert (await db_async_client.get(_relative_url(unknown_capability.url))).status_code == 404

    unknown_artifact = Artifact(id=uuid4(), workspace_id=artifact.workspace_id)
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

    await set_session_tenant_context(db_session, workspace_id=artifact.workspace_id)
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
