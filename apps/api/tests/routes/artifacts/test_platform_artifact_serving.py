# apps/api/tests/routes/artifacts/test_platform_artifact_serving.py

"""Checks scoped view capabilities against publication and rendering boundaries."""

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

import pytest

from core.auth.sessions import session_manager
from core.database import maintenance_async_db_session
from core.settings import settings
from models.artifacts import Artifact
from services.artifacts.create_view_url import create_artifact_view_url
from services.artifacts.domain import artifact_frame_ancestors, build_html_csp, build_plain_csp
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.factory import get_storage_provider
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.factories.artifacts import build_artifact, build_artifact_revision
from tests.support.auth import bearer_headers
from tests.support.storage import reset_storage_provider_cache


@pytest.fixture
async def platform_views(db_session_factory, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "APP_BASE_URL", "http://testserver")
    reset_storage_provider_cache()
    contexts = []
    async with maintenance_async_db_session() as db:
        for _ in range(2):
            actor = build_user(email=f"platform-view-{uuid4().hex}@example.com")
            workspace = build_workspace(slug=f"platform-view-{uuid4().hex}")
            actor.default_workspace_id = workspace.id
            db.add_all(
                [
                    actor,
                    workspace,
                    build_workspace_membership(workspace_id=workspace.id, user_id=actor.id),
                ]
            )
            await db.flush()
            session = await session_manager.create_session(db, str(actor.id))
            contexts.append(
                (
                    workspace.id,
                    {**bearer_headers(session["session_token"]), "X-Workspace": workspace.slug},
                )
            )
        artifact = build_artifact(workspace=workspace, workspace_id=None, scope="platform")
        db.add(artifact)
        await db.flush()
        revisions = []
        for number in range(1, 4):
            revision = build_artifact_revision(
                artifact=artifact,
                scope="platform",
                revision_number=number,
                is_published=number < 3,
                object_key=f"platform/artifacts/{artifact.id}/{uuid4()}.html",
            )
            db.add(revision)
            revisions.append(revision)
        await db.flush()
        artifact.current_version_id = revisions[2].id
        artifact.published_version_id = revisions[1].id
        artifact.is_published = True
    try:
        for number, revision in enumerate(revisions, 1):
            await get_storage_provider().put_object(
                make_storage_object_ref(StorageBucket.PLATFORM_PRIVATE, revision.object_key),
                f"<p>Version {number}</p>".encode(),
                content_type="text/html",
            )
        yield artifact, revisions, contexts
    finally:
        reset_storage_provider_cache()


def _relative(url):
    parsed = urlsplit(url)
    return f"{parsed.path}?{parsed.query}"


async def test_platform_views_pin_published_versions_for_both_workspaces(
    db_async_client, platform_views
):
    artifact, revisions, contexts = platform_views
    for workspace_id, headers in contexts:
        for number, revision in enumerate(revisions[:2], 1):
            minted = await db_async_client.get(
                f"/api/v1/artifacts/{artifact.id}/versions/{revision.id}/view-url", headers=headers
            )
            assert minted.status_code == 200
            query = parse_qs(urlsplit(minted.json()["url"]).query)
            assert query["workspace_id"] == [str(workspace_id)]
            assert query["scope"] == ["platform"]
            assert query["sig"][0].startswith("v2.")
            viewed = await db_async_client.get(_relative(minted.json()["url"]))
            assert viewed.status_code == 200
            assert viewed.text == f"<p>Version {number}</p>"
            assert viewed.headers["content-security-policy"] == build_html_csp(
                connect_src="'none'", frame_ancestors=artifact_frame_ancestors()
            )
            assert viewed.headers["content-type"] == "text/html; charset=utf-8"
            assert viewed.headers["cache-control"] == "no-store"
            assert viewed.headers["x-content-type-options"] == "nosniff"
            assert viewed.headers["referrer-policy"] == "no-referrer"
            assert "set-cookie" not in viewed.headers
        draft = await db_async_client.get(
            f"/api/v1/artifacts/{artifact.id}/versions/{revisions[2].id}/view-url", headers=headers
        )
        assert draft.status_code == 404


@pytest.mark.parametrize(
    "tamper", ["scope", "workspace", "artifact", "version", "expiry", "digest", "v1"]
)
async def test_platform_view_signature_rejects_tampering(db_async_client, platform_views, tamper):
    artifact, revisions, contexts = platform_views
    url = create_artifact_view_url(
        workspace_id=contexts[0][0], artifact=artifact, version_id=revisions[0].id
    ).url
    parsed = urlsplit(url)
    query = {key: values[0] for key, values in parse_qs(parsed.query).items()}
    path = parsed.path
    if tamper == "scope":
        query["scope"] = "workspace"
    elif tamper == "workspace":
        query["workspace_id"] = str(contexts[1][0])
    elif tamper == "artifact":
        path = path.replace(str(artifact.id), str(uuid4()))
    elif tamper == "version":
        path = path.replace(str(revisions[0].id), str(revisions[1].id))
    elif tamper == "expiry":
        query["expires"] = str(int(query["expires"]) + 60)
    elif tamper == "digest":
        query["sig"] = "v2." + "0" * 64
    else:
        query["sig"] = query["sig"].replace("v2.", "v1.", 1)
    assert (await db_async_client.get(f"{path}?{urlencode(query)}")).status_code == 404


@pytest.mark.parametrize("state", ["withdrawn", "deleted"])
async def test_platform_view_rechecks_parent_after_minting(db_async_client, platform_views, state):
    artifact, revisions, contexts = platform_views
    url = create_artifact_view_url(
        workspace_id=contexts[0][0], artifact=artifact, version_id=revisions[0].id
    ).url
    async with maintenance_async_db_session() as db:
        parent = await db.get(Artifact, artifact.id)
        if state == "withdrawn":
            parent.is_published = False
        else:
            parent.deleted = True
            parent.deleted_at = datetime.now(UTC)
    assert (await db_async_client.get(_relative(url))).status_code == 404


async def test_platform_view_checks_exact_scope_and_revision_even_with_valid_signature(
    db_async_client, platform_views
):
    artifact, revisions, contexts = platform_views
    for version_id in (revisions[2].id, uuid4()):
        url = create_artifact_view_url(
            workspace_id=contexts[0][0], artifact=artifact, version_id=version_id
        ).url
        assert (await db_async_client.get(_relative(url))).status_code == 404
    wrong_scope = Artifact(id=artifact.id, scope="workspace", workspace_id=contexts[0][0])
    url = create_artifact_view_url(
        workspace_id=contexts[0][0], artifact=wrong_scope, version_id=revisions[0].id
    ).url
    assert (await db_async_client.get(_relative(url))).status_code == 404


@pytest.mark.parametrize("artifact_type", ["markdown", "mermaid", "csv", "image-ref"])
async def test_platform_serving_preserves_plain_sandbox_and_image_mime_checks(
    db_async_client, platform_views, artifact_type
):
    artifact, revisions, contexts = platform_views
    async with maintenance_async_db_session() as db:
        parent = await db.get(Artifact, artifact.id)
        parent.artifact_type = artifact_type
    url = create_artifact_view_url(
        workspace_id=contexts[0][0], artifact=artifact, version_id=revisions[0].id
    ).url
    response = await db_async_client.get(_relative(url) + "&download=1")
    if artifact_type == "image-ref":
        assert response.status_code == 404
    else:
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/plain; charset=utf-8"
        assert response.headers["content-security-policy"] == build_plain_csp(
            frame_ancestors=artifact_frame_ancestors()
        )
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["content-disposition"].startswith("attachment;")
