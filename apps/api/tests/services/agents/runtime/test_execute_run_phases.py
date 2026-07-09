# apps/api/tests/services/agents/runtime/test_execute_run_phases.py

"""Characterization tests for execute_run phase boundaries."""

import asyncio
import importlib
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from pydantic_ai import DeferredToolResults
from pydantic_ai.messages import (
    BinaryContent,
    ModelMessage,
    ModelRequest,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.exceptions.general import ConflictError
from core.settings import settings
from models.agent import Agent
from models.agent_run import AgentRun
from models.conversation import Conversation, ConversationMessage
from services.agent_runs import create_agent_run
from services.agent_runs.domain import (
    RUN_STATUS_CANCELLED,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    RUN_STATUS_RUNNING,
    RUN_TRIGGER_INTERACTIVE,
)
from services.agents.runtime.cancellation import request_agent_run_task_cancel
from services.agents.runtime.events import EVENT_DONE, EVENT_ERROR, EVENT_RUN_STATUS
from services.agents.runtime.execute_run import execute_run
from services.agents.runtime.sinks import CollectingSink
from services.files.contract import contract_for_content_type
from services.files.utils import private_ref_from_key, revision_object_key, sha256_hex
from services.storage.factory import get_storage_provider
from tests.factories import build_file, build_file_revision, build_user, build_workspace
from tests.support.storage import reset_storage_provider_cache

pytestmark = pytest.mark.asyncio


@dataclass(frozen=True)
class RuntimeContext:
    user_id: UUID
    workspace_id: UUID
    agent_id: UUID
    conversation_id: UUID
    run_id: UUID


class ClosingCollectingSink(CollectingSink):
    """Collecting sink that records close calls."""

    def __init__(self, *, run_id: UUID, conversation_id: UUID):
        super().__init__(run_id=run_id, conversation_id=conversation_id)
        self.closed = False

    async def close(self) -> None:
        self.closed = True


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


async def test_pre_start_status_conflict_emits_error_and_done_without_run_status(
    db_session: AsyncSession,
) -> None:
    context = await _persist_runtime_context(db_session)
    sink = ClosingCollectingSink(run_id=context.run_id, conversation_id=context.conversation_id)

    with pytest.raises(ConflictError):
        await execute_run(
            db_session,
            conversation_id=context.conversation_id,
            run_id=context.run_id,
            user_prompt="Hello",
            sink=sink,
            model=TestModel(call_tools=[]),
            expected_status=RUN_STATUS_RUNNING,
        )

    event_names = [event.event for event in sink.events]
    assert event_names == [EVENT_ERROR, EVENT_DONE]
    assert EVENT_RUN_STATUS not in event_names
    assert sink.events[0].data["code"] == "ConflictError"
    assert sink.events[-1].data["status"] == RUN_STATUS_FAILED
    assert sink.closed


@pytest.mark.parametrize(
    ("user_prompt", "deferred_tool_results", "expected_message"),
    [
        (None, None, "needs a prompt or deferred tool results"),
        (
            None,
            DeferredToolResults(approvals={}),
            "needs rehydrated message history",
        ),
    ],
)
async def test_pre_start_precondition_conflicts_emit_error_and_done(
    db_session: AsyncSession,
    user_prompt,
    deferred_tool_results: DeferredToolResults | None,
    expected_message: str,
) -> None:
    context = await _persist_runtime_context(db_session)
    sink = ClosingCollectingSink(run_id=context.run_id, conversation_id=context.conversation_id)

    with pytest.raises(ConflictError, match=expected_message):
        await execute_run(
            db_session,
            conversation_id=context.conversation_id,
            run_id=context.run_id,
            user_prompt=user_prompt,
            sink=sink,
            model=TestModel(call_tools=[]),
            deferred_tool_results=deferred_tool_results,
        )

    assert [event.event for event in sink.events] == [EVENT_ERROR, EVENT_DONE]
    assert sink.closed


async def test_post_start_stream_failure_persists_failed_run_and_event_order(
    db_session: AsyncSession,
) -> None:
    context = await _persist_runtime_context(db_session)
    sink = ClosingCollectingSink(run_id=context.run_id, conversation_id=context.conversation_id)

    async def failing_stream(_messages: list[ModelMessage], _info: AgentInfo):
        raise RuntimeError("stream failed")
        yield "unreachable"

    with pytest.raises(RuntimeError, match="stream failed"):
        await execute_run(
            db_session,
            conversation_id=context.conversation_id,
            run_id=context.run_id,
            user_prompt="Hello",
            sink=sink,
            model=FunctionModel(
                stream_function=failing_stream,
                model_name="phase-failure",
            ),
        )
    await db_session.rollback()

    stored_run = await db_session.get(AgentRun, context.run_id)
    assert stored_run is not None
    assert stored_run.status == RUN_STATUS_FAILED
    assert stored_run.error_code == "RuntimeError"
    assert stored_run.error_message == "stream failed"

    assert [event.event for event in sink.events] == [
        EVENT_RUN_STATUS,
        EVENT_RUN_STATUS,
        EVENT_ERROR,
        EVENT_DONE,
    ]
    assert sink.events[0].data["status"] == RUN_STATUS_RUNNING
    assert sink.events[1].data["status"] == RUN_STATUS_FAILED
    assert sink.events[2].data["code"] == "RuntimeError"
    assert sink.events[-1].data["status"] == RUN_STATUS_FAILED
    assert sink.closed


async def test_cancelled_run_persists_cancelled_status_events_and_user_prompt(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with committed_db_session_factory() as db:
        context = await _persist_runtime_context(db)
        await db.commit()
        sink = ClosingCollectingSink(run_id=context.run_id, conversation_id=context.conversation_id)
        finalize_module = importlib.import_module("services.agents.runtime.execute.finalize")
        real_persist_cancelled_run = finalize_module.persist_cancelled_run

        async def slow_persist_cancelled_run(run_id: UUID):
            await asyncio.sleep(0.05)
            return await real_persist_cancelled_run(run_id)

        async def slow_stream(
            _messages: list[ModelMessage],
            _info: AgentInfo,
        ) -> AsyncIterator[str]:
            await asyncio.sleep(10)
            yield "too late"

        monkeypatch.setattr(finalize_module, "persist_cancelled_run", slow_persist_cancelled_run)

        task = asyncio.create_task(
            execute_run(
                db,
                conversation_id=context.conversation_id,
                run_id=context.run_id,
                user_prompt="Stop this run",
                sink=sink,
                model=FunctionModel(
                    stream_function=slow_stream,
                    model_name="phase-cancel",
                ),
                client_message_id="cancel-client",
            )
        )

        await _wait_for_status_event(sink, RUN_STATUS_RUNNING)
        request_agent_run_task_cancel(task, run_id=context.run_id)
        await asyncio.sleep(0.01)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

    async with committed_db_session_factory() as db:
        stored_run = await db.get(AgentRun, context.run_id)
        assert stored_run is not None
        assert stored_run.status == RUN_STATUS_CANCELLED

        messages = (
            await db.scalars(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == context.conversation_id)
                .order_by(ConversationMessage.sequence)
            )
        ).all()
    assert [(message.role, message.client_message_id) for message in messages] == [
        ("user", "cancel-client")
    ]
    assert messages[0].parts["parts"][0]["content"] == "Stop this run"

    assert [event.event for event in sink.events] == [
        EVENT_RUN_STATUS,
        EVENT_RUN_STATUS,
        EVENT_DONE,
    ]
    assert sink.events[0].data["status"] == RUN_STATUS_RUNNING
    assert sink.events[1].data["status"] == RUN_STATUS_CANCELLED
    assert sink.events[2].data["status"] == RUN_STATUS_CANCELLED
    assert EVENT_ERROR not in [event.event for event in sink.events]
    assert sink.closed


async def test_unmarked_task_cancellation_does_not_persist_cancelled_run(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with committed_db_session_factory() as db:
        context = await _persist_runtime_context(db)
        await db.commit()
        sink = ClosingCollectingSink(run_id=context.run_id, conversation_id=context.conversation_id)

        async def slow_stream(
            _messages: list[ModelMessage],
            _info: AgentInfo,
        ) -> AsyncIterator[str]:
            await asyncio.sleep(10)
            yield "too late"

        task = asyncio.create_task(
            execute_run(
                db,
                conversation_id=context.conversation_id,
                run_id=context.run_id,
                user_prompt="Worker shutdown should not cancel the run",
                sink=sink,
                model=FunctionModel(
                    stream_function=slow_stream,
                    model_name="phase-generic-cancel",
                ),
                client_message_id="generic-cancel-client",
            )
        )

        await _wait_for_status_event(sink, RUN_STATUS_RUNNING)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

    async with committed_db_session_factory() as db:
        stored_run = await db.get(AgentRun, context.run_id)
        assert stored_run is not None
        assert stored_run.status == RUN_STATUS_RUNNING

        messages = (
            await db.scalars(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == context.conversation_id)
                .order_by(ConversationMessage.sequence)
            )
        ).all()

    assert [(message.role, message.client_message_id) for message in messages] == [
        ("user", "generic-cancel-client")
    ]
    assert [event.data["status"] for event in sink.events if event.event == EVENT_RUN_STATUS] == [
        RUN_STATUS_RUNNING
    ]
    assert EVENT_DONE not in [event.event for event in sink.events]
    assert sink.closed


async def test_eager_persisted_interactive_prompt_is_not_replayed_as_history(
    db_session: AsyncSession,
) -> None:
    context = await _persist_runtime_context(db_session)
    seen_messages: list[ModelMessage] = []

    async def capture_prompt(
        messages: list[ModelMessage],
        _info: AgentInfo,
    ) -> AsyncIterator[str]:
        seen_messages[:] = messages
        yield "ok"

    result = await execute_run(
        db_session,
        conversation_id=context.conversation_id,
        run_id=context.run_id,
        user_prompt="Send this once",
        sink=ClosingCollectingSink(
            run_id=context.run_id,
            conversation_id=context.conversation_id,
        ),
        model=FunctionModel(
            stream_function=capture_prompt,
            model_name="prompt-history-capture",
        ),
        client_message_id="send-once",
    )

    assert result.run.status == RUN_STATUS_COMPLETED
    assert _user_prompt_contents(seen_messages) == ["Send this once"]

    stored_messages = (
        await db_session.scalars(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == context.conversation_id)
            .order_by(ConversationMessage.sequence)
        )
    ).all()
    assert [(message.role, message.client_message_id) for message in stored_messages] == [
        ("user", "send-once"),
        ("assistant", None),
    ]


