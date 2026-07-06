"""Tests for append-only file revision behavior."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import build_file, build_file_revision, build_user, build_workspace

pytestmark = pytest.mark.asyncio


async def _persist_revision(db_session: AsyncSession):
    workspace = build_workspace(slug=f"immutable-{uuid4().hex[:8]}")
    user = build_user(email=f"immutable-{uuid4().hex[:8]}@example.com")
    db_session.add_all([workspace, user])
    await db_session.flush()

    file = build_file(workspace=workspace)
    db_session.add(file)
    await db_session.flush()

    revision = build_file_revision(file, created_by_user_id=user.id)
    db_session.add(revision)
    await db_session.flush()
    return file, revision


@pytest.mark.parametrize(
    ("column_name", "value"),
    [
        ("content_hash", "b" * 64),
        ("object_key", "workspaces/changed/files/changed/revision.pdf"),
        ("size_bytes", 99),
        ("created_by_system", True),
    ],
)
async def test_file_revision_rejects_content_and_provenance_mutation(
    db_session: AsyncSession,
    column_name: str,
    value,
) -> None:
    _file, revision = await _persist_revision(db_session)

    setattr(revision, column_name, value)

    with pytest.raises(RuntimeError, match="File revisions are immutable"):
        await db_session.flush()


async def test_file_revision_allows_markdown_backfill_once(db_session: AsyncSession) -> None:
    _file, revision = await _persist_revision(db_session)

    revision.markdown_object_key = "workspaces/ws/files/file/revision.extracted.md"
    revision.markdown_size_bytes = 1024
    await db_session.flush()

    revision.markdown_object_key = "workspaces/ws/files/file/other.extracted.md"
    with pytest.raises(RuntimeError, match="already set"):
        await db_session.flush()


async def test_file_rows_remain_mutable(db_session: AsyncSession) -> None:
    file, _revision = await _persist_revision(db_session)

    file.content_hash = "c" * 64
    file.size_bytes = 42
    file.processing_status = "processing"
    await db_session.flush()

    assert file.content_hash == "c" * 64
    assert file.size_bytes == 42
