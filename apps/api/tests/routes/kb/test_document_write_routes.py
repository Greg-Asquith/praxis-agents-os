# apps/api/tests/routes/kb/test_document_write_routes.py

"""HTTP-boundary tests for knowledge-document management."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx2
import pytest
from httpx2 import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from core.exceptions.integration import IntegrationAuthError
from integrations.notion import knowledge_source as notion_source_module
from integrations.notion.client import NotionClient
from integrations.notion.knowledge_source import KNOWLEDGE_SOURCE
from models.audit_event import AuditEvent
from models.workspace import WorkspaceRole
from services.integrations.plugin import KnowledgeSourcePreview, KnowledgeSourceSearchResult
from services.kb.schemas import KBDocumentRead
from tests.factories import (
    build_kb_document,
    build_user,
    build_workspace,
    build_workspace_membership,
)
from tests.support.auth import bearer_headers


async def _workspace_session(
    db: AsyncSession,
    *,
    role: WorkspaceRole,
):
    suffix = uuid4().hex
    user = build_user(email=f"kb-write-{suffix}@example.com")
    workspace = build_workspace(slug=f"kb-write-{suffix[:12]}")
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


async def test_member_can_manage_documents_and_mutations_are_audited(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    _user, workspace, headers = await _workspace_session(
        db_session,
        role=WorkspaceRole.MEMBER,
    )
    created = await db_async_client.post(
        "/api/v1/kb/documents",
        headers=headers,
        json={
            "title": "Operator handbook",
            "content_md": "Workspace operations knowledge.",
            "is_private": False,
        },
    )
    assert created.status_code == 201
    document_id = created.json()["id"]
    assert created.json()["processing_attempts"] == 0

    listed = await db_async_client.get("/api/v1/kb/documents", headers=headers)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["documents"]] == [document_id]
    assert listed.json()["documents"][0]["processing_attempts"] == 0

    updated = await db_async_client.patch(
        f"/api/v1/kb/documents/{document_id}",
        headers=headers,
        json={"title": "Updated handbook", "is_private": True},
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Updated handbook"
    assert updated.json()["is_private"] is True

    deleted = await db_async_client.delete(
        f"/api/v1/kb/documents/{document_id}",
        headers=headers,
    )
    assert deleted.status_code == 204
    audits = (
        await db_session.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.workspace_id == workspace.id,
                AuditEvent.resource_type == "kb_document",
                AuditEvent.resource_id == document_id,
            )
            .order_by(AuditEvent.occurred_at)
        )
    ).all()
    assert [event.action for event in audits] == ["create", "update", "delete"]


async def test_read_only_cannot_create_documents(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    _user, _workspace, headers = await _workspace_session(
        db_session,
        role=WorkspaceRole.READ_ONLY,
    )
    response = await db_async_client.post(
        "/api/v1/kb/documents",
        headers=headers,
        json={"title": "Denied", "content_md": "No write access."},
    )
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_member_can_search_preview_and_import_an_integration_source(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, workspace, headers = await _workspace_session(
        db_session,
        role=WorkspaceRole.MEMBER,
    )
    resource_id = uuid4()
    document_id = uuid4()
    page_id = str(uuid4())
    now = datetime.now(UTC)
    captured: dict[str, dict[str, object]] = {}

    async def fake_search(db, **kwargs):
        captured["search"] = kwargs
        return (
            KnowledgeSourceSearchResult(
                reference={"page_id": page_id},
                title="Team handbook",
                url=f"https://www.notion.so/{page_id.replace('-', '')}",
                source_updated_at=now,
            ),
        )

    async def fake_preview(db, **kwargs):
        captured["preview"] = kwargs
        return KnowledgeSourcePreview(
            reference={"page_id": page_id},
            external_id=page_id,
            title="Team handbook",
            url=f"https://www.notion.so/{page_id.replace('-', '')}",
            source_updated_at=now,
            markdown_excerpt="# Team handbook",
        )

    async def fake_import(db, **kwargs):
        captured["import"] = kwargs
        return KBDocumentRead(
            id=document_id,
            title="Team handbook",
            concept_id=None,
            source_type="integration",
            source_updated_at=None,
            source_sync_status="pending",
            source_synced_at=None,
            status="pending",
            processing_error=None,
            processing_attempts=0,
            summary=None,
            external_url=f"https://www.notion.so/{page_id.replace('-', '')}",
            is_private=True,
            chunk_count=0,
            content_md=None,
            meta={"provider_key": "notion"},
            created_by_user_id=user.id,
            created_at=now,
            updated_at=now,
        )

    monkeypatch.setattr(
        "routes.kb.search_integration_sources.search_integration_knowledge_sources",
        fake_search,
    )
    monkeypatch.setattr(
        "routes.kb.preview_integration_source.preview_integration_knowledge_source",
        fake_preview,
    )
    monkeypatch.setattr(
        "routes.kb.create_document_from_integration.import_integration_document",
        fake_import,
    )

    searched = await db_async_client.get(
        "/api/v1/kb/integration-sources/search",
        headers=headers,
        params={
            "integration_resource_id": str(resource_id),
            "query": "handbook",
            "limit": 10,
        },
    )
    assert searched.status_code == 200
    assert searched.json()[0]["reference"] == {"page_id": page_id}
    assert captured["search"]["workspace"].id == workspace.id
    assert captured["search"]["actor"].id == user.id

    previewed = await db_async_client.post(
        "/api/v1/kb/integration-sources/preview",
        headers=headers,
        json={
            "integration_resource_id": str(resource_id),
            "source": {"page_id": page_id},
        },
    )
    assert previewed.status_code == 200
    assert previewed.json()["markdown_excerpt"] == "# Team handbook"

    imported = await db_async_client.post(
        "/api/v1/kb/documents/from-integration",
        headers=headers,
        json={
            "integration_resource_id": str(resource_id),
            "source": {"page_id": page_id},
        },
    )
    assert imported.status_code == 202
    assert imported.json()["source_sync_status"] == "pending"
    assert captured["import"]["payload"].is_private is True


@pytest.mark.parametrize(
    ("path", "method", "patch_target"),
    [
        (
            "/api/v1/kb/integration-sources/search",
            "get",
            "services.kb.integration_sources.search.authorize_integration_knowledge_source",
        ),
        (
            "/api/v1/kb/integration-sources/preview",
            "post",
            "services.kb.integration_sources.preview.authorize_integration_knowledge_source",
        ),
        (
            "/api/v1/kb/documents/from-integration",
            "post",
            "services.kb.integration_sources.import_document."
            "reauthorize_integration_knowledge_source",
        ),
    ],
)
async def test_provider_auth_loss_uses_source_unavailable_contract(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    method: str,
    patch_target: str,
) -> None:
    _user, _workspace, headers = await _workspace_session(
        db_session,
        role=WorkspaceRole.MEMBER,
    )
    resource_id = uuid4()

    async def auth_failed(*_args, **_kwargs):
        raise IntegrationAuthError(
            "Notion authorization expired",
            provider_key="notion",
            operation="read_knowledge_source",
        )

    async def authorize(*_args, **_kwargs):
        return SimpleNamespace(
            connection=SimpleNamespace(provider_key="notion"),
            resource=SimpleNamespace(id=resource_id),
            definition=SimpleNamespace(
                parse_source=lambda source: source,
                preview=auth_failed,
                search=auth_failed,
            ),
        )

    monkeypatch.setattr(patch_target, authorize)
    if method == "get":
        response = await db_async_client.get(
            path,
            headers=headers,
            params={"integration_resource_id": str(resource_id)},
        )
    else:
        response = await db_async_client.post(
            path,
            headers=headers,
            json={
                "integration_resource_id": str(resource_id),
                "source": {"page_id": str(uuid4())},
            },
        )

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["title"] == "Knowledge Source Unavailable"


@pytest.mark.parametrize("provider_status", [403, 404])
async def test_notion_access_loss_uses_source_unavailable_contract(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    provider_status: int,
) -> None:
    _user, _workspace, headers = await _workspace_session(
        db_session,
        role=WorkspaceRole.MEMBER,
    )
    resource_id = uuid4()
    page_id = str(uuid4())

    async def authorize(*_args, **_kwargs):
        return SimpleNamespace(
            connection=SimpleNamespace(provider_key="notion"),
            resource=SimpleNamespace(
                id=resource_id,
                external_id="notion-workspace",
                display_name="Example workspace",
            ),
            definition=KNOWLEDGE_SOURCE,
        )

    def provider_response(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(provider_status, json={}, request=request)

    monkeypatch.setattr(
        "services.kb.integration_sources.preview.authorize_integration_knowledge_source",
        authorize,
    )
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(provider_response)
    ) as provider_client:
        monkeypatch.setattr(
            notion_source_module,
            "notion_client_for_connection",
            lambda *_args: NotionClient(
                lambda _force: _notion_test_token(),
                client=provider_client,
            ),
        )
        response = await db_async_client.post(
            "/api/v1/kb/integration-sources/preview",
            headers=headers,
            json={
                "integration_resource_id": str(resource_id),
                "source": f"https://www.notion.so/{page_id.replace('-', '')}",
            },
        )

    assert response.status_code == 409
    assert response.json()["title"] == "Knowledge Source Unavailable"


async def _notion_test_token() -> str:
    return "notion-test-token"


async def test_cross_workspace_document_mutations_return_not_found(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace, headers = await _workspace_session(
        db_session,
        role=WorkspaceRole.MEMBER,
    )
    other_workspace = build_workspace(slug=f"kb-other-{uuid4().hex[:10]}")
    db_session.add(other_workspace)
    await db_session.flush()
    other_membership = build_workspace_membership(
        workspace_id=other_workspace.id,
        user_id=user.id,
        role=WorkspaceRole.MEMBER,
    )
    hidden = build_kb_document(
        workspace=other_workspace,
        created_by_user_id=user.id,
    )
    db_session.add_all([other_membership, hidden])
    await db_session.commit()

    response = await db_async_client.patch(
        f"/api/v1/kb/documents/{hidden.id}",
        headers=headers,
        json={"title": "Cross-tenant update"},
    )
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert workspace.id != other_workspace.id
