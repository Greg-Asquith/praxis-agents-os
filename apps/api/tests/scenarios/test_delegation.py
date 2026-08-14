# apps/api/tests/scenarios/test_delegation.py

"""Parent/child runtime scenarios across delegated run boundaries."""

import json
from collections.abc import AsyncIterator

import pytest
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.database import set_session_tenant_context
from models.agent_memories import AgentMemory
from models.agent_run import AgentRun
from models.ai_usage_event import AIUsageEvent
from models.conversation import Conversation
from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL, RUN_TRIGGER_DELEGATED
from services.agents.runtime.entity_references.domain import AgentReference
from tests.support.scenario import (
    add_scenario_delegate,
    build_scenario_agent,
    run_scenario,
)


async def test_parent_delegates_to_child_run_and_receives_result(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = await build_scenario_agent(committed_db_session_factory)
    child = await add_scenario_delegate(committed_db_session_factory, context)
    async with committed_db_session_factory() as db:
        db.add(
            AgentMemory(
                workspace_id=context.workspace_id,
                scope="agent",
                agent_id=child.id,
                kind="core",
                memory_type="fact",
                title="Delegate-only context",
                content_md="Use the child agent's own memory.",
                importance=4,
                confidence=0.9,
                status="active",
                source="delegated",
                created_by="agent",
                created_by_user_id=context.user_id,
            )
        )
        await db.commit()
    child_requests: list[str] = []
    model = _delegation_model(
        child_id=str(child.id),
        seen_child_requests=child_requests,
    )
    monkeypatch.setattr("services.agents.runtime.loop.build_model", lambda _resolved: model)

    result = await run_scenario(committed_db_session_factory, context, model=model)

    assert result.output == "parent final"
    async with committed_db_session_factory() as db:
        await set_session_tenant_context(db, workspace_id=context.workspace_id)
        child_run = await db.scalar(
            select(AgentRun).where(AgentRun.parent_run_id == context.run_id)
        )
        assert child_run is not None
        assert child_run.status == "completed"
        assert child_run.trigger == RUN_TRIGGER_DELEGATED
        assert child_run.delegation_depth == 1
        child_conversation = await db.get(Conversation, child_run.conversation_id)
        assert child_conversation is not None
        assert child_conversation.source == "delegated"
        usage_events = (
            await db.scalars(
                select(AIUsageEvent).where(AIUsageEvent.run_id.in_([context.run_id, child_run.id]))
            )
        ).all()
        assert {event.run_id for event in usage_events} == {context.run_id, child_run.id}
        assert sum(event.requests for event in usage_events) == 4
    assert any("Delegate-only context" in request for request in child_requests)


async def test_child_approval_propagates_to_parent_suspension(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = await build_scenario_agent(
        committed_db_session_factory,
        trigger="scheduled",
        metadata={"envelope": {"side_effect_policy": "require_approval"}},
    )
    child = await add_scenario_delegate(
        committed_db_session_factory,
        context,
        tool_names=["scenario_external_write"],
    )
    model = _delegation_model(child_id=str(child.id), child_write=True)
    monkeypatch.setattr("services.agents.runtime.loop.build_model", lambda _resolved: model)

    result = await run_scenario(committed_db_session_factory, context, model=model)

    assert result.run.status == RUN_STATUS_AWAITING_APPROVAL
    approvals = [event.data for event in result.events if event.event == "tool.approval_required"]
    assert [(item["tool_call_id"], item["name"]) for item in approvals] == [
        ("child-write", "scenario_external_write")
    ]
    assert approvals[0]["delegation"]["parent_tool_call_id"] == "delegate-child"


def _delegation_model(
    *,
    child_id: str,
    child_write: bool = False,
    seen_child_requests: list[str] | None = None,
) -> FunctionModel:
    async def stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        names = {tool.name for tool in info.function_tools}
        if "list_delegate_agents" not in names:
            if seen_child_requests is not None:
                seen_child_requests.append(str(messages))
            if child_write and not _has_return(messages, "scenario_external_write"):
                yield {
                    0: DeltaToolCall(
                        name="scenario_external_write",
                        json_args=json.dumps({"value": "external"}),
                        tool_call_id="child-write",
                    )
                }
                return
            yield "child result"
            return
        if not _has_return(messages, "list_delegate_agents"):
            yield {
                0: DeltaToolCall(
                    name="list_delegate_agents", json_args="{}", tool_call_id="list-delegates"
                )
            }
            return
        if not _has_return(messages, "delegate_to_agent"):
            yield {
                0: DeltaToolCall(
                    name="delegate_to_agent",
                    json_args=json.dumps(
                        {
                            "agent_id": AgentReference(
                                entity_id=child_id,
                                label="Child Delegate",
                            ).model_dump(mode="json"),
                            "task": "Run the task.",
                        }
                    ),
                    tool_call_id="delegate-child",
                )
            }
            return
        yield "parent final"

    return FunctionModel(stream_function=stream, model_name="scenario-delegation")


def _has_return(messages: list[ModelMessage], tool_name: str) -> bool:
    return any(
        getattr(part, "part_kind", None) == "tool-return"
        and getattr(part, "tool_name", None) == tool_name
        for message in messages
        for part in message.parts
    )
