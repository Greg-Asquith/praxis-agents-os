# apps/api/tests/conversations/test_conversation_schemas.py

"""Schema regression tests for conversation service contracts."""

from datetime import UTC, datetime
from uuid import uuid4

from models.conversation import Conversation, ConversationMessage
from services.conversations.schemas import ConversationMessageRead, ConversationRead


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
        created_at=now,
        updated_at=now,
    )

    read_model = ConversationRead.from_conversation(conversation)

    assert read_model.metadata_json == {"title_source": "generated"}
    assert read_model.agent_name is None
    assert read_model.active_run_id is None
    assert read_model.active_run_status is None
    assert read_model.needs_approval is False
    assert read_model.model_dump(by_alias=True)["metadata"] == {"title_source": "generated"}


def test_conversation_read_projection_sets_status_fields() -> None:
    now = datetime.now(UTC)
    active_run_id = uuid4()
    conversation = Conversation(
        id=uuid4(),
        user_id=uuid4(),
        workspace_id=uuid4(),
        created_by=uuid4(),
        title="Approvals",
        status="active",
        unread=True,
        source="direct",
        created_at=now,
        updated_at=now,
    )

    read_model = ConversationRead.from_projection(
        conversation,
        agent_name="Research Analyst",
        active_run_id=active_run_id,
        active_run_status="awaiting_approval",
    )

    assert read_model.agent_name == "Research Analyst"
    assert read_model.active_run_id == active_run_id
    assert read_model.active_run_status == "awaiting_approval"
    assert read_model.needs_approval is True


def test_conversation_message_read_uses_public_error_alias_only_on_output() -> None:
    now = datetime.now(UTC)
    message = ConversationMessage(
        id=uuid4(),
        conversation_id=uuid4(),
        role="tool",
        parts={"content": "Failed"},
        metadata_json={"source": "runtime"},
        error_json={"code": "tool_failed"},
        sequence=1,
        created_at=now,
        updated_at=now,
    )

    read_model = ConversationMessageRead.from_message(message)

    dumped = read_model.model_dump(by_alias=True)
    assert dumped["metadata"] == {"source": "runtime"}
    assert dumped["error"] == {"code": "tool_failed"}
