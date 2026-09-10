# apps/api/tests/routes/kb/test_kb_routes.py

"""HTTP-boundary tests for knowledge-base read routes."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from core.database import maintenance_async_db_session
from models.kb import KBDocument
from models.workspace import WorkspaceRole
from services.kb.schemas import KBSearchHit, KBSearchResult
from tests.factories import (
    build_kb_document,
    build_user,
    build_workspace,
    build_workspace_membership,
)
from tests.support.auth import bearer_headers


async def _authenticated_workspace(
    db: AsyncSession,
    *,
    role: WorkspaceRole = WorkspaceRole.READ_ONLY,
):
    suffix = uuid4().hex
    user = build_user(email=f"kb-route-{suffix}@example.com")
    workspace = build_workspace(slug=f"kb-route-{suffix[:12]}")
    membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=user.id,
        role=role,
    )
    db.add_all([user, workspace, membership])
    await db.flush()
    user.default_workspace_id = workspace.id
    session = await session_manager.create_session(db, str(user.id))
    await db.commit()
    headers = {
        **bearer_headers(session["session_token"]),
        "X-Workspace": workspace.slug,
    }
    return user, workspace, headers


async def test_search_requires_authentication_and_explicit_workspace(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    unauthenticated = await db_async_client.post(
        "/api/v1/kb/search",
        headers={"X-Workspace": "missing"},
        json={"query": "vpn"},
    )
    assert unauthenticated.status_code == 401

    _user, _workspace, headers = await _authenticated_workspace(db_session)
    headers.pop("X-Workspace")
    missing_workspace = await db_async_client.post(
        "/api/v1/kb/search",
        headers=headers,
        json={"query": "vpn"},
    )
    assert missing_workspace.status_code == 422


async def test_url_create_and_reprocess_return_pending_sync_state(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    _user, _workspace, headers = await _authenticated_workspace(
        db_session,
        role=WorkspaceRole.MEMBER,
    )
    created = await db_async_client.post(
        "/api/v1/kb/documents/from-url",
        headers=headers,
        json={
            "title": "Refreshable guide",
            "url": "https://example.com/guide",
        },
    )

    assert created.status_code == 202, created.text
    assert created.json()["source_sync_status"] == "pending"
    document = await db_session.get(KBDocument, UUID(created.json()["id"]))
    assert document is not None
    document.status = "error"
    document.source_sync_status = "error"
    await db_session.commit()

    refreshed = await db_async_client.post(
        f"/api/v1/kb/documents/{document.id}/reprocess",
        headers=headers,
    )

    assert refreshed.status_code == 202, refreshed.text
    assert refreshed.json()["source_sync_status"] == "pending"


async def test_search_allows_read_only_and_returns_service_contract(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, workspace, headers = await _authenticated_workspace(db_session)
    document_id = uuid4()
    chunk_id = uuid4()
    captured: dict[str, object] = {}

    async def fake_search(db, **kwargs):
        captured.update(kwargs)
        return KBSearchResult(
            query=kwargs["query"],
            mode="hybrid",
            results=[
                KBSearchHit(
                    id=chunk_id,
                    scope="workspace",
                    document_id=document_id,
                    chunk_index=0,
                    content="Install WireGuard.",
                    context_line=None,
                    char_start=0,
                    char_end=18,
                    meta={"headings": ["VPN"]},
                    pending_embedding=False,
                    title="VPN guide",
                    source_type="manual",
                    external_url=None,
                    is_private=False,
                    score=0.03,
                    sources=["lexical", "semantic"],
                )
            ],
        )

    monkeypatch.setattr("routes.kb.search.search_chunks_service", fake_search)

    response = await db_async_client.post(
        "/api/v1/kb/search",
        headers=headers,
        json={
            "query": "vpn",
            "top_k": 5,
            "source_types": ["manual"],
            "document_ids": [str(document_id)],
            "private_only": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["results"][0]["id"] == str(chunk_id)
    assert response.json()["mode"] == "hybrid"
    assert captured["workspace_id"] == workspace.id
    assert captured["user_id"] == user.id
    assert captured["document_ids"] == [document_id]


async def test_get_document_allows_read_only_and_maps_hidden_to_404(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace, headers = await _authenticated_workspace(db_session)
    other_user = build_user(email=f"kb-route-hidden-{uuid4().hex}@example.com")
    db_session.add(other_user)
    await db_session.flush()
    visible = build_kb_document(
        workspace=workspace,
        created_by_user_id=user.id,
        status="ready",
        processing_attempts=2,
        source_updated_at=datetime.now(UTC),
    )
    external = build_kb_document(
        workspace=workspace,
        created_by_user_id=user.id,
        source_type="url",
        status="ready",
        source_sync_status="ready",
    )
    hidden = build_kb_document(
        workspace=workspace,
        created_by_user_id=other_user.id,
        is_private=True,
    )
    db_session.add_all([visible, external, hidden])
    await db_session.commit()

    response = await db_async_client.get(
        f"/api/v1/kb/documents/{visible.id}",
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["content_md"] == visible.content_md
    assert response.json()["created_by_user_id"] == str(user.id)
    assert response.json()["processing_attempts"] == 2
    assert response.json()["source_sync_status"] is None
    assert response.json()["source_synced_at"] is None

    external_response = await db_async_client.get(
        f"/api/v1/kb/documents/{external.id}",
        headers=headers,
    )
    assert external_response.status_code == 200
    assert external_response.json()["content_md"] == {
        "node": "praxis_untrusted",
        "source_kind": "kb",
        "source_ref": f"document:{external.id}",
        "content": external.content_md,
    }

    hidden_response = await db_async_client.get(
        f"/api/v1/kb/documents/{hidden.id}",
        headers=headers,
    )
    assert hidden_response.status_code == 404
    assert hidden_response.headers["content-type"].startswith("application/problem+json")


async def test_platform_knowledge_read_routes_filter_scope_and_hide_drafts(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    actor, workspace, headers = await _authenticated_workspace(db_session)
    local = build_kb_document(workspace=workspace, created_by_user_id=actor.id)
    published = build_kb_document(
        workspace=workspace,
        scope="platform",
        workspace_id=None,
        is_published=True,
        status="ready",
    )
    draft = build_kb_document(workspace=workspace, scope="platform", workspace_id=None)
    async with maintenance_async_db_session() as db:
        db.add_all([local, published, draft])

    response = await db_async_client.get(
        "/api/v1/kb/documents",
        headers=headers,
        params={"scope": "platform", "limit": 1},
    )
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert response.json()["documents"][0]["id"] == str(published.id)
    assert response.json()["documents"][0]["scope"] == "platform"
    visible = await db_async_client.get(
        f"/api/v1/kb/documents/{published.id}",
        headers=headers,
    )
    assert visible.status_code == 200, visible.text
    assert visible.json()["scope"] == "platform"
    assert visible.json()["workspace_id"] is None
    assert visible.json()["content_md"] == {
        "node": "praxis_untrusted",
        "source_kind": "kb",
        "source_ref": f"document:{published.id}",
        "content": published.content_md,
    }
    hidden = await db_async_client.get(
        f"/api/v1/kb/documents/{draft.id}",
        headers=headers,
    )
    assert hidden.status_code == 404
