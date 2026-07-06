"""Tests for workspace file markdown extraction jobs."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from services.files.utils import private_ref_from_key, revision_object_key
from services.jobs.handlers.extract_file_markdown import extract_file_markdown
from tests.factories import build_file, build_file_revision, build_job, build_workspace
from tests.support.storage import reset_storage_provider_cache
from utils.document_markdown import TRUNCATION_MARKER, DocumentConversionError

pytestmark = pytest.mark.asyncio


@pytest.fixture
def local_storage_settings(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "APP_BASE_URL", "http://testserver")
    reset_storage_provider_cache()
    try:
        yield
    finally:
        reset_storage_provider_cache()


async def _persist_pdf_file(
    db: AsyncSession,
    *,
    text: str = "Hello Praxis",
    processing_status: str = "pending",
):
    from services.storage.factory import get_storage_provider

    workspace = build_workspace(slug=f"extract-{uuid4().hex[:8]}")
    file = build_file(
        workspace=workspace,
        name="report.pdf",
        content_type="application/pdf",
        extension=".pdf",
        processing_status=processing_status,
    )
    db.add(workspace)
    await db.flush()
    db.add(file)
    await db.flush()

    revision_id = uuid4()
    object_key = revision_object_key(workspace.id, file.id, revision_id, ".pdf")
    pdf_bytes = _tiny_pdf(text)
    await get_storage_provider().put_object(
        private_ref_from_key(object_key),
        pdf_bytes,
        content_type="application/pdf",
    )
    revision = build_file_revision(
        file,
        revision_id=revision_id,
        created_by_system=True,
        object_key=object_key,
        content_type="application/pdf",
        extension=".pdf",
        size_bytes=len(pdf_bytes),
    )
    db.add(revision)
    await db.flush()
    file.current_revision_id = revision.id
    file.revision_count = 1
    file.size_bytes = revision.size_bytes
    await db.flush()
    job = build_job(
        kind="files.extract",
        workspace_id=workspace.id,
        subject_type="file_revision",
        subject_id=revision.id,
        payload={"file_id": str(file.id), "revision_id": str(revision.id)},
        content_hash=revision.content_hash,
    )
    return workspace, file, revision, job


async def test_extract_file_markdown_stores_markdown_and_marks_file_ready(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    from services.storage.factory import get_storage_provider

    _workspace, file, revision, job = await _persist_pdf_file(db_session)

    await extract_file_markdown(db_session, job)
    await db_session.refresh(file)
    await db_session.refresh(revision)

    assert file.processing_status == "ready"
    assert file.processing_error is None
    assert file.processing_attempts == 1
    assert revision.markdown_object_key is not None
    assert revision.markdown_object_key.endswith(".extracted.md")
    markdown = await get_storage_provider().get_object(
        private_ref_from_key(revision.markdown_object_key)
    )
    assert b"Hello Praxis" in markdown
    assert revision.markdown_size_bytes == len(markdown)


async def test_extract_file_markdown_truncates_and_is_idempotent(
    db_session: AsyncSession,
    local_storage_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.storage.factory import get_storage_provider

    long_text = " ".join(["Praxis"] * 100)
    _workspace, _file, revision, job = await _persist_pdf_file(db_session, text=long_text)
    monkeypatch.setattr(settings, "FILES_MAX_MARKDOWN_BYTES", 90)

    await extract_file_markdown(db_session, job)
    await db_session.refresh(revision)
    assert revision.markdown_object_key is not None
    markdown = (
        await get_storage_provider().get_object(private_ref_from_key(revision.markdown_object_key))
    ).decode()
    assert markdown.endswith(TRUNCATION_MARKER)
    assert len(markdown.encode()) <= 90

    async def fail_put(*_args, **_kwargs):
        raise AssertionError("idempotent extraction should not rewrite markdown")

    monkeypatch.setattr(get_storage_provider(), "put_object", fail_put)
    await extract_file_markdown(db_session, job)


async def test_extract_file_markdown_does_not_clobber_newer_current_revision(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    _workspace, file, old_revision, job = await _persist_pdf_file(db_session)
    new_revision = build_file_revision(
        file,
        revision_number=2,
        revision_kind="replace",
        created_by_system=True,
        content_hash="b" * 64,
        object_key=revision_object_key(file.workspace_id, file.id, uuid4(), ".pdf"),
    )
    db_session.add(new_revision)
    await db_session.flush()
    file.current_revision_id = new_revision.id
    file.revision_count = 2
    file.processing_status = "ready"
    await db_session.flush()

    await extract_file_markdown(db_session, job)
    await db_session.refresh(file)
    await db_session.refresh(old_revision)

    assert old_revision.markdown_object_key is not None
    assert file.current_revision_id == new_revision.id
    assert file.processing_status == "ready"


async def test_extract_file_markdown_skips_deleted_files(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    _workspace, file, revision, job = await _persist_pdf_file(db_session)
    file.soft_delete()
    await db_session.flush()

    await extract_file_markdown(db_session, job)
    await db_session.refresh(revision)

    assert revision.markdown_object_key is None


async def test_extract_file_markdown_restore_fast_path_copies_source_markdown(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    _workspace, file, source, _old_job = await _persist_pdf_file(db_session)
    source.markdown_object_key = "workspaces/example/source.extracted.md"
    source.markdown_size_bytes = 12
    restore_revision = build_file_revision(
        file,
        revision_number=2,
        revision_kind="restore",
        created_by_system=True,
        restored_from_revision_id=source.id,
        object_key=source.object_key,
    )
    db_session.add(restore_revision)
    await db_session.flush()
    file.current_revision_id = restore_revision.id
    file.revision_count = 2
    file.processing_status = "pending"
    await db_session.flush()
    job = build_job(
        kind="files.extract",
        workspace_id=file.workspace_id,
        payload={"file_id": str(file.id), "revision_id": str(restore_revision.id)},
    )

    await extract_file_markdown(db_session, job)
    await db_session.refresh(file)
    await db_session.refresh(restore_revision)

    assert restore_revision.markdown_object_key == source.markdown_object_key
    assert restore_revision.markdown_size_bytes == source.markdown_size_bytes
    assert file.processing_status == "ready"


async def test_extract_file_markdown_failure_marks_current_file_error(
    db_session: AsyncSession,
    local_storage_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.jobs.handlers.extract_file_markdown as extract_module

    _workspace, file, _revision, job = await _persist_pdf_file(db_session)

    async def fail_convert(*_args, **_kwargs):
        raise DocumentConversionError("very noisy conversion failure")

    monkeypatch.setattr(extract_module, "convert_document_to_markdown", fail_convert)

    with pytest.raises(DocumentConversionError):
        await extract_file_markdown(db_session, job)

    await db_session.refresh(file)
    assert file.processing_status == "error"
    assert file.processing_attempts == 1
    assert file.processing_error == "very noisy conversion failure"


def _tiny_pdf(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 50 100 Td ({escaped}) Tj ET".encode()
    return (
        b"%PDF-1.1\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 200]"
        b"/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
        + f"4 0 obj<</Length {len(stream)}>>stream\n".encode()
        + stream
        + b"\nendstream endobj\n"
        b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
        b"trailer<</Root 1 0 R>>\n%%EOF\n"
    )
