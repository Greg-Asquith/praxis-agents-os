# apps/api/tests/services/agents/runtime/test_run_persistence.py

"""Tests for runtime persistence side effects that do not need a database."""

from pydantic_ai.usage import RunUsage

from models.agent_run import AgentRun
from models.conversation import Conversation
from services.agent_runs.domain import RUN_TRIGGER_INTERACTIVE, RUN_TRIGGER_SCHEDULED
from services.agents.runtime.run_persistence import (
    _mark_background_output_unread,
    usage_snapshot,
)


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


def test_usage_snapshot_preserves_cache_creation_tokens() -> None:
    snapshot = usage_snapshot(
        RunUsage(
            input_tokens=100,
            cache_read_tokens=40,
            cache_write_tokens=60,
            output_tokens=10,
            requests=2,
            tool_calls=1,
        )
    )

    assert snapshot.input_tokens_cached == 40
    assert snapshot.raw_json is not None
    assert snapshot.raw_json["cache_read_tokens"] == 40
    assert snapshot.raw_json["cache_write_tokens"] == 60
