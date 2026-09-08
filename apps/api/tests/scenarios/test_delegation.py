# apps/api/tests/scenarios/test_delegation.py

"""Parent/child runtime scenarios across delegated run boundaries."""

import json
from collections.abc import AsyncIterator, Iterator

import pytest
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.database import set_session_tenant_context
from core.settings import settings
from models.agent_memories import AgentMemory
from models.agent_run import AgentRun
from models.ai_usage_event import AIUsageEvent
from models.conversation import Conversation, ConversationMessage
from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL, RUN_TRIGGER_DELEGATED
from services.agent_runs.schemas import AgentRunResumeDecision
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.code_mode.executor import close_code_mode_executor
from services.agents.runtime.code_mode.state import load_code_mode_state
from services.agents.runtime.entity_references.domain import AgentReference
from tests.support.delegation import ScenarioEffects, resume_scenario, scenario_effects
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    add_scenario_delegate,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)


@pytest.fixture
def effects() -> Iterator[ScenarioEffects]:
    with scenario_effects() as probe:
        yield probe


@pytest.fixture
async def code_mode_executor_cleanup() -> AsyncIterator[None]:
    try:
        yield
    finally:
        await close_code_mode_executor()


@pytest.mark.parametrize("specialist_count", [1, 2])
async def test_parent_delegates_to_child_run_and_receives_result(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    effects: ScenarioEffects,
    specialist_count: int,
) -> None:
    context = await build_scenario_agent(committed_db_session_factory)
    children = [
        await add_scenario_delegate(
            committed_db_session_factory, context, tool_names=[effects.name]
        )
        for _ in range(specialist_count)
    ]
    child = children[0]
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
        child_ids=[str(child.id) for child in children],
        write_tool=effects.name,
        seen_child_requests=child_requests,
    )
    monkeypatch.setattr("services.agents.runtime.loop.build_model", lambda _resolved: model)

    result = await run_scenario(committed_db_session_factory, context, model=model)

    assert result.output == "parent final"
    async with committed_db_session_factory() as db:
        await set_session_tenant_context(db, workspace_id=context.workspace_id)
        assert result.run.status == "completed"
        assert result.run.parent_run_id is None
        assert result.run.delegation_depth == 0
        assert [event.data["status"] for event in result.events if event.event == "done"] == [
            "completed"
        ]
        returns = result.tool_returns("delegate_to_agent")
        assert len(returns) == specialist_count
        assert all("child result" in str(part["content"]) for part in returns)
        child_runs = list(
            await db.scalars(
                select(AgentRun)
                .where(AgentRun.parent_run_id == context.run_id)
                .order_by(AgentRun.created_at)
            )
        )
        assert [run.agent_id for run in child_runs] == [child.id for child in children]
        assert effects.calls == [(run.id, "external") for run in child_runs]
        for child_run in child_runs:
            assert child_run.status == "completed"
            assert child_run.trigger == RUN_TRIGGER_DELEGATED
            assert child_run.delegation_depth == 1
            child_conversation = await db.get(Conversation, child_run.conversation_id)
            assert child_conversation.source == "delegated"
            child_messages = list(
                await db.scalars(
                    select(ConversationMessage).where(
                        ConversationMessage.conversation_id == child_run.conversation_id
                    )
                )
            )
            tool_returns = [
                part
                for message in child_messages
                for part in message.parts["parts"]
                if part.get("part_kind") == "tool-return" and part.get("tool_name") == effects.name
            ]
            assert [(part["tool_call_id"], part["content"]) for part in tool_returns] == [
                ("child-write", "external")
            ]
        runs = [result.run, *child_runs]
        usage_events = list(
            await db.scalars(
                select(AIUsageEvent).where(AIUsageEvent.run_id.in_([run.id for run in runs]))
            )
        )
        assert {
            (event.run_id, event.agent_id, event.conversation_id) for event in usage_events
        } == {(run.id, run.agent_id, run.conversation_id) for run in runs}
        assert (
            sum(event.requests for event in usage_events if event.run_id == context.run_id)
            == specialist_count + 2
        )
        for child_run in child_runs:
            assert (
                sum(event.requests for event in usage_events if event.run_id == child_run.id) == 2
            )
    assert any("Delegate-only context" in request for request in child_requests)


