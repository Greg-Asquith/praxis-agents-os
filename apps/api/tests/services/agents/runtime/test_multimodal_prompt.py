"""Runtime tests for multimodal user-prompt assembly and persistence."""

import importlib
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from pydantic_ai.messages import (
    BinaryContent,
    ModelMessagesTypeAdapter,
    ModelRequest,
    UserPromptPart,
)
from pydantic_ai.models.test import TestModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.agent import Agent
from models.conversation import Conversation, ConversationMessage
from services.agent_runs import create_agent_run
from services.agent_runs.domain import RUN_TRIGGER_INTERACTIVE
from services.agents.runtime.execute_run import execute_run
from services.agents.runtime.persistence import load_message_history
from services.agents.runtime.sinks import CollectingSink
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


async def test_execute_run_persists_multimodal_user_prompt_round_trip(
    db_session: AsyncSession,
    local_storage_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = await _persist_runtime_context(db_session)
    actor = await db_session.get(Agent, context.agent_id)
    assert actor is not None
    file, _revision = await _persist_file(
        db_session,
        workspace_id=context.workspace_id,
        created_by_user_id=context.user_id,
        content_type="image/png",
        filename="screen.png",
        content=b"png",
    )
    sink = CollectingSink(run_id=context.run_id, conversation_id=context.conversation_id)

    result = await execute_run(
        db_session,
        conversation_id=context.conversation_id,
        run_id=context.run_id,
        user_prompt="What is in this image?",
        attachment_file_ids=[file.id],
        sink=sink,
        model=TestModel(call_tools=[]),
    )

    assert result.new_message_count == 2
    user_message = await db_session.scalar(
        select(ConversationMessage)
        .where(
            ConversationMessage.conversation_id == context.conversation_id,
            ConversationMessage.role == "user",
        )
        .order_by(ConversationMessage.sequence)
    )
    assert user_message is not None
    request = _stored_model_request(user_message)
    [prompt_part] = request.parts
    assert isinstance(prompt_part, UserPromptPart)
    assert isinstance(prompt_part.content, list)
    assert prompt_part.content[0] == "What is in this image?"
    binary = prompt_part.content[1]
    assert isinstance(binary, BinaryContent)
    assert binary.data == b"png"
    assert binary.media_type == "image/png"
    assert binary.identifier == str(file.id)

    class BrokenStorage:
        async def get_object(self, _ref):
            raise AssertionError("history replay must not read storage")

    builder_module = importlib.import_module("services.files.build_attachment_user_content")

    monkeypatch.setattr(builder_module, "get_storage_provider", lambda: BrokenStorage())
    history = await load_message_history(db_session, conversation_id=context.conversation_id)
    history_request = history[0]
    assert isinstance(history_request, ModelRequest)
    history_prompt = history_request.parts[0]
    assert isinstance(history_prompt, UserPromptPart)
    assert isinstance(history_prompt.content, list)
    history_binary = history_prompt.content[1]
    assert isinstance(history_binary, BinaryContent)
    assert history_binary.data == b"png"
    assert history_binary.identifier == str(file.id)


async def test_execute_run_text_only_prompt_stays_plain_string(
    db_session: AsyncSession,
) -> None:
    context = await _persist_runtime_context(db_session)
    sink = CollectingSink(run_id=context.run_id, conversation_id=context.conversation_id)

    await execute_run(
        db_session,
        conversation_id=context.conversation_id,
        run_id=context.run_id,
        user_prompt="Hello",
        sink=sink,
        model=TestModel(call_tools=[]),
    )

    user_message = await db_session.scalar(
        select(ConversationMessage)
        .where(
            ConversationMessage.conversation_id == context.conversation_id,
            ConversationMessage.role == "user",
        )
        .order_by(ConversationMessage.sequence)
    )
    assert user_message is not None
    request = _stored_model_request(user_message)
    [prompt_part] = request.parts
    assert isinstance(prompt_part, UserPromptPart)
    assert prompt_part.content == "Hello"


class RuntimeContext:
    def __init__(
        self,
        *,
        user_id: UUID,
        workspace_id: UUID,
        agent_id: UUID,
        conversation_id: UUID,
        run_id: UUID,
    ) -> None:
        self.user_id = user_id
        self.workspace_id = workspace_id
        self.agent_id = agent_id
        self.conversation_id = conversation_id
        self.run_id = run_id


def _stored_model_request(message: ConversationMessage) -> ModelRequest:
    [request] = ModelMessagesTypeAdapter.validate_python([message.parts])
    assert isinstance(request, ModelRequest)
    return request


async def _persist_runtime_context(db: AsyncSession) -> RuntimeContext:
    user = build_user(email=f"multimodal-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"multimodal-{uuid4().hex[:8]}")
    agent = Agent(
        name="Multimodal Agent",
        slug=f"multimodal-agent-{uuid4().hex[:8]}",
        instructions="Reply plainly.",
        workspace_id=workspace.id,
        created_by=user.id,
        model_provider="openai",
        model="gpt-5.4-mini",
    )
    db.add_all([user, workspace, agent])
    await db.flush()
    conversation = Conversation(
        user_id=user.id,
        workspace_id=workspace.id,
        created_by=user.id,
        active_agent_id=agent.id,
    )
    db.add(conversation)
    await db.flush()
    run = await create_agent_run(
        db,
        conversation_id=conversation.id,
        agent_id=agent.id,
        workspace_id=workspace.id,
        user_id=user.id,
        trigger=RUN_TRIGGER_INTERACTIVE,
    )
    return RuntimeContext(
        user_id=user.id,
        workspace_id=workspace.id,
        agent_id=agent.id,
        conversation_id=conversation.id,
        run_id=run.id,
    )


async def _persist_file(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    created_by_user_id: UUID,
    content_type: str,
    filename: str,
    content: bytes,
):
    workspace = build_workspace(workspace_id=workspace_id)
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
    object_key = revision_object_key(workspace_id, file.id, revision_id, entry.extensions[0])
    await get_storage_provider().put_object(
        private_ref_from_key(object_key),
        content,
        content_type=entry.content_type,
    )
    revision = build_file_revision(
        file,
        revision_id=revision_id,
        created_by_user_id=created_by_user_id,
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
