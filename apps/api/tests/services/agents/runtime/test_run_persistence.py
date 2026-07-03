# apps/api/tests/services/agents/runtime/test_run_persistence.py

"""Tests for runtime persistence side effects that do not need a database."""

from models.agent_run import AgentRun
from models.conversation import Conversation
from services.agent_runs.domain import RUN_TRIGGER_INTERACTIVE, RUN_TRIGGER_SCHEDULED
from services.agents.runtime.run_persistence import _mark_background_output_unread


def test_scheduled_output_marks_conversation_unread() -> None:
    conversation = Conversation(unread=False)
    run = AgentRun(trigger=RUN_TRIGGER_SCHEDULED)

    _mark_background_output_unread(run, conversation, persisted_messages_count=2)

    assert conversation.unread is True


def test_interactive_output_does_not_mark_conversation_unread() -> None:
    conversation = Conversation(unread=False)
    run = AgentRun(trigger=RUN_TRIGGER_INTERACTIVE)

    _mark_background_output_unread(run, conversation, persisted_messages_count=2)

    assert conversation.unread is False


def test_scheduled_run_without_new_messages_does_not_mark_conversation_unread() -> None:
    conversation = Conversation(unread=False)
    run = AgentRun(trigger=RUN_TRIGGER_SCHEDULED)

    _mark_background_output_unread(run, conversation, persisted_messages_count=0)

    assert conversation.unread is False