async def test_child_approval_then_parent_resume(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    effects: ScenarioEffects,
) -> None:
    context = await build_scenario_agent(
        committed_db_session_factory,
        trigger="scheduled",
        metadata={"envelope": {"side_effect_policy": "require_approval"}},
    )
    child = await add_scenario_delegate(
        committed_db_session_factory,
        context,
        tool_names=[effects.name],
    )
    model = _delegation_model(child_ids=[str(child.id)], write_tool=effects.name)
    monkeypatch.setattr("services.agents.runtime.loop.build_model", lambda _resolved: model)

    result = await run_scenario(committed_db_session_factory, context, model=model)

    assert result.run.status == RUN_STATUS_AWAITING_APPROVAL
    approvals = [event.data for event in result.events if event.event == "tool.approval_required"]
    assert [(item["tool_call_id"], item["name"]) for item in approvals] == [
        ("child-write", effects.name)
    ]
    assert approvals[0]["delegation"]["parent_tool_call_id"] == "delegate-child"

    assert effects.calls == []
    assert [event.data["status"] for event in result.events if event.event == "done"] == [
        "awaiting_approval"
    ]
    async with committed_db_session_factory() as db:
        [child_run] = list(
            await db.scalars(select(AgentRun).where(AgentRun.parent_run_id == context.run_id))
        )
        assert child_run.status == "awaiting_approval"
        assert load_suspended_run_state(child_run).pending_tool_call_ids == ["child-write"]
    resumed = await resume_scenario(
        committed_db_session_factory,
        context,
        model=model,
        decisions=[AgentRunResumeDecision(tool_call_id="child-write", decision="approved")],
    )
    assert resumed.run.status == "completed"
    assert resumed.run.parent_run_id is None
    assert resumed.output == "parent final"
    assert effects.calls == [(child_run.id, "external")]
    assert [event.data["status"] for event in resumed.events if event.event == "done"] == [
        "completed"
    ]
    [returned] = resumed.tool_returns("delegate_to_agent")
    assert "child result" in str(returned["content"])
    async with committed_db_session_factory() as db:
        child_run = await db.get(AgentRun, child_run.id)
        assert child_run.status == "completed"
        assert child_run.parent_run_id == context.run_id
        assert child_run.delegation_depth == 1
        child_messages = list(
            await db.scalars(
                select(ConversationMessage).where(
                    ConversationMessage.conversation_id == child_run.conversation_id
                )
            )
        )
        assert [
            (part["tool_call_id"], part["content"])
            for message in child_messages
            for part in message.parts["parts"]
            if part.get("part_kind") == "tool-return" and part.get("tool_name") == effects.name
        ] == [("child-write", "external")]
        usage_events = list(
            await db.scalars(
                select(AIUsageEvent).where(AIUsageEvent.run_id.in_([context.run_id, child_run.id]))
            )
        )
        assert {
            (event.run_id, event.agent_id, event.conversation_id) for event in usage_events
        } == {(run.id, run.agent_id, run.conversation_id) for run in [resumed.run, child_run]}
        assert sum(event.requests for event in usage_events if event.run_id == context.run_id) == 3
        assert sum(event.requests for event in usage_events if event.run_id == child_run.id) == 2


async def test_top_level_workflow_approval_restores_interpreter_and_completes(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    effects: ScenarioEffects,
    code_mode_executor_cleanup: None,
) -> None:
    context = await build_scenario_agent(
        committed_db_session_factory,
        tool_names=[effects.name],
        tool_policies={effects.name: "approval"},
        code_mode_enabled=True,
    )
    model = scripted_model(
        turns=[
            ToolTurn(
                (
                    ToolCall(
                        "run_workflow",
                        {
                            "code": f"value = 'retained'\nawait {effects.name}(value=value)\nvalue + ' result'",
                        },
                        "workflow-call",
                    ),
                )
            ),
            "workflow final",
        ]
    )
    suspended = await run_scenario(committed_db_session_factory, context, model=model)
    assert suspended.run.status == "awaiting_approval"
    assert effects.calls == []
    assert [event.data["status"] for event in suspended.events if event.event == "done"] == [
        "awaiting_approval"
    ]
    state = load_code_mode_state(
        suspended.run, snapshot_max_bytes=settings.AGENT_CODE_MODE_SNAPSHOT_MAX_BYTES
    )
    assert state.snapshot
    assert state.run_id == str(context.run_id)
    assert state.nested_call_id == "workflow-call:1"
    assert state.executed_effects == ()
    await close_code_mode_executor()
    resumed = await resume_scenario(
        committed_db_session_factory,
        context,
        model=model,
        decisions=[AgentRunResumeDecision(tool_call_id=state.nested_call_id, decision="approved")],
    )
    assert resumed.run.status == "completed"
    assert resumed.run.parent_run_id is None
    assert resumed.run.delegation_depth == 0
    assert resumed.output == "workflow final"
    assert effects.calls == [(context.run_id, "retained")]
    assert [event.data["status"] for event in resumed.events if event.event == "done"] == [
        "completed"
    ]
    [returned] = resumed.tool_returns("run_workflow")
    assert "retained result" in str(returned["content"])
    assert "code_mode_state" not in (resumed.run.metadata_json or {})
    async with committed_db_session_factory() as db:
        assert (
            list(await db.scalars(select(AgentRun).where(AgentRun.parent_run_id == context.run_id)))
            == []
        )
        events = list(
            await db.scalars(select(AIUsageEvent).where(AIUsageEvent.run_id == context.run_id))
        )
        assert {(event.agent_id, event.conversation_id) for event in events} == {
            (context.agent_id, context.conversation_id)
        }
        assert sum(event.requests for event in events) == 2


def _delegation_model(
    *,
    child_ids: list[str],
    write_tool: str,
    seen_child_requests: list[str] | None = None,
) -> FunctionModel:
    async def stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        names = {tool.name for tool in info.function_tools}
        if "list_delegate_agents" not in names:
            if seen_child_requests is not None:
                seen_child_requests.append(str(messages))
            if not _has_return(messages, write_tool):
                yield {
                    0: DeltaToolCall(
                        name=write_tool,
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
        completed_children = sum(
            getattr(part, "part_kind", None) == "tool-return"
            and getattr(part, "tool_name", None) == "delegate_to_agent"
            for message in messages
            for part in message.parts
        )
        if completed_children < len(child_ids):
            yield {
                0: DeltaToolCall(
                    name="delegate_to_agent",
                    json_args=json.dumps(
                        {
                            "agent_id": AgentReference(
                                entity_id=child_ids[completed_children],
                                label="Child Delegate",
                            ).model_dump(mode="json"),
                            "task": "Run the task.",
                        }
                    ),
                    tool_call_id="delegate-child"
                    if completed_children == 0
                    else f"delegate-child-{completed_children}",
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
