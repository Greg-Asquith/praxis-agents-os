"""HTTP-boundary tests for knowledge-base read routes."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
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
        source_updated_at=datetime.now(UTC),
    )
    hidden = build_kb_document(
        workspace=workspace,
        created_by_user_id=other_user.id,
        is_private=True,
    )
    db_session.add_all([visible, hidden])
    await db_session.commit()

    response = await db_async_client.get(
        f"/api/v1/kb/documents/{visible.id}",
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["content_md"] == visible.content_md

    hidden_response = await db_async_client.get(
        f"/api/v1/kb/documents/{hidden.id}",
        headers=headers,
    )
    assert hidden_response.status_code == 404
    assert hidden_response.headers["content-type"].startswith("application/problem+json")
