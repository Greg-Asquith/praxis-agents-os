# apps/api/tests/services/kb/test_ingest_document.py

"""Knowledge-base ingestion lifecycle tests."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from models.jobs import Job
from models.kb import KBChunk, KBDocument
from services.files.utils import private_ref_from_key
from services.kb import create_kb_document
from services.kb.ingest_document import ingest_kb_document
from services.storage.factory import get_storage_provider
from tests.factories import build_file, build_file_revision
from tests.services.kb.conftest import KBActors

pytestmark = pytest.mark.asyncio


async def _ingest(
    db: AsyncSession,
    actors: KBActors,
    document: KBDocument,
) -> None:
    await ingest_kb_document(
        db,
        document_id=document.id,
        workspace_id=actors.workspace.id,
        initiated_by_user_id=actors.user.id,
    )


async def test_manual_ingest_is_lexically_ready_before_embedding(
    db_session: AsyncSession,
    kb_actors: KBActors,
) -> None:
    document = await create_kb_document(
        db_session,
        workspace_id=kb_actors.workspace.id,
        source_type="manual",
        title="VPN guide",
        content="# Access\n\nConfigure the orbital VPN before connecting.",
    )

    await _ingest(db_session, kb_actors, document)

    await db_session.refresh(document)
    chunks = (
        await db_session.scalars(
            select(KBChunk).where(KBChunk.document_id == document.id).order_by(KBChunk.chunk_index)
        )
    ).all()
    assert document.status == "ready"
    assert document.chunk_count == len(chunks) > 0
    assert all(chunk.embedding is None for chunk in chunks)
    lexical_count = await db_session.scalar(
        select(func.count(KBChunk.id)).where(
            KBChunk.document_id == document.id,
            KBChunk.tsv.op("@@")(func.websearch_to_tsquery("english", "orbital VPN")),
        )
    )
    assert lexical_count
    assert (
        await db_session.scalar(
            select(func.count(Job.id)).where(
                Job.kind == "kb.embed_chunks",
                Job.subject_id == document.id,
            )
        )
        == 1
    )


async def test_unchanged_reingest_preserves_chunks_and_source_timestamp(
    db_session: AsyncSession,
    kb_actors: KBActors,
) -> None:
    document = await create_kb_document(
        db_session,
        workspace_id=kb_actors.workspace.id,
        source_type="manual",
        title="Stable",
        content="Stable knowledge.",
    )
    await _ingest(db_session, kb_actors, document)
    first_ids = tuple(
        await db_session.scalars(
            select(KBChunk.id)
            .where(KBChunk.document_id == document.id)
            .order_by(KBChunk.chunk_index)
        )
    )
    original_source_updated_at = document.source_updated_at

    await _ingest(db_session, kb_actors, document)

    second_ids = tuple(
        await db_session.scalars(
            select(KBChunk.id)
            .where(KBChunk.document_id == document.id)
            .order_by(KBChunk.chunk_index)
        )
    )
    await db_session.refresh(document)
    assert second_ids == first_ids
    assert document.source_updated_at == original_source_updated_at


async def test_changed_content_replaces_chunks_and_updates_source_timestamp(
    db_session: AsyncSession,
    kb_actors: KBActors,
) -> None:
    document = await create_kb_document(
        db_session,
        workspace_id=kb_actors.workspace.id,
        source_type="manual",
        title="Changing",
        content="Original content.",
    )
    await _ingest(db_session, kb_actors, document)
    first_ids = set(
        await db_session.scalars(select(KBChunk.id).where(KBChunk.document_id == document.id))
    )
    document.content_md = "Replacement knowledge with a distinct hash."
    document.source_updated_at = datetime(2000, 1, 1, tzinfo=UTC)
    await db_session.flush()

    await _ingest(db_session, kb_actors, document)

    second_ids = set(
        await db_session.scalars(select(KBChunk.id).where(KBChunk.document_id == document.id))
    )
    await db_session.refresh(document)
    assert second_ids.isdisjoint(first_ids)
    assert document.source_updated_at > datetime(2000, 1, 1, tzinfo=UTC)


async def test_upload_ingests_extracted_markdown(
    db_session: AsyncSession,
    kb_actors: KBActors,
) -> None:
    file = build_file(workspace=kb_actors.workspace)
    revision = build_file_revision(
        file,
        markdown_object_key=f"private/{kb_actors.workspace.id}/kb-source.md",
    )
    db_session.add_all([file, revision])
    await db_session.flush()
    await get_storage_provider().put_object(
        private_ref_from_key(revision.markdown_object_key),
        b"# Uploaded\n\nExtracted orbital knowledge.",
        content_type="text/markdown",
    )
    document = await create_kb_document(
        db_session,
        workspace_id=kb_actors.workspace.id,
        source_type="upload",
        title="Upload",
        file_revision_id=revision.id,
        annotate=False,
    )

    await _ingest(db_session, kb_actors, document)

    await db_session.refresh(document)
    assert document.status == "ready"
    assert "Extracted orbital knowledge" in (document.content_md or "")


async def test_deleted_document_is_an_idempotent_noop(
    db_session: AsyncSession,
    kb_actors: KBActors,
) -> None:
    document = await create_kb_document(
        db_session,
        workspace_id=kb_actors.workspace.id,
        source_type="manual",
        title="Deleted",
        content="Do not ingest.",
    )
    document.soft_delete(deleted_by=kb_actors.user.id, cascade=False)
    await db_session.flush()

    await _ingest(db_session, kb_actors, document)

    assert (
        await db_session.scalar(
            select(func.count(KBChunk.id)).where(KBChunk.document_id == document.id)
        )
        == 0
    )


async def test_ingest_requires_workspace_scope_before_mutating(
    db_session: AsyncSession,
    kb_actors: KBActors,
) -> None:
    document = await create_kb_document(
        db_session,
        workspace_id=kb_actors.workspace.id,
        source_type="manual",
        title="Scoped",
        content="Workspace knowledge.",
    )

    with pytest.raises(AppValidationError, match="require a workspace"):
        await ingest_kb_document(
            db_session,
            document_id=document.id,
            workspace_id=None,
            initiated_by_user_id=kb_actors.user.id,
        )

    await db_session.refresh(document)
    assert document.status == "pending"
    assert document.processing_attempts == 0
    assert (
        await db_session.scalar(
            select(func.count(KBChunk.id)).where(KBChunk.document_id == document.id)
        )
        == 0
    )


async def test_failure_status_survives_reraise(
    db_session: AsyncSession,
    kb_actors: KBActors,
) -> None:
    document = await create_kb_document(
        db_session,
        workspace_id=kb_actors.workspace.id,
        source_type="url",
        title="Missing URL",
        url="https://example.com/source",
    )
    document.external_url = None
    await db_session.commit()

    with pytest.raises(AppValidationError, match="no source URL"):
        await _ingest(db_session, kb_actors, document)

    failed = await db_session.get(KBDocument, document.id)
    assert failed is not None
    assert failed.status == "error"
    assert failed.processing_attempts == 1
    assert failed.processing_error == "URL document has no source URL"
