# apps/api/tests/services/agents/runtime/test_pydantic_ai_spike.py

"""Pydantic AI dependency + serialization spike.

Build-sequence step 1 from docs/architecture/agent-runtime.md: prove the dependency
and the serialization shape before any runtime abstraction sits on top of them.

These tests are deterministic and provider-free (TestModel only), so they run in CI
without a database or model credentials. They pin the behaviours the runtime design
depends on against the installed pydantic-ai version (currently 2.1.0):

- message history round-trips byte-stable through ModelMessagesTypeAdapter and stays
  storable per-row in ConversationMessage.parts;
- both agent.iter() and agent.run_stream_events() surface the full multi-step loop,
  including tool calls (run_stream_events is the SSE driver of record);
- requires_approval tools suspend into DeferredToolRequests and resume via
  DeferredToolResults (the durable human-in-the-loop primitive);
- ALLOW_MODEL_REQUESTS=False does not break TestModel-based tests.
"""

import json

import pytest
from pydantic_ai import (
    Agent,
    DeferredToolRequests,
    DeferredToolResults,
    ToolApproved,
    ToolDenied,
    models as pai_models,
)
from pydantic_ai.messages import ModelMessagesTypeAdapter
from pydantic_ai.models.test import TestModel

pytestmark = pytest.mark.asyncio

# Stream event_kind discriminators the SSE sink translator depends on (07-streaming.md).
EXPECTED_EVENT_KINDS = {
    "part_start",
    "part_delta",
    "part_end",
    "final_result",
    "function_tool_call",
    "function_tool_result",
    "agent_run_result",
}


def _build_tool_agent() -> Agent:
    """An agent with one plain tool; TestModel exercises the tool then answers."""
    agent = Agent(TestModel(), name="spike")

    @agent.tool_plain
    def add(a: int, b: int) -> int:
        return a + b

    return agent


def _build_approval_agent() -> Agent:
    """An agent whose only tool always needs approval, with a deferred output branch."""
    agent = Agent(TestModel(), name="spike-approval", output_type=[str, DeferredToolRequests])

    @agent.tool_plain(requires_approval=True)
    def delete_thing(name: str) -> str:
        return f"deleted {name}"

    return agent


async def test_message_history_round_trips_byte_stable() -> None:
    """all_messages() -> JSON -> back is byte-stable and re-feedable as history."""
    agent = _build_tool_agent()
    result = await agent.run("compute something")

    messages = result.all_messages()
    blob = ModelMessagesTypeAdapter.dump_json(messages)
    stored = json.loads(blob)  # the shape we persist into JSONB

    rebuilt = ModelMessagesTypeAdapter.validate_python(stored)
    assert ModelMessagesTypeAdapter.dump_json(rebuilt) == blob

    # Rehydrated history is accepted by a continuation run.
    continued = await agent.run("and again", message_history=rebuilt)
    assert continued.new_messages()


async def test_serialized_messages_are_storable_per_row() -> None:
    """Each ModelMessage carries a kind discriminator + parts -> one ConversationMessage row each."""
    agent = _build_tool_agent()
    result = await agent.run("compute something")

    stored = json.loads(ModelMessagesTypeAdapter.dump_json(result.all_messages()))
    assert isinstance(stored, list)
    for message in stored:
        assert message["kind"] in {"request", "response"}
        assert isinstance(message["parts"], list)
        # round-trips through json again -> safe for a JSONB column
        assert json.loads(json.dumps(message)) == message


async def test_usage_is_a_property_not_a_method() -> None:
    """AgentRunResult.usage is a RunUsage property in 2.1.0 (docs flagged it as .usage())."""
    agent = _build_tool_agent()
    result = await agent.run("compute something")

    usage = result.usage
    assert not callable(usage)
    assert usage.requests >= 1
    assert usage.tool_calls >= 1
    # run identity is built into the result (relevant to the agent_runs table decision)
    assert result.run_id
    assert result.conversation_id


async def test_iter_driver_surfaces_tool_calls_and_output() -> None:
    """agent.iter() exposes node boundaries and per-node event streams across the full loop."""
    agent = _build_tool_agent()

    node_names: list[str] = []
    event_kinds: set[str] = set()

    async with agent.iter("compute something") as run:
        async for node in run:
            node_names.append(type(node).__name__)
            if Agent.is_model_request_node(node) or Agent.is_call_tools_node(node):
                async with node.stream(run.ctx) as stream:
                    async for event in stream:
                        event_kinds.add(event.event_kind)
        output = run.result.output

    assert "CallToolsNode" in node_names
    assert "End" in node_names
    # the tool round-trip is observable, not hidden behind the final output
    assert {"function_tool_call", "function_tool_result"} <= event_kinds
    assert output is not None


async def test_run_stream_events_surfaces_full_loop_and_terminal_result() -> None:
    """run_stream_events() is the SSE driver: a flat stream of every event + a terminal result.

    This resolves the iter()-vs-run_stream_events() question: run_stream_events does NOT
    hide post-output tool calls (that was a run_stream limitation, a different method).
    """
    agent = _build_tool_agent()

    async with agent.run_stream_events("compute something") as stream:
        event_kinds = [event.event_kind async for event in stream]

    seen = set(event_kinds)
    assert {"function_tool_call", "function_tool_result", "final_result"} <= seen
    assert seen <= EXPECTED_EVENT_KINDS
    # the stream ends with a single terminal result event carrying the run outcome
    assert event_kinds[-1] == "agent_run_result"


async def test_requires_approval_suspends_with_deferred_requests() -> None:
    """A requires_approval tool yields DeferredToolRequests instead of running."""
    agent = _build_approval_agent()
    result = await agent.run("delete the widget")

    assert isinstance(result.output, DeferredToolRequests)
    assert len(result.output.approvals) == 1
    approval = result.output.approvals[0]
    assert approval.tool_name == "delete_thing"
    assert approval.tool_call_id  # the durable correlation key for resume


async def test_deferred_results_resume_approved_path() -> None:
    """Resuming with ToolApproved continues the run and produces a final output."""
    agent = _build_approval_agent()
    suspended = await agent.run("delete the widget")
    tool_call_id = suspended.output.approvals[0].tool_call_id

    results = DeferredToolResults(approvals={tool_call_id: ToolApproved()})
    resumed = await agent.run(
        message_history=suspended.all_messages(),
        deferred_tool_results=results,
    )
    assert not isinstance(resumed.output, DeferredToolRequests)
    assert "deleted" in json.dumps(resumed.output)


async def test_deferred_results_resume_denied_path() -> None:
    """Resuming with ToolDenied feeds the model a typed denial rather than a result."""
    agent = _build_approval_agent()
    suspended = await agent.run("delete the widget")
    tool_call_id = suspended.output.approvals[0].tool_call_id

    results = DeferredToolResults(
        approvals={tool_call_id: ToolDenied("Denied by policy")}
    )
    resumed = await agent.run(
        message_history=suspended.all_messages(),
        deferred_tool_results=results,
    )
    # the run completes; the denial does not surface as a deleted result
    assert not isinstance(resumed.output, DeferredToolRequests)
    assert "deleted" not in json.dumps(resumed.output)


async def test_test_model_runs_under_allow_model_requests_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ALLOW_MODEL_REQUESTS=False (the CI guard) must not block TestModel-based tests."""
    monkeypatch.setattr(pai_models, "ALLOW_MODEL_REQUESTS", False)
    agent = _build_tool_agent()
    result = await agent.run("compute something")
    assert result.output is not None
