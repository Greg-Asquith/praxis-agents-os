# apps/api/tests/services/conversations/test_list_conversation_messages.py

"""Tests for paginated conversation message reads."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from models.conversation import Conversation, ConversationMessage
from services.conversations.list_messages import list_conversation_messages
from tests.factories import build_user, build_workspace, build_workspace_membership

pytestmark = pytest.mark.asyncio


async def test_list_conversation_messages_paginates_latest_messages(
    db_session: AsyncSession,
) -> None:
    actor = build_user(email=f"messages-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"messages-{uuid4().hex[:8]}")
    membership = build_workspace_membership(workspace_id=workspace.id, user_id=actor.id)
    conversation = Conversation(
        user_id=actor.id,
        workspace_id=workspace.id,
        created_by=actor.id,
    )
    db_session.add_all([actor, workspace, membership, conversation])
    await db_session.flush()
    _add_messages(db_session, conversation, count=30)
    await db_session.flush()

    first_page = await list_conversation_messages(
        db_session,
        actor=actor,
        workspace=workspace,
        conversation_id=conversation.id,
        limit=10,
    )

    assert [message.sequence for message in first_page.messages] == list(range(21, 31))
    assert first_page.total == 30
    assert first_page.has_more is True

    second_page = await list_conversation_messages(
        db_session,
        actor=actor,
        workspace=workspace,
        conversation_id=conversation.id,
        limit=10,
        before_sequence=21,
    )

    assert [message.sequence for message in second_page.messages] == list(range(11, 21))
    assert second_page.total == 30
    assert second_page.has_more is True

    final_page = await list_conversation_messages(
        db_session,
        actor=actor,
        workspace=workspace,
        conversation_id=conversation.id,
        limit=10,
        before_sequence=11,
    )

    assert [message.sequence for message in final_page.messages] == list(range(1, 11))
    assert final_page.total == 30
    assert final_page.has_more is False


def _add_messages(db: AsyncSession, conversation: Conversation, *, count: int) -> None:
    for sequence in range(1, count + 1):
        db.add(
            ConversationMessage(
                conversation_id=conversation.id,
                role="user",
                parts={"parts": [{"part_kind": "user-prompt", "content": str(sequence)}]},
                sequence=sequence,
            )
        )
