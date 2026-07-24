# apps/api/tests/services/kb/test_document_sources.py

"""Knowledge-document source and lifecycle operations."""

from uuid import uuid4

import pytest
from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError, NotFoundError
from models.jobs import Job
from models.kb import KBChunk, KBDocument
from models.workspace import WorkspaceRole
from services.jobs.domain import JOB_STATUS_SUCCEEDED
from services.kb.documents import (
    create_document_from_file,
    create_document_from_url,
    create_manual_document,
    delete_document,
    reprocess_document,
    update_document,
)
from services.kb.schemas import (
    KBDocumentUpdateRequest,
    KBFileDocumentCreateRequest,
    KBManualDocumentCreateRequest,
    KBUrlDocumentCreateRequest,
)
from tests.factories import (
    build_file,
    build_file_revision,
    build_workspace,
    build_workspace_membership,
)
from tests.services.kb.conftest import KBActors


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/kb/documents", "headers": []})


async def _membership(db: AsyncSession, actors: KBActors):
    membership = build_workspace_membership(
        workspace_id=actors.workspace.id,
        user_id=actors.user.id,
        role=WorkspaceRole.MEMBER,
    )
    db.add(membership)
    await db.flush()
    return membership


async def test_sources_set_provenance_and_enqueue_ingestion(
    db_session: AsyncSession,
    kb_actors: KBActors,
) -> None:
    membership = await _membership(db_session, kb_actors)
    file = build_file(workspace=kb_actors.workspace, name="Runbook.pdf")
    revision = build_file_revision(file)
    db_session.add(file)
    await db_session.flush()
    db_session.add(revision)
    await db_session.flush()
    file.current_revision_id = revision.id
    await db_session.flush()

    manual = await create_manual_document(
        db_session,
        request=_request(),
        actor=kb_actors.user,
        workspace=kb_actors.workspace,
        membership=membership,
        payload=KBManualDocumentCreateRequest(
            title="Manual",
            content_md="Member-authored knowledge.",
        ),
    )
    remote = await create_document_from_url(
        db_session,
        request=_request(),
        actor=kb_actors.user,
        workspace=kb_actors.workspace,
        membership=membership,
        payload=KBUrlDocumentCreateRequest(
            title="Remote",
            url="https://example.com/guide",
        ),
    )
    uploaded = await create_document_from_file(
        db_session,
        request=_request(),
        actor=kb_actors.user,
        workspace=kb_actors.workspace,
        membership=membership,
        payload=KBFileDocumentCreateRequest(file_id=file.id),
    )

    rows = {
        row.id: row
        for row in (
            await db_session.scalars(
                select(KBDocument).where(KBDocument.id.in_([manual.id, remote.id, uploaded.id]))
            )
        ).all()
    }
    assert rows[manual.id].source_type == "manual"
    assert rows[manual.id].created_by_user_id == kb_actors.user.id
    assert rows[remote.id].source_type == "url"
    assert rows[remote.id].external_url == "https://example.com/guide"
    assert rows[uploaded.id].source_type == "upload"
    assert rows[uploaded.id].file_revision_id == revision.id
    assert rows[uploaded.id].title == file.name
    assert (
        await db_session.scalar(
            select(func.count(Job.id)).where(
                Job.kind == "kb.ingest_document",
                Job.subject_id.in_([manual.id, remote.id, uploaded.id]),
            )
        )
        == 3
    )


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1/private",
        "http://169.254.169.254/latest/meta-data",
        "http://localhost/private",
    ],
)
async def test_url_create_rejects_non_public_sources(
    db_session: AsyncSession,
    kb_actors: KBActors,
    url: str,
) -> None:
    membership = await _membership(db_session, kb_actors)
    with pytest.raises(AppValidationError):
        await create_document_from_url(
            db_session,
            request=_request(),
            actor=kb_actors.user,
            workspace=kb_actors.workspace,
            membership=membership,
            payload=KBUrlDocumentCreateRequest(title="Blocked", url=url),
        )


