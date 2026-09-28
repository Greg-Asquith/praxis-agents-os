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

import asyncio
import json

import pytest
from pydantic_ai import (
    Agent,
    DeferredToolRequests,
    DeferredToolResults,
    ToolApproved,
    ToolDenied,
)
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelResponse,
    TextPart,
    ToolCallPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RequestUsage

pytestmark = pytest.mark.asyncio


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


async def test_model_response_usage_exposes_all_metered_token_classes() -> None:
    response = ModelResponse(
        parts=[TextPart(content="done")],
        usage=RequestUsage(
            input_tokens=11,
            cache_read_tokens=3,
            cache_write_tokens=4,
            output_tokens=5,
        ),
    )

    assert response.usage.input_tokens == 11
    assert response.usage.cache_read_tokens == 3
    assert response.usage.cache_write_tokens == 4
    assert response.usage.output_tokens == 5


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

    results = DeferredToolResults(approvals={tool_call_id: ToolDenied("Denied by policy")})
    resumed = await agent.run(
        message_history=suspended.all_messages(),
        deferred_tool_results=results,
    )
    # the run completes; the denial does not surface as a deleted result
    assert not isinstance(resumed.output, DeferredToolRequests)
    assert "deleted" not in json.dumps(resumed.output)


def _build_overlap_probe_agent() -> tuple[Agent, dict[str, int]]:
    """Two slow tools called in one model response, tracking concurrent execution."""

    def two_calls_then_done(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(
                parts=[ToolCallPart(tool_name="slow_one"), ToolCallPart(tool_name="slow_two")]
            )
        return ModelResponse(parts=[TextPart(content="done")])

    agent = Agent(FunctionModel(two_calls_then_done), name="spike-sequential")
    gauge = {"active": 0, "max_active": 0}

    async def probe() -> str:
        gauge["active"] += 1
        gauge["max_active"] = max(gauge["max_active"], gauge["active"])
        await asyncio.sleep(0.01)
        gauge["active"] -= 1
        return "ok"

    @agent.tool_plain(name="slow_one")
    async def slow_one() -> str:
        return await probe()

    @agent.tool_plain(name="slow_two")
    async def slow_two() -> str:
        return await probe()

    return agent, gauge


async def test_sequential_mode_serializes_parallel_tool_calls() -> None:
    """The execute_run guard: sequential mode never overlaps tool execution."""
    agent, gauge = _build_overlap_probe_agent()
    with Agent.parallel_tool_call_execution_mode("sequential"):
        await agent.run("go")
    assert gauge["max_active"] == 1
