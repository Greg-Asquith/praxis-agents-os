# apps/api/tests/services/agents/runtime/test_run_persistence_terminal.py

"""Tests for runtime persistence when a run was settled terminally mid-flight."""

from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.usage import RunUsage
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import Agent
from models.conversation import Conversation, ConversationMessage
from services.agent_runs import create_agent_run, fail_agent_run, start_agent_run
from services.agent_runs.domain import RUN_STATUS_FAILED
from services.agents.runtime.approval_state import APPROVAL_STATE_METADATA_KEY
from services.agents.runtime.run_persistence import persist_successful_run
from tests.factories import build_user, build_workspace, build_workspace_membership

pytestmark = pytest.mark.asyncio


@dataclass(frozen=True)
class RunContext:
    user_id: UUID
    workspace_id: UUID
    agent_id: UUID
    conversation_id: UUID


@pytest_asyncio.fixture
async def run_context(db_session: AsyncSession) -> RunContext:
    user = build_user(email=f"persist-terminal-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"persist-terminal-{uuid4().hex[:8]}")
    membership = build_workspace_membership(workspace_id=workspace.id, user_id=user.id)
    db_session.add_all([user, workspace, membership])
    await db_session.flush()

    agent = Agent(
        name="Persist Agent",
        slug=f"persist-agent-{uuid4().hex[:8]}",
        instructions="Reply.",
        workspace_id=workspace.id,
        created_by=user.id,
    )
    db_session.add(agent)
    await db_session.flush()

    conversation = Conversation(
        user_id=user.id,
        workspace_id=workspace.id,
        created_by=user.id,
        active_agent_id=agent.id,
    )
    db_session.add(conversation)
    await db_session.flush()

    return RunContext(
        user_id=user.id,
        workspace_id=workspace.id,
        agent_id=agent.id,
        conversation_id=conversation.id,
    )


async def test_persist_successful_run_keeps_messages_when_run_settled_terminally(
    db_session: AsyncSession,
    run_context: RunContext,
) -> None:
    run = await create_agent_run(
        db_session,
        conversation_id=run_context.conversation_id,
        agent_id=run_context.agent_id,
        workspace_id=run_context.workspace_id,
        user_id=run_context.user_id,
        trigger="interactive",
    )
    await start_agent_run(db_session, run)
    await fail_agent_run(db_session, run, error_code="run_abandoned", error_message="reaped")
    # Simulate a stale mid-run metadata write-back resurrecting the approval state.
    run.metadata_json = {APPROVAL_STATE_METADATA_KEY: {"message_history": ["stale"]}}
    await db_session.flush()

    terminal_result = SimpleNamespace(
        new_messages=lambda: [
            ModelRequest(parts=[UserPromptPart("do the thing")]),
            ModelResponse(parts=[TextPart("done")]),
        ],
        usage=RunUsage(),
    )
    persisted_run, message_count = await persist_successful_run(
        db_session,
        conversation_id=run_context.conversation_id,
        run_id=run.id,
        terminal_result=terminal_result,
        client_message_id=None,
    )

    assert message_count == 2
    assert persisted_run.status == RUN_STATUS_FAILED
    assert persisted_run.error_code == "run_abandoned"
    assert APPROVAL_STATE_METADATA_KEY not in (persisted_run.metadata_json or {})
    stored = await db_session.scalar(
        select(func.count())
        .select_from(ConversationMessage)
        .where(ConversationMessage.conversation_id == run_context.conversation_id)
    )
    assert stored == 2
