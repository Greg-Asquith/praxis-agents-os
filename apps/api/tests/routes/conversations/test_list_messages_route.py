# apps/api/tests/routes/conversations/test_list_messages_route.py

"""Route tests for conversation message listing."""

from uuid import uuid4

import pytest
from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from models.conversation import Conversation, ConversationMessage
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.support.auth import bearer_headers

pytestmark = pytest.mark.asyncio


async def test_list_messages_rejects_invalid_limits(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    conversation, headers = await _authenticated_conversation(db_session)

    too_small = await db_async_client.get(
        f"/api/v1/conversations/{conversation.id}/messages?limit=0",
        headers=headers,
    )
    too_large = await db_async_client.get(
        f"/api/v1/conversations/{conversation.id}/messages?limit=501",
        headers=headers,
    )

    assert too_small.status_code == 422
    assert too_large.status_code == 422


async def _authenticated_conversation(
    db: AsyncSession,
) -> tuple[Conversation, dict[str, str]]:
    user = build_user(email=f"route-messages-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"route-messages-{uuid4().hex[:8]}")
    membership = build_workspace_membership(workspace_id=workspace.id, user_id=user.id)
    conversation = Conversation(
        user_id=user.id,
        workspace_id=workspace.id,
        created_by=user.id,
    )
    db.add_all([user, workspace, membership, conversation])
    await db.flush()
    user.default_workspace_id = workspace.id
    db.add(
        ConversationMessage(
            conversation_id=conversation.id,
            role="user",
            parts={"parts": [{"part_kind": "user-prompt", "content": "hello"}]},
            sequence=1,
        )
    )
    session = await session_manager.create_session(db, str(user.id))
    await db.commit()
    return conversation, bearer_headers(session["session_token"])
