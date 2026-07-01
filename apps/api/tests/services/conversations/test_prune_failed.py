# apps/api/tests/services/conversations/test_prune_failed.py

"""Tests for pruning failed empty first conversations."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import Agent
from models.conversation import Conversation, ConversationMessage
from services.agent_runs import (
    complete_agent_run,
    create_agent_run,
    fail_agent_run,
    start_agent_run,
)
from services.conversations import prune_failed_empty_conversation_for_run
from tests.factories import build_user, build_workspace

pytestmark = pytest.mark.asyncio


async def _conversation_context(db: AsyncSession):
    user = build_user(email=f"prune-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"prune-{uuid4().hex[:8]}")
    db.add_all([user, workspace])
    await db.flush()

    agent = Agent(
        name="Prune Agent",
        slug=f"prune-agent-{uuid4().hex[:8]}",
        instructions="Reply plainly.",
        workspace_id=workspace.id,
        created_by=user.id,
    )
    db.add(agent)
    await db.flush()

    conversation = Conversation(
        user_id=user.id,
        workspace_id=workspace.id,
        created_by=user.id,
        active_agent_id=agent.id,
        source="direct",
    )
    db.add(conversation)
    await db.flush()

    run = await create_agent_run(
        db,
        conversation_id=conversation.id,
        agent_id=agent.id,
        workspace_id=workspace.id,
        user_id=user.id,
        trigger="interactive",
    )
    return user, workspace, agent, conversation, run


async def test_failed_first_run_with_zero_messages_prunes(
    db_session: AsyncSession,
) -> None:
    user, _workspace, _agent, conversation, run = await _conversation_context(db_session)
    await fail_agent_run(db_session, run, error_code="provider", error_message="boom")

    pruned = await prune_failed_empty_conversation_for_run(
        db_session,
        conversation_id=conversation.id,
        run_id=run.id,
        deleted_by_user_id=user.id,
    )

    assert pruned is True
    assert conversation.deleted is True
    assert conversation.deleted_by == user.id


async def test_failed_run_with_message_is_preserved(db_session: AsyncSession) -> None:
    user, _workspace, _agent, conversation, run = await _conversation_context(db_session)
    await fail_agent_run(db_session, run, error_code="provider", error_message="boom")
    db_session.add(
        ConversationMessage(
            conversation_id=conversation.id,
            role="user",
            parts={"kind": "request", "parts": []},
            sequence=1,
        )
    )
    await db_session.flush()

    pruned = await prune_failed_empty_conversation_for_run(
        db_session,
        conversation_id=conversation.id,
        run_id=run.id,
        deleted_by_user_id=user.id,
    )

    assert pruned is False
    assert conversation.deleted is False


async def test_completed_run_with_zero_messages_is_preserved(db_session: AsyncSession) -> None:
    user, _workspace, _agent, conversation, run = await _conversation_context(db_session)
    await start_agent_run(db_session, run)
    await complete_agent_run(db_session, run)

    pruned = await prune_failed_empty_conversation_for_run(
        db_session,
        conversation_id=conversation.id,
        run_id=run.id,
        deleted_by_user_id=user.id,
    )

    assert pruned is False
    assert conversation.deleted is False


async def test_failed_run_with_another_run_is_preserved(db_session: AsyncSession) -> None:
    user, workspace, agent, conversation, run = await _conversation_context(db_session)
    await fail_agent_run(db_session, run, error_code="provider", error_message="boom")
    await create_agent_run(
        db_session,
        conversation_id=conversation.id,
        agent_id=agent.id,
        workspace_id=workspace.id,
        user_id=user.id,
        trigger="interactive",
    )

    pruned = await prune_failed_empty_conversation_for_run(
        db_session,
        conversation_id=conversation.id,
        run_id=run.id,
        deleted_by_user_id=user.id,
    )

    assert pruned is False
    assert conversation.deleted is False