async def test_file_source_rejects_cross_workspace_file_as_not_found(
    db_session: AsyncSession,
    kb_actors: KBActors,
) -> None:
    membership = await _membership(db_session, kb_actors)
    other = build_workspace(slug=f"other-kb-{uuid4().hex[:8]}")
    db_session.add(other)
    await db_session.flush()
    file = build_file(workspace=other)
    revision = build_file_revision(file)
    db_session.add(file)
    await db_session.flush()
    db_session.add(revision)
    await db_session.flush()
    file.current_revision_id = revision.id
    await db_session.flush()

    with pytest.raises(NotFoundError):
        await create_document_from_file(
            db_session,
            request=_request(),
            actor=kb_actors.user,
            workspace=kb_actors.workspace,
            membership=membership,
            payload=KBFileDocumentCreateRequest(file_id=file.id),
        )


async def test_update_enforces_private_direction_and_manual_content_only(
    db_session: AsyncSession,
    kb_actors: KBActors,
) -> None:
    membership = await _membership(db_session, kb_actors)
    manual = await create_manual_document(
        db_session,
        request=_request(),
        actor=kb_actors.user,
        workspace=kb_actors.workspace,
        membership=membership,
        payload=KBManualDocumentCreateRequest(
            title="Private",
            content_md="Original content.",
            is_private=True,
        ),
    )
    with pytest.raises(AppValidationError, match="cannot be made workspace-shared"):
        await update_document(
            db_session,
            request=_request(),
            actor=kb_actors.user,
            workspace=kb_actors.workspace,
            membership=membership,
            document_id=manual.id,
            payload=KBDocumentUpdateRequest(is_private=False),
        )

    remote = await create_document_from_url(
        db_session,
        request=_request(),
        actor=kb_actors.user,
        workspace=kb_actors.workspace,
        membership=membership,
        payload=KBUrlDocumentCreateRequest(
            title="Remote",
            url="https://example.com/source",
        ),
    )
    with pytest.raises(AppValidationError, match="Only manual"):
        await update_document(
            db_session,
            request=_request(),
            actor=kb_actors.user,
            workspace=kb_actors.workspace,
            membership=membership,
            document_id=remote.id,
            payload=KBDocumentUpdateRequest(content_md="Replacement"),
        )


async def test_delete_removes_chunks_and_reprocess_enqueues_fresh_job(
    db_session: AsyncSession,
    kb_actors: KBActors,
) -> None:
    membership = await _membership(db_session, kb_actors)
    first = await create_manual_document(
        db_session,
        request=_request(),
        actor=kb_actors.user,
        workspace=kb_actors.workspace,
        membership=membership,
        payload=KBManualDocumentCreateRequest(title="Delete", content_md="Delete content."),
    )
    document = await db_session.get(KBDocument, first.id)
    assert document is not None
    chunk = KBChunk(
        document_id=document.id,
        workspace_id=document.workspace_id,
        chunk_index=0,
        content="Delete content.",
        char_start=0,
        char_end=15,
        token_estimate=4,
        meta={},
    )
    db_session.add(chunk)
    document.chunk_count = 1
    await db_session.flush()

    await delete_document(
        db_session,
        request=_request(),
        actor=kb_actors.user,
        workspace=kb_actors.workspace,
        membership=membership,
        document_id=document.id,
    )
    assert document.deleted is True
    assert (
        await db_session.scalar(
            select(func.count(KBChunk.id)).where(KBChunk.document_id == document.id)
        )
        == 0
    )

    retry = await create_manual_document(
        db_session,
        request=_request(),
        actor=kb_actors.user,
        workspace=kb_actors.workspace,
        membership=membership,
        payload=KBManualDocumentCreateRequest(title="Retry", content_md="Retry content."),
    )
    retry_document = await db_session.get(KBDocument, retry.id)
    assert retry_document is not None
    original_job = await db_session.scalar(
        select(Job).where(Job.kind == "kb.ingest_document", Job.subject_id == retry.id)
    )
    assert original_job is not None
    original_job.status = JOB_STATUS_SUCCEEDED
    retry_document.status = "error"
    retry_document.processing_error = "temporary"
    await db_session.flush()

    result = await reprocess_document(
        db_session,
        request=_request(),
        actor=kb_actors.user,
        workspace=kb_actors.workspace,
        membership=membership,
        document_id=retry.id,
    )
    assert result.status == "pending"
    assert result.processing_error is None
    assert (
        await db_session.scalar(
            select(func.count(Job.id)).where(
                Job.kind == "kb.ingest_document",
                Job.subject_id == retry.id,
            )
        )
        == 2
    )