async def test_attachment_prompt_promotes_string_to_multimodal_content(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    context = await _persist_runtime_context(db_session)
    file, _revision = await _persist_file(
        db_session,
        workspace_id=context.workspace_id,
        created_by_user_id=context.user_id,
        content_type="image/png",
        filename="screen.png",
        content=b"png",
    )
    seen_messages: list[ModelMessage] = []

    async def capture_prompt(
        messages: list[ModelMessage],
        _info: AgentInfo,
    ) -> AsyncIterator[str]:
        seen_messages[:] = messages
        yield "ok"

    result = await execute_run(
        db_session,
        conversation_id=context.conversation_id,
        run_id=context.run_id,
        user_prompt="Describe this",
        attachment_file_ids=[file.id],
        sink=ClosingCollectingSink(
            run_id=context.run_id,
            conversation_id=context.conversation_id,
        ),
        model=FunctionModel(
            stream_function=capture_prompt,
            model_name="prompt-capture",
        ),
    )

    assert result.run.status == RUN_STATUS_COMPLETED
    prompt_content = _last_user_prompt_content(seen_messages)
    assert isinstance(prompt_content, list)
    assert prompt_content[0] == "Describe this"
    attachment = prompt_content[1]
    assert isinstance(attachment, BinaryContent)
    assert attachment.data == b"png"
    assert attachment.media_type == "image/png"
    assert attachment.identifier == str(file.id)


async def test_sink_closes_on_success_and_failure(db_session: AsyncSession) -> None:
    success_context = await _persist_runtime_context(db_session)
    success_sink = ClosingCollectingSink(
        run_id=success_context.run_id,
        conversation_id=success_context.conversation_id,
    )

    await execute_run(
        db_session,
        conversation_id=success_context.conversation_id,
        run_id=success_context.run_id,
        user_prompt="Hello",
        sink=success_sink,
        model=TestModel(call_tools=[]),
    )

    failure_context = await _persist_runtime_context(db_session)
    failure_sink = ClosingCollectingSink(
        run_id=failure_context.run_id,
        conversation_id=failure_context.conversation_id,
    )
    with pytest.raises(ConflictError):
        await execute_run(
            db_session,
            conversation_id=failure_context.conversation_id,
            run_id=failure_context.run_id,
            user_prompt="Hello",
            sink=failure_sink,
            model=TestModel(call_tools=[]),
            expected_status=RUN_STATUS_RUNNING,
        )

    assert success_sink.closed
    assert failure_sink.closed


def _last_user_prompt_content(messages: list[ModelMessage]):
    for message in reversed(messages):
        if not isinstance(message, ModelRequest):
            continue
        for part in reversed(message.parts):
            if isinstance(part, UserPromptPart):
                return part.content
    raise AssertionError("No user prompt part was sent to the model")


def _user_prompt_contents(messages: list[ModelMessage]):
    return [
        part.content
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, UserPromptPart)
    ]


async def _wait_for_status_event(
    sink: ClosingCollectingSink,
    status: str,
    *,
    max_wait_seconds: float = 2.0,
) -> None:
    def observed() -> bool:
        return any(
            event.event == EVENT_RUN_STATUS and event.data.get("status") == status
            for event in sink.events
        )

    deadline = asyncio.get_running_loop().time() + max_wait_seconds
    while asyncio.get_running_loop().time() < deadline:
        if observed():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"Timed out waiting for run.status {status!r}")


async def _persist_runtime_context(db: AsyncSession) -> RuntimeContext:
    user = build_user(email=f"execute-run-phase-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"execute-run-phase-{uuid4().hex[:8]}")
    agent = Agent(
        name="Execute Run Phase Agent",
        slug=f"execute-run-phase-agent-{uuid4().hex[:8]}",
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
