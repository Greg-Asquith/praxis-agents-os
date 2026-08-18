"""Concurrency coverage for folder membership changes."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.exceptions.general import NotFoundError
from models.agent import Agent
from models.audit_event import AuditEvent
from models.conversation import Conversation
from models.files import File, FileFolder, FileRevision
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.files import (
    create_folder as create_folder_service,
    ensure_conversation_folder as ensure_conversation_folder_service,
    move_files as move_files_service,
)
from services.files.create_folder import create_folder
from services.files.domain import FileFolderCreateRequest, FileMoveRequest
from services.files.ensure_conversation_folder import ensure_conversation_folder
from services.files.move_files import move_files
from tests.factories import (
    build_file,
    build_file_revision,
    build_user,
    build_workspace,
    build_workspace_membership,
)


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/files/move", "headers": []})


def _two_caller_barrier(original):
    callers = 0
    both_ready = asyncio.Event()

    async def coordinated(*args, **kwargs):
        nonlocal callers
        if callers < 2:
            callers += 1
            if callers == 2:
                both_ready.set()
            await both_ready.wait()
        return await original(*args, **kwargs)

    return coordinated


async def test_concurrent_same_name_folder_creation_retries_deterministically(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex
    user = build_user(email=f"same-folder-{suffix}@example.com")
    workspace = build_workspace(slug=f"same-folder-{suffix[:10]}")
    membership = build_workspace_membership(workspace_id=workspace.id, user_id=user.id)
    async with committed_db_session_factory() as setup_db:
        setup_db.add_all([user, workspace])
        await setup_db.flush()
        setup_db.add(membership)
        await setup_db.commit()

    create_module = __import__(create_folder_service.__module__, fromlist=["create_folder"])
    monkeypatch.setattr(
        create_module,
        "available_folder_name",
        _two_caller_barrier(create_module.available_folder_name),
    )

    async def create_one():
        async with committed_db_session_factory() as db:
            result = await create_folder(
                db,
                request=_request(),
                actor=user,
                workspace=workspace,
                membership=membership,
                payload=FileFolderCreateRequest(name="Shared"),
            )
            await db.commit()
            return result

    try:
        created = await asyncio.gather(create_one(), create_one())
        assert {folder.name for folder in created} == {"Shared", "Shared (2)"}
    finally:
        async with committed_db_session_factory() as cleanup_db:
            await cleanup_db.execute(
                delete(AuditEvent).where(AuditEvent.workspace_id == workspace.id)
            )
            await cleanup_db.execute(
                delete(FileFolder).where(FileFolder.workspace_id == workspace.id)
            )
            await cleanup_db.execute(
                delete(WorkspaceMembership).where(WorkspaceMembership.workspace_id == workspace.id)
            )
            await cleanup_db.execute(delete(Workspace).where(Workspace.id == workspace.id))
            await cleanup_db.execute(delete(User).where(User.id == user.id))
            await cleanup_db.commit()


async def test_concurrent_conversation_folder_creation_reuses_winner(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex
    user = build_user(email=f"conversation-folder-{suffix}@example.com")
    workspace = build_workspace(slug=f"conversation-folder-{suffix[:10]}")
    membership = build_workspace_membership(workspace_id=workspace.id, user_id=user.id)
    agent = Agent(
        name="Folder Agent",
        slug=f"folder-agent-{suffix[:10]}",
        instructions="Create files.",
        workspace_id=workspace.id,
        created_by=user.id,
        model_provider="openai",
        model="gpt-5.6-luna",
    )
    conversation = Conversation(
        user_id=user.id,
        workspace_id=workspace.id,
        created_by=user.id,
        active_agent_id=agent.id,
        title="Concurrent outputs",
    )
    async with committed_db_session_factory() as setup_db:
        setup_db.add_all([user, workspace])
        await setup_db.flush()
        setup_db.add_all([membership, agent])
        await setup_db.flush()
        setup_db.add(conversation)
        await setup_db.commit()

    ensure_module = __import__(
        ensure_conversation_folder_service.__module__,
        fromlist=["ensure_conversation_folder"],
    )
    monkeypatch.setattr(
        ensure_module,
        "available_folder_name",
        _two_caller_barrier(ensure_module.available_folder_name),
    )

    async def ensure_one():
        async with committed_db_session_factory() as db:
            folder = await ensure_conversation_folder(
                SimpleNamespace(
                    agent=agent,
                    conversation=conversation,
                    db=db,
                    user=user,
                    workspace=workspace,
                )
            )
            await db.commit()
            return folder.id

    try:
        folder_ids = await asyncio.gather(ensure_one(), ensure_one())
        assert folder_ids[0] == folder_ids[1]
        async with committed_db_session_factory() as verify_db:
            assert (
                len(
                    list(
                        await verify_db.scalars(
                            select(FileFolder).where(
                                FileFolder.workspace_id == workspace.id,
                                FileFolder.source_conversation_id == conversation.id,
                                FileFolder.deleted.is_(False),
                            )
                        )
                    )
                )
                == 1
            )
    finally:
        async with committed_db_session_factory() as cleanup_db:
            await cleanup_db.execute(
                delete(AuditEvent).where(AuditEvent.workspace_id == workspace.id)
            )
            await cleanup_db.execute(
                delete(FileFolder).where(FileFolder.workspace_id == workspace.id)
            )
            await cleanup_db.execute(delete(Conversation).where(Conversation.id == conversation.id))
            await cleanup_db.execute(delete(Agent).where(Agent.id == agent.id))
            await cleanup_db.execute(
                delete(WorkspaceMembership).where(WorkspaceMembership.workspace_id == workspace.id)
            )
            await cleanup_db.execute(delete(Workspace).where(Workspace.id == workspace.id))
            await cleanup_db.execute(delete(User).where(User.id == user.id))
            await cleanup_db.commit()


async def test_move_waits_for_target_folder_delete_and_then_fails_closed(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex
    user = build_user(email=f"folder-race-{suffix}@example.com")
    workspace = build_workspace(slug=f"folder-race-{suffix[:10]}")
    membership = build_workspace_membership(workspace_id=workspace.id, user_id=user.id)
    folder = FileFolder(
        workspace_id=workspace.id,
        name="Deleting target",
        created_by_user_id=user.id,
    )
    file = build_file(workspace=workspace, name="move-me.pdf")
    revision = build_file_revision(file, created_by_user_id=user.id)

    async with committed_db_session_factory() as setup_db:
        setup_db.add_all([user, workspace])
        await setup_db.flush()
        setup_db.add_all([membership, folder, file])
        await setup_db.flush()
        setup_db.add(revision)
        await setup_db.flush()
        file.current_revision_id = revision.id
        file.revision_count = 1
        await setup_db.commit()

    move_task: asyncio.Task[object] | None = None
    try:
        target_lock_requested = asyncio.Event()
        move_module = __import__(move_files_service.__module__, fromlist=["move_files"])
        original_get_folder = move_module.get_folder_for_workspace

        async def signal_target_lock(*args, **kwargs):
            target_lock_requested.set()
            return await original_get_folder(*args, **kwargs)

        monkeypatch.setattr(move_module, "get_folder_for_workspace", signal_target_lock)
        async with committed_db_session_factory() as delete_db:
            deleting_folder = await delete_db.scalar(
                select(FileFolder).where(FileFolder.id == folder.id).with_for_update()
            )
            assert deleting_folder is not None
            deleting_folder.soft_delete(deleted_by=user.id)
            await delete_db.flush()

            async def move_to_deleting_folder() -> object:
                async with committed_db_session_factory() as move_db:
                    result = await move_files(
                        move_db,
                        request=_request(),
                        actor=user,
                        workspace=workspace,
                        membership=membership,
                        payload=FileMoveRequest(file_ids=[file.id], folder_id=folder.id),
                    )
                    await move_db.commit()
                    return result

            move_task = asyncio.create_task(move_to_deleting_folder())
            await target_lock_requested.wait()
            assert not move_task.done()
            await delete_db.commit()

        with pytest.raises(NotFoundError, match="File folder not found"):
            await move_task

        async with committed_db_session_factory() as verify_db:
            persisted_file = await verify_db.get(File, file.id)
            assert persisted_file is not None
            assert persisted_file.folder_id is None
    finally:
        if move_task is not None and not move_task.done():
            move_task.cancel()
            await asyncio.gather(move_task, return_exceptions=True)
        async with committed_db_session_factory() as cleanup_db:
            persisted_file = await cleanup_db.get(File, file.id)
            if persisted_file is not None:
                persisted_file.current_revision_id = None
                await cleanup_db.flush()
            await cleanup_db.execute(delete(FileRevision).where(FileRevision.file_id == file.id))
            await cleanup_db.execute(delete(File).where(File.id == file.id))
            await cleanup_db.execute(delete(FileFolder).where(FileFolder.id == folder.id))
            await cleanup_db.execute(
                delete(WorkspaceMembership).where(WorkspaceMembership.workspace_id == workspace.id)
            )
            await cleanup_db.execute(delete(Workspace).where(Workspace.id == workspace.id))
            await cleanup_db.execute(delete(User).where(User.id == user.id))
            await cleanup_db.commit()
