# apps/api/tests/services/conversations/test_conversation_schemas.py

"""Schema regression tests for conversation service contracts."""

from datetime import UTC, datetime
from uuid import uuid4

from models.conversation import Conversation
from services.conversations.schemas import ConversationRead


def test_conversation_read_validates_metadata_from_orm_attribute() -> None:
    """The public metadata alias must not read SQLAlchemy's MetaData registry."""
    now = datetime.now(UTC)
    conversation = Conversation(
        id=uuid4(),
        user_id=uuid4(),
        workspace_id=uuid4(),
        created_by=uuid4(),
        title="Research",
        status="active",
        metadata_json={"title_source": "generated"},
        unread=False,
        source="direct",
        visibility="private",
        created_at=now,
        updated_at=now,
    )

    read_model = ConversationRead.from_conversation(conversation)

    assert read_model.metadata_json == {"title_source": "generated"}
    assert read_model.capabilities.model_dump() == {
        "can_reply": False,
        "can_manage_sharing": False,
        "can_stop_sharing": False,
    }
    legacy_payload = read_model.model_dump(exclude={"capabilities", "access", "visibility"})
    assert ConversationRead.model_validate(legacy_payload).capabilities == read_model.capabilities
    assert read_model.agent_name is None
    assert read_model.active_run_id is None
    assert read_model.active_run_status is None
    assert read_model.needs_approval is False
    assert read_model.model_dump(by_alias=True)["metadata"] == {"title_source": "generated"}
