"""Database tests for file model invariants."""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import Agent
from models.files import FileReference, FileRevision, FileUpload
from tests.factories import (
    build_file,
    build_file_reference,
    build_file_revision,
    build_file_upload,
    build_user,
    build_workspace,
)

pytestmark = pytest.mark.asyncio


async def _workspace_and_user(db_session: AsyncSession, *, suffix: str):
    workspace = build_workspace(slug=f"files-{suffix}-{uuid4().hex[:8]}")
    user = build_user(email=f"files-{suffix}-{uuid4().hex[:8]}@example.com")
    db_session.add_all([workspace, user])
    await db_session.flush()
    return workspace, user


async def _file_with_revision(db_session: AsyncSession, *, suffix: str = "base"):
    workspace, user = await _workspace_and_user(db_session, suffix=suffix)
    file = build_file(workspace=workspace)
    db_session.add(file)
    await db_session.flush()
    revision = build_file_revision(file, created_by_user_id=user.id)
    db_session.add(revision)
    await db_session.flush()
    file.current_revision_id = revision.id
    file.revision_count = 1
    await db_session.flush()
    return workspace, user, file, revision


async def test_file_revision_requires_exactly_one_actor(db_session: AsyncSession) -> None:
    workspace, user = await _workspace_and_user(db_session, suffix="actor")
    agent = Agent(
        name="File Agent",
        slug=f"file-agent-{uuid4().hex[:8]}",
        description="Agent for file provenance tests.",
        instructions="Help with files.",
        workspace_id=workspace.id,
        created_by=user.id,
    )
    file = build_file(workspace=workspace)
    db_session.add_all([agent, file])
    await db_session.flush()

    db_session.add(build_file_revision(file, created_by_system=False))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()

    workspace, user = await _workspace_and_user(db_session, suffix="two-actor")
    agent = Agent(
        name="Two Actor Agent",
        slug=f"two-actor-agent-{uuid4().hex[:8]}",
        description="Agent for file provenance tests.",
        instructions="Help with files.",
        workspace_id=workspace.id,
        created_by=user.id,
    )
    file = build_file(workspace=workspace)
    db_session.add_all([agent, file])
    await db_session.flush()

    db_session.add(
        build_file_revision(
            file,
            created_by_user_id=user.id,
            created_by_agent_id=agent.id,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()

    workspace, user = await _workspace_and_user(db_session, suffix="single-user")
    file = build_file(workspace=workspace)
    db_session.add(file)
    await db_session.flush()
    db_session.add(build_file_revision(file, created_by_user_id=user.id))
    await db_session.flush()

    workspace, user = await _workspace_and_user(db_session, suffix="single-agent")
    agent = Agent(
        name="Single Actor Agent",
        slug=f"single-actor-agent-{uuid4().hex[:8]}",
        description="Agent for file provenance tests.",
        instructions="Help with files.",
        workspace_id=workspace.id,
        created_by=user.id,
    )
    file = build_file(workspace=workspace)
    db_session.add_all([agent, file])
    await db_session.flush()
    db_session.add(build_file_revision(file, created_by_agent_id=agent.id))
    await db_session.flush()

    workspace, _user = await _workspace_and_user(db_session, suffix="single-system")
    file = build_file(workspace=workspace)
    db_session.add(file)
    await db_session.flush()
    db_session.add(build_file_revision(file, created_by_system=True))
    await db_session.flush()


@pytest.mark.parametrize(
    ("revision_kind", "restored_from_revision_id", "should_raise"),
    [
        ("unknown", None, True),
        ("restore", None, True),
        ("create", uuid4(), True),
    ],
)
async def test_file_revision_kind_and_restore_constraints(
    db_session: AsyncSession,
    revision_kind: str,
    restored_from_revision_id,
    should_raise: bool,
) -> None:
    _workspace, user, file, _revision = await _file_with_revision(db_session, suffix=revision_kind)
    candidate = build_file_revision(
        file,
        revision_number=2,
        revision_kind=revision_kind,
        created_by_user_id=user.id,
        restored_from_revision_id=restored_from_revision_id,
    )
    db_session.add(candidate)

    if should_raise:
        with pytest.raises(IntegrityError):
            await db_session.flush()


async def test_duplicate_revision_number_is_rejected(db_session: AsyncSession) -> None:
    _workspace, user, file, _revision = await _file_with_revision(db_session, suffix="dupe-rev")
    db_session.add(build_file_revision(file, revision_number=1, created_by_user_id=user.id))

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_file_rejects_unknown_processing_status(db_session: AsyncSession) -> None:
    workspace, _user = await _workspace_and_user(db_session, suffix="bad-processing")
    db_session.add(build_file(workspace=workspace, processing_status="missing"))

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_file_reference_duplicate_target_is_rejected(db_session: AsyncSession) -> None:
    _workspace, user, file, revision = await _file_with_revision(db_session, suffix="ref-dupe")
    target_id = uuid4()
    db_session.add_all(
        [
            build_file_reference(
                file,
                target_id=target_id,
                file_revision_id=revision.id,
                created_by_user_id=user.id,
            ),
            build_file_reference(
                file,
                target_id=target_id,
                file_revision_id=revision.id,
                created_by_user_id=user.id,
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_file_upload_duplicate_object_key_is_rejected(db_session: AsyncSession) -> None:
    workspace, user = await _workspace_and_user(db_session, suffix="upload-dupe")
    object_key = f"workspaces/{workspace.id}/files/{uuid4()}/{uuid4()}.pdf"
    db_session.add_all(
        [
            build_file_upload(
                workspace=workspace, object_key=object_key, created_by_user_id=user.id
            ),
            build_file_upload(
                workspace=workspace, object_key=object_key, created_by_user_id=user.id
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_file_hard_delete_cascades_revisions_and_references(
    db_session: AsyncSession,
) -> None:
    _workspace, user, file, revision = await _file_with_revision(db_session, suffix="cascade")
    reference = build_file_reference(
        file,
        file_revision_id=revision.id,
        created_by_user_id=user.id,
    )
    db_session.add(reference)
    await db_session.flush()

    file_id = file.id
    revision_id = revision.id
    reference_id = reference.id
    await db_session.delete(file)
    await db_session.flush()

    assert (
        await db_session.scalar(select(FileRevision.id).where(FileRevision.id == revision_id))
        is None
    )
    assert (
        await db_session.scalar(select(FileReference.id).where(FileReference.id == reference_id))
        is None
    )
    assert await db_session.scalar(select(FileUpload).where(FileUpload.file_id == file_id)) is None
