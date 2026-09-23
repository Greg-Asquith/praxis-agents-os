"""In-flight SDK history survives failed and cancelled stream consumption."""

import asyncio
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from pydantic_ai import Agent, DeferredToolRequests, DeferredToolResults
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel

from models.agent_run import AgentRun
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.execute.stream import consume_stream
from services.agents.runtime.sinks import CollectingSink


async def _consume(stream, messages, *, deferred_tool_results=None):
    run_id = uuid4()
    return await consume_stream(
        stream,
        deps=cast(RuntimeDeps, SimpleNamespace()),
        skills=(),
        run=cast(AgentRun, SimpleNamespace(id=run_id)),
        deferred_tool_results=deferred_tool_results,
        event_sink=CollectingSink(run_id=run_id, conversation_id=uuid4()),
        messages_so_far=messages,
    )


async def test_stream_captures_new_messages_without_prior_history() -> None:
    agent = Agent(TestModel(custom_output_text="Done."))
    history = [
        ModelRequest(parts=[UserPromptPart("Earlier prompt")], run_id="earlier"),
        ModelResponse(parts=[TextPart("Earlier reply")], run_id="earlier"),
    ]
    messages: list[ModelMessage] = []
    async with agent.run_stream_events("Continue", message_history=history) as stream:
        result, captured = await _consume(stream, messages)

    assert captured is messages
    assert messages == result.new_messages()
    assert len(messages) == 2
    assert messages[0].parts[0].content == "Continue"
    assert messages[1].parts[0].content == "Done."


async def test_stream_captures_partial_response_on_provider_failure() -> None:
    async def fail_after_text(_messages, _info):
        yield "Partial reply"
        raise RuntimeError("Provider failed")

    agent = Agent(FunctionModel(stream_function=fail_after_text))
    messages: list[ModelMessage] = []
    with pytest.raises(RuntimeError, match="Provider failed"):
        async with agent.run_stream_events("Continue") as stream:
            await _consume(stream, messages)

    assert len(messages) == 2
    response = messages[-1]
    assert isinstance(response, ModelResponse)
    assert response.parts[0].content == "Partial reply"
    assert response.state == "interrupted"
    assert response.run_id is not None
    assert response.timestamp is not None


@pytest.mark.parametrize("cancel", [False, True])
async def test_stream_captures_completed_return_before_later_tool_stops(cancel) -> None:
    second_started = asyncio.Event()
    agent = Agent(TestModel())

    @agent.tool_plain
    def first() -> str:
        return "Completed effect"

    @agent.tool_plain
    async def second() -> str:
        second_started.set()
        if cancel:
            await asyncio.Event().wait()
        raise RuntimeError("Later tool failed")

    messages: list[ModelMessage] = []

    async def run() -> None:
        with Agent.parallel_tool_call_execution_mode("sequential"):
            async with agent.run_stream_events("Run both tools") as stream:
                await _consume(stream, messages)

    task = asyncio.create_task(run())
    await asyncio.wait_for(second_started.wait(), timeout=3)
    if cancel:
        task.cancel("operator stop")
    with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
        await task

    returns = [
        part
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    assert any(part.tool_name == "first" and part.content == "Completed effect" for part in returns)
    assert messages[-1].state == "interrupted"


async def test_stream_captures_approved_return_when_resumed_model_fails() -> None:
    agent = Agent(TestModel(), output_type=str | DeferredToolRequests)

    @agent.tool_plain(requires_approval=True)
    def write() -> str:
        return "Saved the file"

    suspended = await agent.run("Save a file")
    assert isinstance(suspended.output, DeferredToolRequests)
    results = DeferredToolResults(
        approvals={call.tool_call_id: True for call in suspended.output.approvals}
    )

    async def fail(_messages, _info):
        raise RuntimeError("Resumed provider failed")
        yield ""

    messages: list[ModelMessage] = []
    with (
        agent.override(model=FunctionModel(stream_function=fail)),
        pytest.raises(RuntimeError, match="Resumed provider failed"),
    ):
        async with agent.run_stream_events(
            message_history=suspended.all_messages(), deferred_tool_results=results
        ) as stream:
            await _consume(stream, messages, deferred_tool_results=results)

    assert len(messages) == 2
    assert isinstance(messages[-1], ModelResponse)
    assert messages[-1].state == "interrupted"
    [returned] = messages[0].parts
    assert isinstance(returned, ToolReturnPart)
    assert returned.tool_name == "write"
    assert returned.content == "Saved the file"


async def test_stream_keeps_request_and_response_events_without_sdk_handle() -> None:
    request = ModelRequest(parts=[UserPromptPart("Continue")])
    response = ModelResponse(parts=[TextPart("Partial reply")])

    async def events():
        yield request
        yield response
        raise RuntimeError("Stream failed")

    messages: list[ModelMessage] = []
    with pytest.raises(RuntimeError, match="Stream failed"):
        await _consume(events(), messages)

    assert messages == [request, response]
