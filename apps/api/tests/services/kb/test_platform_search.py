# apps/api/tests/services/kb/test_platform_search.py

"""Combined retrieval enforces ownership before ranking and meters the requester."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text

from core.database import maintenance_async_db_session, set_session_tenant_context
from core.settings import settings
from models.ai_usage_event import AIUsageEvent
from services.kb.search_chunks import search_chunks
from tests.factories import build_kb_chunk, build_kb_document, build_user, build_workspace
from tests.services.kb.test_search_chunks import FailingEmbeddingProvider
from tests.support.embeddings import FakeEmbeddingProvider


@pytest.fixture
async def mixed_corpus(db_session_factory):
    async with maintenance_async_db_session() as db:
        workspace, other_workspace = build_workspace(slug="a"), build_workspace(slug="b")
        user, other_user = build_user(email="a@example.com"), build_user(email="b@example.com")
        db.add_all([workspace, other_workspace, user, other_user])
        await db.flush()
        vector = await FakeEmbeddingProvider().embed_texts(
            ["shared retrieval guidance"], model=settings.EMBEDDINGS_MODEL, dimensions=1024
        )
        documents = {}
        cases = {
            "local": {},
            "private": {"is_private": True},
            "other_private": {"is_private": True, "created_by_user_id": other_user.id},
            "other_workspace": {"workspace_id": other_workspace.id},
            "platform": {"scope": "platform", "workspace_id": None, "is_published": True},
            "pending_embedding": {
                "scope": "platform",
                "workspace_id": None,
                "is_published": True,
                "source_type": "upload",
            },
            "draft": {"scope": "platform", "workspace_id": None},
            "withdrawn": {"scope": "platform", "workspace_id": None},
            "deleted": {
                "scope": "platform",
                "workspace_id": None,
                "is_published": True,
                "deleted": True,
                "deleted_at": datetime.now(UTC),
            },
            "unavailable": {"source_type": "url", "source_sync_status": "unavailable"},
        }
        for name, overrides in cases.items():
            values = {
                "title": "Shared title",
                "status": "ready",
                "is_private": False,
                "created_by_user_id": user.id,
                "content_md": "shared retrieval guidance",
                "chunk_count": 1,
            }
            values.update(overrides)
            document = build_kb_document(workspace=workspace, **values)
            db.add(document)
            await db.flush()
            chunk = build_kb_chunk(
                document=document,
                scope=document.scope,
                content=document.content_md,
            )
            if name != "pending_embedding":
                chunk.embedding = vector.vectors[0]
                chunk.embedding_provider = vector.provider
                chunk.embedding_model = vector.model
                chunk.embedding_dims = vector.dimensions
            db.add(chunk)
            documents[name] = document
        await db.flush()
        documents["withdrawn"].is_published = True
        await db.flush()
        documents["withdrawn"].is_published = False
    return workspace, user, documents


@pytest.mark.parametrize("maintenance", [False, True])
@pytest.mark.parametrize("semantic", [False, True])
@pytest.mark.parametrize("filter_kind", ["all", "private", "documents", "source", "hidden"])
async def test_combined_search_visibility(
    db_session_factory, mixed_corpus, maintenance, semantic, filter_kind
):
    workspace, user, documents = mixed_corpus
    filters = {}
    expected = {"local", "private", "platform", "pending_embedding"}
    if filter_kind == "private":
        filters = {"private_only": True}
        expected = {"private"}
    elif filter_kind == "documents":
        filters = {"document_ids": [documents[name].id for name in ("platform", "draft", "local")]}
        expected = {"platform", "local"}
    elif filter_kind == "source":
        filters = {"source_types": ["upload"]}
        expected = {"pending_embedding"}
    elif filter_kind == "hidden":
        filters = {
            "document_ids": [documents[name].id for name in ("draft", "withdrawn", "other_private")]
        }
        expected = set()
    session = maintenance_async_db_session() if maintenance else db_session_factory()
    async with session as db:
        if not maintenance:
            await set_session_tenant_context(db, workspace_id=workspace.id, user_id=user.id)
            assert await db.scalar(text("SELECT current_user")) == "praxis_app"
        result = await search_chunks(
            db,
            workspace_id=workspace.id,
            user_id=user.id,
            query="shared retrieval guidance",
            provider=FakeEmbeddingProvider() if semantic else FailingEmbeddingProvider(),
            top_k=50,
            **filters,
        )
        await db.commit()
    assert {hit.document_id for hit in result.results} == {documents[name].id for name in expected}
    assert result.mode == ("hybrid" if semantic else "lexical_fallback")
    for hit in result.results:
        document = next(row for row in documents.values() if row.id == hit.document_id)
        assert hit.scope == document.scope
        encoded = hit.model_dump(mode="json")
        if hit.scope == "platform":
            assert encoded["content"] == {
                "node": "praxis_untrusted",
                "source_kind": "kb",
                "source_ref": f"chunk:{hit.id}",
                "content": hit.content,
            }
        else:
            assert encoded["content"] == hit.content
        assert hit.sources == (
            ["lexical", "semantic"] if semantic and not hit.pending_embedding else ["lexical"]
        )
    if semantic:
        async with maintenance_async_db_session() as db:
            events = list(
                await db.scalars(
                    select(AIUsageEvent).where(AIUsageEvent.workspace_id == workspace.id)
                )
            )
        assert len(events) == 1
        assert events[0].scope == "workspace"
        assert events[0].workspace_id == workspace.id
        assert events[0].purpose == "embedding_kb_search"
        assert events[0].requests == 1


@pytest.mark.parametrize("semantic", [False, True])
async def test_candidate_limits_follow_visibility_and_document_filters(
    db_session_factory, mixed_corpus, monkeypatch, semantic
):
    workspace, user, documents = mixed_corpus
    monkeypatch.setattr(settings, "KB_SEARCH_CTE_LIMIT", 1)
    # Maintenance deliberately removes RLS as a second line of defence.
    async with maintenance_async_db_session() as db:
        result = await search_chunks(
            db,
            workspace_id=workspace.id,
            user_id=user.id,
            query="shared retrieval guidance",
            document_ids=[documents["platform"].id, documents["draft"].id],
            provider=FakeEmbeddingProvider() if semantic else FailingEmbeddingProvider(),
            top_k=1,
        )
    assert [hit.document_id for hit in result.results] == [documents["platform"].id]
