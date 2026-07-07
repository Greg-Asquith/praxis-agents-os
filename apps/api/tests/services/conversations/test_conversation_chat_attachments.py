"""Tests for chat attachment plumbing in conversation send paths."""

import importlib
from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import NotFoundError
from core.settings import settings
from models.agent import Agent
from models.agent_run import AgentRun
from models.conversation import Conversation
from models.files import FileReference
from services.agent_runs.domain import RUN_STATUS_COMPLETED
from services.conversations.create_conversation_stream import create_conversation_stream
from services.conversations.create_turn_stream import create_conversation_turn_stream
from services.conversations.schemas import ConversationCreateRequest, ConversationTurnCreateRequest
from services.files.contract import contract_for_content_type
from services.files.utils import private_ref_from_key, revision_object_key, sha256_hex
from services.storage.factory import get_storage_provider
from tests.factories import build_file, build_file_revision, build_user, build_workspace
from tests.support.storage import reset_storage_provider_cache

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


async def test_create_conversation_records_attachment_references_and_run_metadata(
    db_session: AsyncSession,
    local_storage_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_module = importlib.import_module("services.conversations.create_conversation_stream")

    actor, workspace, agent = await _persist_workspace_agent(db_session)
    file, _revision = await _persist_file(db_session, workspace=workspace, actor=actor)
    captured_worker: dict[str, object] = {}
    _patch_spawn(monkeypatch, create_module)

    def fake_initial_worker(**kwargs):
        captured_worker.update(kwargs)

        async def noop():
            return None

        return noop()

    monkeypatch.setattr(create_module, "_run_initial_conversation_worker", fake_initial_worker)

    await create_conversation_stream(
        db_session,
        actor=actor,
        workspace=workspace,
        payload=ConversationCreateRequest(
            agent_id=agent.id,
            user_prompt="Read this file",
            client_message_id="create-attachment",
            attachments=[file.id, file.id],
        ),
    )

    conversation = await db_session.scalar(
        select(Conversation).where(Conversation.active_agent_id == agent.id)
    )
    assert conversation is not None
    reference = await db_session.scalar(
        select(FileReference).where(
            FileReference.file_id == file.id,
            FileReference.target_type == "conversation",
            FileReference.target_id == conversation.id,
        )
    )
    assert reference is not None
    run = await db_session.scalar(
        select(AgentRun).where(AgentRun.conversation_id == conversation.id)
    )
    assert run is not None
    assert run.metadata_json["attachment_file_ids"] == [str(file.id)]
    assert captured_worker["attachment_file_ids"] == [file.id]


async def test_create_turn_references_attachments_idempotently(
    db_session: AsyncSession,
    local_storage_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    turn_module = importlib.import_module("services.conversations.create_turn_stream")

    actor, workspace, agent = await _persist_workspace_agent(db_session)
    conversation = Conversation(
        user_id=actor.id,
        workspace_id=workspace.id,
        created_by=actor.id,
        active_agent_id=agent.id,
        agent_slug=agent.slug,
    )
    db_session.add(conversation)
    await db_session.flush()
    file, _revision = await _persist_file(db_session, workspace=workspace, actor=actor)
    captured_worker: dict[str, object] = {}
    _patch_spawn(monkeypatch, turn_module)

    def fake_run_turn_worker(**kwargs):
        captured_worker.update(kwargs)

        async def noop():
            return None

        return noop()

    monkeypatch.setattr(turn_module, "run_turn_worker", fake_run_turn_worker)

    for client_message_id in ("turn-attachment-1", "turn-attachment-2"):
        await create_conversation_turn_stream(
            db_session,
            actor=actor,
            workspace=workspace,
            conversation_id=conversation.id,
            payload=ConversationTurnCreateRequest(
                user_prompt="Use this",
                client_message_id=client_message_id,
                attachments=[file.id],
            ),
        )
        active_runs = (
            await db_session.scalars(
                select(AgentRun).where(AgentRun.conversation_id == conversation.id)
            )
        ).all()
        for run in active_runs:
            run.status = RUN_STATUS_COMPLETED
        await db_session.flush()

    reference_count = await db_session.scalar(
        select(func.count())
        .select_from(FileReference)
        .where(
            FileReference.file_id == file.id,
            FileReference.target_type == "conversation",
            FileReference.target_id == conversation.id,
        )
    )
    assert reference_count == 1
    runs = (
        await db_session.scalars(
            select(AgentRun)
            .where(AgentRun.conversation_id == conversation.id)
            .order_by(AgentRun.id)
        )
    ).all()
    assert len(runs) == 2
    assert all(run.metadata_json["attachment_file_ids"] == [str(file.id)] for run in runs)
    assert captured_worker["attachment_file_ids"] == [file.id]


async def test_invalid_turn_attachment_fails_before_run_creation(
    db_session: AsyncSession,
    local_storage_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    turn_module = importlib.import_module("services.conversations.create_turn_stream")

    actor, workspace, agent = await _persist_workspace_agent(db_session)
    conversation = Conversation(
        user_id=actor.id,
        workspace_id=workspace.id,
        created_by=actor.id,
        active_agent_id=agent.id,
        agent_slug=agent.slug,
    )
    db_session.add(conversation)
    await db_session.flush()
    _patch_spawn(monkeypatch, turn_module)

    with pytest.raises(NotFoundError):
        await create_conversation_turn_stream(
            db_session,
            actor=actor,
            workspace=workspace,
            conversation_id=conversation.id,
            payload=ConversationTurnCreateRequest(
                user_prompt="Use this",
                client_message_id="invalid-attachment",
                attachments=[uuid4()],
            ),
        )

    run_count = await db_session.scalar(
        select(func.count())
        .select_from(AgentRun)
        .where(AgentRun.conversation_id == conversation.id)
    )
    assert run_count == 0


def _patch_spawn(monkeypatch: pytest.MonkeyPatch, module) -> None:
    def fake_spawn(_run_id, coro):
        coro.close()

    monkeypatch.setattr(module.run_task_registry, "spawn", fake_spawn)


async def _persist_workspace_agent(db: AsyncSession):
    actor = build_user(email=f"conversation-attachment-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"conversation-attachment-{uuid4().hex[:8]}")
    agent = Agent(
        name="Attachment Agent",
        slug=f"attachment-agent-{uuid4().hex[:8]}",
        instructions="Use attachments.",
        workspace_id=workspace.id,
        created_by=actor.id,
        model_provider="openai",
        model="gpt-5.4-mini",
    )
    db.add_all([actor, workspace, agent])
    await db.flush()
    return actor, workspace, agent


async def _persist_file(
    db: AsyncSession,
    *,
    workspace,
    actor,
    content_type: str = "text/plain",
    filename: str = "notes.txt",
    content: bytes = b"hello",
):
    entry = contract_for_content_type(content_type)
    content_hash = sha256_hex(content)
    file = build_file(
        workspace=workspace,
        name=filename,
        category=entry.category.value,
        content_type=entry.content_type,
        extension=entry.extensions[0],
        size_bytes=len(content),
        content_hash=content_hash,
    )
    db.add(file)
    await db.flush()
    revision_id = uuid4()
    object_key = revision_object_key(workspace.id, file.id, revision_id, entry.extensions[0])
    await get_storage_provider().put_object(
        private_ref_from_key(object_key),
        content,
        content_type=entry.content_type,
    )
    revision = build_file_revision(
        file,
        revision_id=revision_id,
        created_by_user_id=actor.id,
        object_key=object_key,
        size_bytes=len(content),
        content_hash=content_hash,
    )
    db.add(revision)
    await db.flush()
    file.current_revision_id = revision.id
    file.revision_count = 1
    await db.flush()
    return file, revision
