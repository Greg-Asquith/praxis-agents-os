# apps/api/tests/services/kb/test_ingest_document.py

"""Knowledge-base ingestion lifecycle tests."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError, ConflictError
from models.jobs import Job
from models.kb import KBChunk, KBDocument
from services.files.utils import private_ref_from_key
from services.jobs.domain import JOB_STATUS_RUNNING, JOB_STATUS_SUCCEEDED
from services.jobs.finalize_job import finalize_job_success
from services.jobs.handlers.ingest_kb_document import handle_ingest_kb_document
from services.kb import create_kb_document
from services.kb.domain import FetchedUrl, KBSourceUnavailableError
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


async def test_failed_changed_content_ingest_rebuilds_chunks_on_retry(
    db_session: AsyncSession,
    kb_actors: KBActors,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = await create_kb_document(
        db_session,
        workspace_id=kb_actors.workspace.id,
        source_type="manual",
        title="Retryable refresh",
        content="Original searchable knowledge.",
    )
    document_id = document.id
    workspace_id = kb_actors.workspace.id
    user_id = kb_actors.user.id
    await _ingest(db_session, kb_actors, document)
    await db_session.commit()
    original_chunk_ids = set(
        await db_session.scalars(select(KBChunk.id).where(KBChunk.document_id == document_id))
    )

    document.content_md = "Replacement searchable knowledge."
    await db_session.commit()

    def fail_chunking(*args: object, **kwargs: object) -> None:
        raise RuntimeError("chunking failed")

    with monkeypatch.context() as patch:
        patch.setattr("services.kb.ingest_document.chunk_markdown", fail_chunking)
        with pytest.raises(RuntimeError, match="chunking failed"):
            await ingest_kb_document(
                db_session,
                document_id=document_id,
                workspace_id=workspace_id,
                initiated_by_user_id=user_id,
            )

    await db_session.refresh(document)
    chunks_after_failure = set(
        await db_session.scalars(select(KBChunk.id).where(KBChunk.document_id == document_id))
    )
    assert chunks_after_failure == set()
    assert document.chunk_count == 0
    assert document.status == "error"

    await ingest_kb_document(
        db_session,
        document_id=document_id,
        workspace_id=workspace_id,
        initiated_by_user_id=user_id,
    )

    await db_session.refresh(document)
    replacement_chunks = (
        await db_session.scalars(select(KBChunk).where(KBChunk.document_id == document_id))
    ).all()
    assert {chunk.id for chunk in replacement_chunks}.isdisjoint(original_chunk_ids)
    assert [chunk.content for chunk in replacement_chunks] == ["Replacement searchable knowledge."]
    assert document.chunk_count == len(replacement_chunks) == 1
    assert document.status == "ready"


async def test_upload_ingests_extracted_markdown(
    db_session: AsyncSession,
    kb_actors: KBActors,
) -> None:
    file = build_file(workspace=kb_actors.workspace)
    revision = build_file_revision(
        file,
        markdown_object_key=f"workspaces/{kb_actors.workspace.id}/kb-source.md",
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


async def test_upload_ingest_rejects_secret_before_storing_extracted_content(
    db_session: AsyncSession,
    kb_actors: KBActors,
) -> None:
    detected_secret = "AKIA1234567890ABCDEF"
    file = build_file(workspace=kb_actors.workspace)
    revision = build_file_revision(
        file,
        markdown_object_key=f"workspaces/{kb_actors.workspace.id}/kb-secret-source.md",
    )
    db_session.add_all([file, revision])
    await db_session.flush()
    await get_storage_provider().put_object(
        private_ref_from_key(revision.markdown_object_key),
        f"# Credentials\n\nDo not store {detected_secret}.".encode(),
        content_type="text/markdown",
    )
    document = await create_kb_document(
        db_session,
        workspace_id=kb_actors.workspace.id,
        source_type="upload",
        title="Unsafe upload",
        file_revision_id=revision.id,
        annotate=False,
    )

    with pytest.raises(AppValidationError):
        await _ingest(db_session, kb_actors, document)

    await db_session.refresh(document)
    assert document.status == "error"
    assert document.content_md is None
    assert document.content_hash == ""
    assert detected_secret not in (document.processing_error or "")


async def test_upload_ingest_rejects_duplicate_materialized_content(
    db_session: AsyncSession,
    kb_actors: KBActors,
) -> None:
    documents: list[KBDocument] = []
    for index in range(2):
        file = build_file(workspace=kb_actors.workspace)
        revision = build_file_revision(
            file,
            markdown_object_key=(
                f"workspaces/{kb_actors.workspace.id}/kb-duplicate-source-{index}.md"
            ),
        )
        db_session.add_all([file, revision])
        await db_session.flush()
        await get_storage_provider().put_object(
            private_ref_from_key(revision.markdown_object_key),
            b"# Shared source\n\nIdentical extracted knowledge.",
            content_type="text/markdown",
        )
        documents.append(
            await create_kb_document(
                db_session,
                workspace_id=kb_actors.workspace.id,
                source_type="upload",
                title=f"Upload {index}",
                file_revision_id=revision.id,
                annotate=False,
            )
        )

    await _ingest(db_session, kb_actors, documents[0])
    with pytest.raises(ConflictError):
        await _ingest(db_session, kb_actors, documents[1])

    await db_session.refresh(documents[1])
    assert documents[1].status == "error"
    assert documents[1].content_md is None
    assert documents[1].content_hash == ""


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


async def test_url_ingest_stores_validators_and_not_modified_preserves_chunks(
    db_session: AsyncSession,
    kb_actors: KBActors,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    last_modified = "Tue, 01 Sep 2026 09:00:00 GMT"
    responses = [
        FetchedUrl(
            data=b"# Guide\n\nStable URL knowledge.",
            content_type="text/markdown",
            etag='"revision-1"',
            last_modified=last_modified,
            not_modified=False,
        ),
        FetchedUrl(
            data=b"",
            content_type="application/octet-stream",
            etag='"revision-1"',
            last_modified=last_modified,
            not_modified=True,
        ),
    ]
    requests: list[tuple[str | None, str | None]] = []

    async def fetch(
        _url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> FetchedUrl:
        requests.append((etag, last_modified))
        return responses.pop(0)

    async def convert(data: bytes, **_kwargs: object) -> str:
        return data.decode()

    monkeypatch.setattr("services.kb.ingest_document.fetch_url", fetch)
    monkeypatch.setattr("services.kb.ingest_document.convert_html_to_markdown", convert)
    document = await create_kb_document(
        db_session,
        workspace_id=kb_actors.workspace.id,
        source_type="url",
        title="Refreshable guide",
        url="https://example.com/guide",
    )
    assert document.source_sync_status == "pending"

    await _ingest(db_session, kb_actors, document)

    first_chunk_ids = tuple(
        await db_session.scalars(
            select(KBChunk.id)
            .where(KBChunk.document_id == document.id)
            .order_by(KBChunk.chunk_index)
        )
    )
    first_synced_at = document.source_synced_at
    assert first_chunk_ids
    assert document.status == "ready"
    assert document.source_sync_status == "ready"
    assert document.source_updated_at == datetime(2026, 9, 1, 9, tzinfo=UTC)
    assert document.meta == {
        "etag": '"revision-1"',
        "last_modified": last_modified,
    }

    def fail_hashing(_markdown: str) -> str:
        raise AssertionError("A not-modified response must skip hashing")

    monkeypatch.setattr("services.kb.ingest_document.compute_markdown_hash", fail_hashing)

    await _ingest(db_session, kb_actors, document)

    second_chunk_ids = tuple(
        await db_session.scalars(
            select(KBChunk.id)
            .where(KBChunk.document_id == document.id)
            .order_by(KBChunk.chunk_index)
        )
    )
    await db_session.refresh(document)
    assert requests == [(None, None), ('"revision-1"', last_modified)]
    assert second_chunk_ids == first_chunk_ids
    assert document.source_sync_status == "ready"
    assert document.source_synced_at is not None
    assert first_synced_at is not None
    assert document.source_synced_at >= first_synced_at


async def test_url_not_modified_without_stored_content_forces_full_refetch(
    db_session: AsyncSession,
    kb_actors: KBActors,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[tuple[str | None, str | None]] = []

    async def fetch(
        _url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> FetchedUrl:
        requests.append((etag, last_modified))
        if len(requests) == 1:
            return FetchedUrl(
                data=b"",
                content_type="application/octet-stream",
                etag='"stale"',
                last_modified=None,
                not_modified=True,
            )
        return FetchedUrl(
            data=b"# Restored\n\nFresh URL content.",
            content_type="text/markdown",
            etag='"fresh"',
            last_modified=None,
            not_modified=False,
        )

    async def convert(data: bytes, **_kwargs: object) -> str:
        return data.decode()

    monkeypatch.setattr("services.kb.ingest_document.fetch_url", fetch)
    monkeypatch.setattr("services.kb.ingest_document.convert_html_to_markdown", convert)
    document = await create_kb_document(
        db_session,
        workspace_id=kb_actors.workspace.id,
        source_type="url",
        title="Empty URL source",
        url="https://example.com/empty",
        meta={"etag": '"stale"'},
    )

    await _ingest(db_session, kb_actors, document)

    await db_session.refresh(document)
    assert requests == [('"stale"', None), (None, None)]
    assert document.status == "ready"
    assert document.source_sync_status == "ready"
    assert document.source_synced_at is not None
    assert document.content_md == "# Restored\n\nFresh URL content."
    assert document.chunk_count > 0
    assert document.meta == {"etag": '"fresh"'}


@pytest.mark.parametrize(
    ("status_code", "error_code"),
    [(429, "rate_limited"), (503, "refresh_failed")],
)
async def test_transient_url_failure_retains_last_ready_content(
    db_session: AsyncSession,
    kb_actors: KBActors,
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    error_code: str,
) -> None:
    response: FetchedUrl | Exception = FetchedUrl(
        data=b"# Guide\n\nLast good URL content.",
        content_type="text/markdown",
        etag='"revision-1"',
        last_modified=None,
        not_modified=False,
    )

    async def fetch(_url: str, **_kwargs: object) -> FetchedUrl:
        if isinstance(response, Exception):
            raise response
        return response

    async def convert(data: bytes, **_kwargs: object) -> str:
        return data.decode()

    monkeypatch.setattr("services.kb.ingest_document.fetch_url", fetch)
    monkeypatch.setattr("services.kb.ingest_document.convert_html_to_markdown", convert)
    document = await create_kb_document(
        db_session,
        workspace_id=kb_actors.workspace.id,
        source_type="url",
        title="Transient URL source",
        url="https://example.com/transient",
    )
    await _ingest(db_session, kb_actors, document)
    original_content = document.content_md
    original_hash = document.content_hash
    assert document.source_updated_at is not None
    original_chunk_ids = set(
        await db_session.scalars(select(KBChunk.id).where(KBChunk.document_id == document.id))
    )
    response = AppValidationError(
        "Knowledge-base URL returned an unsuccessful response",
        field="url",
        details={"status_code": status_code},
    )

    with pytest.raises(AppValidationError):
        await _ingest(db_session, kb_actors, document)

    retained_chunk_ids = set(
        await db_session.scalars(select(KBChunk.id).where(KBChunk.document_id == document.id))
    )
    await db_session.refresh(document)
    assert document.status == "error"
    assert document.source_sync_status == "error"
    assert document.content_md == original_content
    assert document.content_hash == original_hash
    assert retained_chunk_ids == original_chunk_ids
    assert document.meta == {
        "etag": '"revision-1"',
        "last_error_code": error_code,
    }


async def test_unavailable_url_finishes_job_and_later_refresh_restores_content(
    db_session: AsyncSession,
    kb_actors: KBActors,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response: FetchedUrl | Exception = KBSourceUnavailableError(
        error_code="not_found",
        status_code=404,
    )

    async def fetch(_url: str, **_kwargs: object) -> FetchedUrl:
        if isinstance(response, Exception):
            raise response
        return response

    async def convert(data: bytes, **_kwargs: object) -> str:
        return data.decode()

    monkeypatch.setattr("services.kb.ingest_document.fetch_url", fetch)
    monkeypatch.setattr("services.kb.ingest_document.convert_html_to_markdown", convert)
    document = await create_kb_document(
        db_session,
        workspace_id=kb_actors.workspace.id,
        source_type="url",
        title="Unavailable URL source",
        url="https://example.com/missing",
        meta={"etag": '"revision-1"'},
    )
    document.content_md = "# Stale\n\nStale searchable content."
    document.content_hash = "stale-hash"
    document.summary = "Stale summary"
    chunk = KBChunk(
        document_id=document.id,
        workspace_id=document.workspace_id,
        chunk_index=0,
        content="Stale searchable content.",
        char_start=0,
        char_end=25,
        token_estimate=7,
        meta={"headings": ["Stale"]},
    )
    db_session.add(chunk)
    document.chunk_count = 1
    job = await db_session.scalar(
        select(Job).where(Job.kind == "kb.ingest_document", Job.subject_id == document.id)
    )
    assert job is not None
    owner_id = f"kb-url-unavailable-{uuid4().hex}"
    job.status = JOB_STATUS_RUNNING
    job.attempts = 1
    job.locked_by = owner_id
    job.locked_at = datetime.now(UTC)
    job.lock_expires_at = datetime.now(UTC) + timedelta(minutes=5)

    await handle_ingest_kb_document(db_session, job)
    finalized = await finalize_job_success(
        db_session,
        job,
        owner_instance_id=owner_id,
    )

    await db_session.refresh(document)
    assert finalized is True
    assert job.status == JOB_STATUS_SUCCEEDED
    assert document.status == "error"
    assert document.source_sync_status == "unavailable"
    assert document.processing_error == "This page is no longer available at its URL."
    assert document.content_md is None
    assert document.summary is None
    assert document.content_hash == ""
    assert document.chunk_count == 0
    assert document.meta == {
        "etag": '"revision-1"',
        "last_error_code": "not_found",
    }
    assert (
        await db_session.scalar(
            select(func.count(KBChunk.id)).where(KBChunk.document_id == document.id)
        )
        == 0
    )

    response = FetchedUrl(
        data=b"# Restored\n\nFresh URL knowledge.",
        content_type="text/markdown",
        etag='"revision-2"',
        last_modified=None,
        not_modified=False,
    )
    await _ingest(db_session, kb_actors, document)

    await db_session.refresh(document)
    assert document.status == "ready"
    assert document.source_sync_status == "ready"
    assert document.content_md == "# Restored\n\nFresh URL knowledge."
    assert document.chunk_count > 0
    assert document.meta == {"etag": '"revision-2"'}
