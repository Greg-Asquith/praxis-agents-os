# apps/api/tests/services/kb/test_platform_document_reads.py

"""Tenant document reads combine published knowledge without widening write access."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from core.database import maintenance_async_db_session, set_session_tenant_context
from core.exceptions.general import NotFoundError
from models.kb import KBDocument
from services.kb.documents.list_documents import list_documents
from services.kb.documents.utils import get_mutable_document
from services.kb.get_document import get_kb_document
from services.kb.visibility import visible_document_filter
from tests.factories import build_kb_document, build_user, build_workspace
from utils.content import ContentScope


@pytest.fixture
async def mixed_documents(db_session_factory):
    async with maintenance_async_db_session() as db:
        actor = build_user(email=f"reader-{uuid4()}@example.com")
        other = build_user(email=f"other-{uuid4()}@example.com")
        workspace = build_workspace(slug=f"reader-{uuid4()}")
        other_workspace = build_workspace(slug=f"other-{uuid4()}")
        db.add_all([actor, other, workspace, other_workspace])
        await db.flush()
        documents = {}
        for name, values in {
            "workspace": {},
            "private": {"is_private": True},
            "other_private": {"is_private": True, "created_by_user_id": other.id},
            "other_workspace": {"workspace_id": other_workspace.id},
            "platform": {"scope": "platform", "workspace_id": None, "is_published": True},
            "draft": {"scope": "platform", "workspace_id": None},
            "withdrawn": {"scope": "platform", "workspace_id": None, "status": "ready"},
            "deleted": {
                "scope": "platform",
                "workspace_id": None,
                "is_published": True,
                "deleted": True,
                "deleted_at": datetime.now(UTC),
            },
            "unavailable": {"source_type": "url", "source_sync_status": "unavailable"},
        }.items():
            documents[name] = build_kb_document(
                workspace=workspace,
                **{"created_by_user_id": actor.id, "title": name, "status": "ready", **values},
            )
        db.add_all(documents.values())
    return actor, workspace, other_workspace, documents


@pytest.mark.parametrize("tenant", ["owner", "other", "missing"])
async def test_platform_document_get_respects_tenant_and_publication(
    db_session_factory, mixed_documents, tenant
):
    actor, workspace, other_workspace, documents = mixed_documents
    selected = other_workspace if tenant == "other" else workspace
    expected = {"platform"}
    if tenant == "owner":
        expected |= {"workspace", "private", "unavailable"}
    elif tenant == "other":
        expected |= {"other_workspace"}
    else:
        expected = set()
    async with db_session_factory() as db:
        if tenant != "missing":
            await set_session_tenant_context(db, workspace_id=selected.id, user_id=actor.id)
        for name, document in documents.items():
            kwargs = {"workspace_id": selected.id, "user_id": actor.id, "document_id": document.id}
            if name in expected:
                result = await get_kb_document(db, **kwargs)
                assert result.id == document.id
                assert result.scope == document.scope
            else:
                with pytest.raises(NotFoundError):
                    await get_kb_document(db, **kwargs)


@pytest.mark.parametrize(
    "scope,is_private,expected",
    [
        (None, None, {"workspace", "private", "platform"}),
        (ContentScope.WORKSPACE, None, {"workspace", "private"}),
        (ContentScope.PLATFORM, None, {"platform"}),
        (None, True, {"private"}),
        (ContentScope.PLATFORM, True, set()),
        (None, False, {"workspace", "platform"}),
    ],
)
async def test_platform_document_list_filters_before_pagination(
    db_session_factory, mixed_documents, scope, is_private, expected
):
    actor, workspace, _, documents = mixed_documents
    async with db_session_factory() as db:
        await set_session_tenant_context(db, workspace_id=workspace.id, user_id=actor.id)
        found = set()
        for offset in range(max(1, len(expected))):
            result = await list_documents(
                db,
                actor=actor,
                workspace=workspace,
                limit=1,
                offset=offset,
                source_type="manual",
                status="ready",
                is_private=is_private,
                scope=scope,
            )
            assert result.total == len(expected)
            assert len(result.documents) <= 1
            found.update(item.id for item in result.documents)
        assert found == {documents[name].id for name in expected}


async def test_platform_document_reads_do_not_authorise_workspace_mutations(
    db_session_factory, mixed_documents
):
    actor, workspace, _, documents = mixed_documents
    async with db_session_factory() as db:
        await set_session_tenant_context(db, workspace_id=workspace.id, user_id=actor.id)
        with pytest.raises(NotFoundError):
            await get_mutable_document(
                db,
                workspace_id=workspace.id,
                user_id=actor.id,
                document_id=documents["platform"].id,
            )
        local = await get_mutable_document(
            db,
            workspace_id=workspace.id,
            user_id=actor.id,
            document_id=documents["private"].id,
        )
        assert local.id == documents["private"].id


@pytest.mark.parametrize("source_type", ["url", "integration"])
@pytest.mark.parametrize("sync_status", ["pending", "error", "unavailable", "disconnected"])
async def test_unready_local_source_keeps_recovery_metadata_without_cached_content(
    db_session_factory, mixed_documents, source_type, sync_status
):
    actor, workspace, _, documents = mixed_documents
    document_id = documents["unavailable"].id
    async with maintenance_async_db_session() as db:
        document = await db.get(KBDocument, document_id)
        document.source_type = source_type
        document.external_id = "example-page" if source_type == "integration" else None
        document.source_sync_status = sync_status
        document.summary = "Cached summary"
        document.content_md = "Cached source content"
        document.processing_error = "Refresh this source to restore access."
    async with db_session_factory() as db:
        await set_session_tenant_context(db, workspace_id=workspace.id, user_id=actor.id)
        result = await list_documents(
            db,
            actor=actor,
            workspace=workspace,
            limit=10,
            offset=0,
            source_type=source_type,
            status=None,
            is_private=None,
        )
        assert [item.id for item in result.documents] == [document_id]
        assert result.documents[0].source_sync_status == sync_status
        detail = await get_kb_document(
            db, workspace_id=workspace.id, user_id=actor.id, document_id=document_id
        )
        assert detail.content_md is None and detail.summary is None
        assert detail.processing_error == "Refresh this source to restore access."
        mutable = await get_mutable_document(
            db, workspace_id=workspace.id, user_id=actor.id, document_id=document_id
        )
        assert mutable.content_md == "Cached source content"
        assert (
            await db.scalar(
                select(KBDocument.id).where(
                    KBDocument.id == document_id,
                    visible_document_filter(workspace.id, actor.id),
                )
            )
            is None
        )
