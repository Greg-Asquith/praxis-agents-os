# apps/api/tests/services/kb/test_create_document.py

"""Knowledge-base document creation tests."""

import asyncio
from datetime import datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.exceptions.general import AppValidationError, ConflictError, NotFoundError
from models.jobs import Job
from models.kb import KBDocument
from models.workspace import Workspace
from services.kb import create_kb_document, delete_kb_document
from services.kb.utils import compute_markdown_hash
from tests.factories import build_file, build_file_revision, build_workspace
from tests.services.kb.conftest import KBActors

pytestmark = pytest.mark.asyncio


async def _create_concurrent_duplicate(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    workspace_id: UUID,
) -> bool:
    async with session_factory() as db:
        try:
            await create_kb_document(
                db,
                workspace_id=workspace_id,
                source_type="manual",
                title="Concurrent handbook",
                content="The exact same concurrent content.",
            )
            await db.commit()
        except ConflictError:
            await db.rollback()
            return False
    return True


async def test_manual_create_stores_content_and_enqueues_ids_only_job(
    db_session: AsyncSession,
    kb_actors: KBActors,
) -> None:
    document = await create_kb_document(
        db_session,
        workspace_id=kb_actors.workspace.id,
        source_type="manual",
        title="  Handbook  ",
        created_by_user_id=kb_actors.user.id,
        content="# Handbook\n\nOperator guidance.",
    )

    assert document.title == "Handbook"
    assert document.content_hash == compute_markdown_hash(document.content_md or "")
    assert isinstance(document.source_updated_at, datetime)
    assert document.annotation_enabled is False
    job = await db_session.scalar(
        select(Job).where(Job.kind == "kb.ingest_document", Job.subject_id == document.id)
    )
    assert job is not None
    assert job.payload == {}
    assert job.initiated_by_user_id == kb_actors.user.id


async def test_concurrent_identical_creates_allow_exactly_one_document(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workspace = build_workspace(slug=f"kb-duplicate-{uuid4().hex[:8]}")
    async with committed_db_session_factory() as setup:
        setup.add(workspace)
        await setup.commit()
        workspace_id = workspace.id

    try:
        results = await asyncio.gather(
            _create_concurrent_duplicate(
                committed_db_session_factory,
                workspace_id=workspace_id,
            ),
            _create_concurrent_duplicate(
                committed_db_session_factory,
                workspace_id=workspace_id,
            ),
        )
        assert sorted(results) == [False, True]

        async with committed_db_session_factory() as verify:
            count = await verify.scalar(
                select(func.count(KBDocument.id)).where(
                    KBDocument.workspace_id == workspace_id,
                    KBDocument.deleted.is_(False),
                )
            )
            assert count == 1
    finally:
        async with committed_db_session_factory() as cleanup:
            await cleanup.execute(delete(Job).where(Job.workspace_id == workspace_id))
            await cleanup.execute(delete(KBDocument).where(KBDocument.workspace_id == workspace_id))
            await cleanup.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await cleanup.commit()


async def test_url_create_defers_fetch_and_supports_annotation_override(
    db_session: AsyncSession,
    kb_actors: KBActors,
) -> None:
    document = await create_kb_document(
        db_session,
        workspace_id=kb_actors.workspace.id,
        source_type="url",
        title="Remote guide",
        url="https://docs.example.com/guide",
        annotate=False,
    )

    assert document.external_url == "https://docs.example.com/guide"
    assert document.content_md is None
    assert document.source_updated_at is None
    assert document.annotation_enabled is False


async def test_upload_requires_revision_in_the_same_workspace(
    db_session: AsyncSession,
    kb_actors: KBActors,
) -> None:
    file = build_file(workspace=kb_actors.workspace)
    revision = build_file_revision(file)
    db_session.add_all([file, revision])
    await db_session.flush()

    document = await create_kb_document(
        db_session,
        workspace_id=kb_actors.workspace.id,
        source_type="upload",
        title="Uploaded guide",
        file_revision_id=revision.id,
    )
    assert document.file_revision_id == revision.id
    assert document.annotation_enabled is True

    other_workspace = build_workspace(slug=f"other-{uuid4().hex[:10]}")
    db_session.add(other_workspace)
    await db_session.flush()
    with pytest.raises(AppValidationError, match="this workspace"):
        await create_kb_document(
            db_session,
            workspace_id=other_workspace.id,
            source_type="upload",
            title="Cross-workspace",
            file_revision_id=revision.id,
        )


@pytest.mark.parametrize(
    ("source_type", "message"),
    [
        ("conversation", "document-source workflow"),
        ("integration", "provider source support"),
    ],
)
async def test_unavailable_source_producers_are_rejected_honestly(
    db_session: AsyncSession,
    kb_actors: KBActors,
    source_type: str,
    message: str,
) -> None:
    with pytest.raises(AppValidationError, match=message):
        await create_kb_document(
            db_session,
            workspace_id=kb_actors.workspace.id,
            source_type=source_type,
            title="Pending source",
        )


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "https://user:secret@example.com/a",
        "https://example.com:invalid/source",
        "nope",
    ],
)
async def test_invalid_urls_are_rejected_without_a_request(
    db_session: AsyncSession,
    kb_actors: KBActors,
    url: str,
) -> None:
    with pytest.raises(AppValidationError):
        await create_kb_document(
            db_session,
            workspace_id=kb_actors.workspace.id,
            source_type="url",
            title="Bad URL",
            url=url,
        )


async def test_delete_is_workspace_scoped_and_keeps_a_retained_tombstone(
    db_session: AsyncSession,
    kb_actors: KBActors,
) -> None:
    document = await create_kb_document(
        db_session,
        workspace_id=kb_actors.workspace.id,
        source_type="manual",
        title="Retained",
        content="Retain until the sweep.",
    )

    with pytest.raises(NotFoundError):
        await delete_kb_document(
            db_session,
            workspace_id=uuid4(),
            document_id=document.id,
            deleted_by=kb_actors.user.id,
        )

    await delete_kb_document(
        db_session,
        workspace_id=kb_actors.workspace.id,
        document_id=document.id,
        deleted_by=kb_actors.user.id,
    )
    assert document.deleted is True
    assert document.deleted_by == kb_actors.user.id
