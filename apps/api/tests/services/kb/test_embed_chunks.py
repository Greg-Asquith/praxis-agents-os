# apps/api/tests/services/kb/test_embed_chunks.py

"""Knowledge-base embedding job tests."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from core.settings import settings
from models.kb import KBChunk
from services.embeddings.domain import EmbeddingConfigurationError
from services.embeddings.get_embedding_usage import get_embedding_usage
from services.kb.embed_chunks import embed_kb_chunks
from tests.factories import build_kb_chunk, build_kb_document
from tests.services.kb.conftest import KBActors
from tests.support.embeddings import FakeEmbeddingProvider

pytestmark = pytest.mark.asyncio


async def test_embedding_requires_workspace_scope_before_mutating(
    db_session: AsyncSession,
    kb_actors: KBActors,
) -> None:
    document = build_kb_document(workspace=kb_actors.workspace, status="ready", chunk_count=1)
    chunk = build_kb_chunk(document=document)
    db_session.add(document)
    await db_session.flush()
    db_session.add(chunk)
    await db_session.flush()

    with pytest.raises(AppValidationError, match="require a workspace"):
        await embed_kb_chunks(
            db_session,
            document_id=document.id,
            workspace_id=None,
            provider=FakeEmbeddingProvider(),
        )

    await db_session.refresh(chunk)
    assert chunk.embedding is None


async def test_embedding_fills_only_null_rows_and_meters_usage(
    db_session: AsyncSession,
    kb_actors: KBActors,
) -> None:
    document = build_kb_document(workspace=kb_actors.workspace, status="ready", chunk_count=2)
    first = build_kb_chunk(document=document, chunk_index=0, content="first knowledge")
    second = build_kb_chunk(document=document, chunk_index=1, content="second knowledge")
    db_session.add(document)
    await db_session.flush()
    db_session.add_all([first, second])
    await db_session.flush()

    await embed_kb_chunks(
        db_session,
        document_id=document.id,
        workspace_id=kb_actors.workspace.id,
        provider=FakeEmbeddingProvider(),
    )

    rows = (
        await db_session.scalars(
            select(KBChunk).where(KBChunk.document_id == document.id).order_by(KBChunk.chunk_index)
        )
    ).all()
    assert all(row.embedding is not None for row in rows)
    assert {(row.embedding_provider, row.embedding_model, row.embedding_dims) for row in rows} == {
        ("fake", settings.EMBEDDINGS_MODEL, 1024)
    }
    first_usage = await get_embedding_usage(db_session, workspace_id=kb_actors.workspace.id)
    assert first_usage > 0

    await embed_kb_chunks(
        db_session,
        document_id=document.id,
        workspace_id=kb_actors.workspace.id,
        provider=FakeEmbeddingProvider(),
    )
    assert (
        await get_embedding_usage(
            db_session,
            workspace_id=kb_actors.workspace.id,
        )
        == first_usage
    )


async def test_dimension_mismatch_fails_before_writing(
    db_session: AsyncSession,
    kb_actors: KBActors,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = build_kb_document(workspace=kb_actors.workspace, status="ready", chunk_count=1)
    chunk = build_kb_chunk(document=document)
    db_session.add(document)
    await db_session.flush()
    db_session.add(chunk)
    await db_session.flush()
    monkeypatch.setattr(settings, "EMBEDDINGS_DIMENSIONS", 768)

    with pytest.raises(EmbeddingConfigurationError, match="dimensions"):
        await embed_kb_chunks(
            db_session,
            document_id=document.id,
            workspace_id=kb_actors.workspace.id,
            provider=FakeEmbeddingProvider(dimensions=768),
        )

    await db_session.refresh(chunk)
    assert chunk.embedding is None


async def test_existing_collection_stamp_rejects_a_different_model(
    db_session: AsyncSession,
    kb_actors: KBActors,
) -> None:
    existing_document = build_kb_document(
        workspace=kb_actors.workspace,
        status="ready",
        chunk_count=1,
    )
    pending_document = build_kb_document(
        workspace=kb_actors.workspace,
        status="ready",
        chunk_count=1,
    )
    db_session.add_all([existing_document, pending_document])
    await db_session.flush()
    db_session.add_all(
        [
            build_kb_chunk(
                document=existing_document,
                embedding=[0.0] * 1024,
                embedding_provider="fake",
                embedding_model="older-model",
                embedding_dims=1024,
            ),
            build_kb_chunk(document=pending_document),
        ]
    )
    await db_session.flush()

    with pytest.raises(EmbeddingConfigurationError, match="does not match"):
        await embed_kb_chunks(
            db_session,
            document_id=pending_document.id,
            workspace_id=kb_actors.workspace.id,
            provider=FakeEmbeddingProvider(),
        )

    pending_chunk = await db_session.scalar(
        select(KBChunk).where(KBChunk.document_id == pending_document.id)
    )
    assert pending_chunk is not None
    assert pending_chunk.embedding is None
