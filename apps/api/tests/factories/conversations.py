# apps/api/tests/factories/conversations.py

"""Conversation model factories for tests."""

from uuid import uuid4

from models.conversation import Conversation
from models.user import User
from models.workspace import Workspace


def build_conversation(
    *,
    user: User,
    workspace: Workspace,
    **overrides,
) -> Conversation:
    defaults = {
        "id": uuid4(),
        "user_id": user.id,
        "workspace_id": workspace.id,
        "created_by": user.id,
        "title": "Test conversation",
        "source": "direct",
    }
    defaults.update(overrides)
    return Conversation(**defaults)
