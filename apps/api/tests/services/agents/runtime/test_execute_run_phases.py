# apps/api/tests/services/agents/runtime/test_execute_run_phases.py

"""Characterization tests for execute_run phase boundaries."""

import asyncio
import importlib
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.agent import Agent
from models.agent_run import AgentRun
from models.conversation import Conversation, ConversationMessage
from services.agent_runs import create_agent_run
from services.agent_runs.domain import (
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    RUN_STATUS_RUNNING,
    RUN_TRIGGER_INTERACTIVE,
)
from services.agents.runtime.events import EVENT_DONE, EVENT_ERROR, EVENT_RUN_STATUS
from services.agents.runtime.execute_run import execute_run
from services.agents.runtime.sinks import CollectingSink
from tests.factories import (
    build_user,
    build_workspace,
    build_workspace_membership,
)

pytestmark = pytest.mark.asyncio

execute_run_impl = importlib.import_module("services.agents.runtime.execute.execute_run")
finalize_module = importlib.import_module("services.agents.runtime.execute.finalize")


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


async def test_post_start_stream_failure_persists_failed_run_and_event_order(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    context = await _persist_runtime_context(db_session)
    sink = ClosingCollectingSink(run_id=context.run_id, conversation_id=context.conversation_id)
    sensitive_text = "sensitive-provider-token-post-start"
    monkeypatch.setattr(finalize_module.logger, "disabled", False)

    async def failing_stream(_messages: list[ModelMessage], _info: AgentInfo):
        raise RuntimeError(sensitive_text)
        yield "unreachable"

    with (
        caplog.at_level(
            logging.ERROR,
            logger=finalize_module.logger.name,
        ),
        pytest.raises(RuntimeError, match=sensitive_text),
    ):
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

    stored_run = await db_session.get(AgentRun, context.run_id, populate_existing=True)
    assert stored_run is not None
    assert stored_run.status == RUN_STATUS_FAILED
    assert stored_run.error_code == "agent_run_failed"
    assert stored_run.error_message == "The agent run failed unexpectedly."
    assert sensitive_text not in (stored_run.error_message or "")

    assert [event.event for event in sink.events] == [
        EVENT_RUN_STATUS,
        EVENT_RUN_STATUS,
        EVENT_ERROR,
        EVENT_DONE,
    ]
    assert sink.events[0].data["status"] == RUN_STATUS_RUNNING
    assert sink.events[1].data["status"] == RUN_STATUS_FAILED
    assert sink.events[2].data["code"] == "agent_run_failed"
    assert sink.events[2].data["message"] == "The agent run failed unexpectedly."
    assert sensitive_text not in str([event.data for event in sink.events])
    assert sink.events[-1].data["status"] == RUN_STATUS_FAILED
    assert sink.closed
    assert sensitive_text in caplog.text
    failure_record = next(
        record for record in caplog.records if record.getMessage() == "Agent run execution failed"
    )
    assert failure_record.agent_run_id == str(context.run_id)
    assert failure_record.run_started is True


async def test_pre_start_unknown_failure_uses_public_error_contract(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    context = await _persist_runtime_context(db_session)
    await db_session.commit()
    sink = ClosingCollectingSink(run_id=context.run_id, conversation_id=context.conversation_id)
    sensitive_text = "sensitive-database-dsn-pre-start"
    monkeypatch.setattr(finalize_module.logger, "disabled", False)

    def fail_validation(*_args, **_kwargs) -> None:
        raise RuntimeError(sensitive_text)

    monkeypatch.setattr(
        execute_run_impl,
        "validate_execution_preconditions",
        fail_validation,
    )

    with (
        caplog.at_level(
            logging.ERROR,
            logger=finalize_module.logger.name,
        ),
        pytest.raises(RuntimeError, match=sensitive_text),
    ):
        await execute_run(
            db_session,
            conversation_id=context.conversation_id,
            run_id=context.run_id,
            user_prompt="Hello",
            sink=sink,
            model=TestModel(call_tools=[]),
        )

    await db_session.rollback()
    stored_run = await db_session.get(AgentRun, context.run_id)
    assert stored_run is not None
    assert stored_run.error_code is None
    assert stored_run.error_message is None
    assert [event.event for event in sink.events] == [EVENT_ERROR, EVENT_DONE]
    assert sink.events[0].data["code"] == "agent_run_failed"
    assert sink.events[0].data["message"] == "The agent run failed unexpectedly."
    assert sensitive_text not in str([event.data for event in sink.events])
    assert sensitive_text in caplog.text
    failure_record = next(
        record for record in caplog.records if record.getMessage() == "Agent run execution failed"
    )
    assert failure_record.agent_run_id == str(context.run_id)
    assert failure_record.run_started is False
    assert sink.closed


async def test_shutdown_records_failure_without_claiming_human_cancellation(
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
                user_prompt="Record a truthful shutdown outcome",
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
        assert stored_run.status == RUN_STATUS_FAILED
        assert stored_run.error_code == "run_process_shutdown"

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
        RUN_STATUS_RUNNING,
        RUN_STATUS_FAILED,
    ]
    assert EVENT_DONE in [event.event for event in sink.events]
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
    membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=user.id,
    )
    agent = Agent(
        name="Execute Run Phase Agent",
        slug=f"execute-run-phase-agent-{uuid4().hex[:8]}",
        instructions="Reply plainly.",
        workspace_id=workspace.id,
        created_by=user.id,
        model_provider="openai",
        model="gpt-5.4-mini",
    )
    db.add_all([user, workspace, membership, agent])
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
