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
from models.agent import Agent
from models.agent_memories import AgentMemory
from models.agent_run import AgentRun
from models.ai_usage_event import AIUsageEvent
from models.conversation import Conversation, ConversationMessage
from services.agent_runs.continuation_state import AgentRunResumeRequiresRecoveryError
from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL, RUN_TRIGGER_DELEGATED
from services.agent_runs.schemas import AgentRunResumeDecision
from services.agents.runtime.approval_projection import build_approval_graph, project_approval_graph
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.code_mode.executor import close_code_mode_executor
from services.agents.runtime.code_mode.state import load_code_mode_state
from services.agents.runtime.entity_references.domain import AgentReference
from services.agents.runtime.usage_limits import EFFECTIVE_USAGE_LIMITS_KEY, BudgetLimitExceeded
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
@pytest.mark.parametrize("unbounded_tokens", [False, True])
async def test_parent_delegates_to_child_run_and_receives_result(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    effects: ScenarioEffects,
    specialist_count: int,
    unbounded_tokens: bool,
) -> None:
    if unbounded_tokens:
        monkeypatch.setattr(settings, "AGENT_RUN_TOTAL_TOKENS_LIMIT", None)
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
    assert (
        result.run.metadata_json[EFFECTIVE_USAGE_LIMITS_KEY]["limits"]["total_tokens_limit"]
        == settings.AGENT_RUN_TOTAL_TOKENS_LIMIT
    )
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


@pytest.mark.parametrize("revocation", [None, "depth", "permission"])
async def test_child_approval_then_parent_resume(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    effects: ScenarioEffects,
    revocation: str | None,
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
    seen_requests: list[str] = []
    model = _delegation_model(
        child_ids=[str(child.id)], write_tool=effects.name, seen_requests=seen_requests
    )
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
        projection = project_approval_graph(
            build_approval_graph(result.run, {child_run.id: child_run})
        )
        [pending] = projection.approvals
        assert pending.owner_run_id == child_run.id
        assert pending.root_run_id == result.run.id
        assert pending.tool_call_id == "child-write"
        assert pending.approval_id is not None
        assert load_suspended_run_state(child_run).approval_batch_id is not None
        assert approvals[0]["approval_id"] == str(pending.approval_id)
    if revocation == "depth":
        monkeypatch.setattr(settings, "AGENT_MAX_DELEGATION_DEPTH", 0)
    elif revocation == "permission":
        async with committed_db_session_factory() as db:
            parent_agent = await db.get(Agent, context.agent_id)
            parent_agent.allowed_agent_ids = []
            await db.commit()
    if revocation is not None:
        request_count = len(seen_requests)
        with pytest.raises(AgentRunResumeRequiresRecoveryError):
            await resume_scenario(
                committed_db_session_factory,
                context,
                model=model,
                decisions=[AgentRunResumeDecision(tool_call_id="child-write", decision="approved")],
            )
        assert effects.calls == []
        assert len(seen_requests) == request_count
        async with committed_db_session_factory() as db:
            root = await db.get(AgentRun, context.run_id)
            saved_child = await db.get(AgentRun, child_run.id)
            assert root.status == "failed"
            assert root.outcome == "blocked"
            assert root.error_code == "agent_run_resume_requires_recovery"
            assert saved_child.status == "failed"
        return
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
    projection = project_approval_graph(build_approval_graph(suspended.run, {}))
    [pending] = projection.approvals
    assert pending.tool_call_id == state.nested_call_id
    assert pending.parent_tool_call_id == "workflow-call"
    assert pending.owner_run_id == context.run_id
    assert pending.args == {"value": "retained"}
    assert projection.workflow == projection.workflows[0]
    assert "snapshot_b64" not in projection.model_dump_json()
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
    seen_requests: list[str] | None = None,
    workflow_code: str | None = None,
) -> FunctionModel:
    async def stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        if seen_requests is not None:
            seen_requests.append(str(messages))
        names = {tool.name for tool in info.function_tools}
        if "list_delegate_agents" not in names:
            if seen_child_requests is not None:
                seen_child_requests.append(str(messages))
            if workflow_code is not None and not _has_return(messages, "run_workflow"):
                yield {
                    0: DeltaToolCall(
                        name="run_workflow",
                        json_args=json.dumps({"code": workflow_code}),
                        tool_call_id="child-workflow",
                    )
                }
                return
            if workflow_code is None and not _has_return(messages, write_tool):
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


@pytest.mark.parametrize("attempt", ["suspension", "success", "failure"])
async def test_reaped_child_propagates_durable_failure_without_approval(
    committed_db_session_factory, monkeypatch, effects, attempt
):
    import importlib
    from datetime import UTC, datetime, timedelta

    from services.agent_runs.reap_abandoned import reap_abandoned_runs

    execution = importlib.import_module("services.agents.runtime.execute.execute_run")
    context = await build_scenario_agent(committed_db_session_factory)
    child = await add_scenario_delegate(
        committed_db_session_factory,
        context,
        tool_names=[effects.name],
    )
    if attempt == "suspension":
        async with committed_db_session_factory() as db:
            saved_child = await db.get(type(child), child.id)
            saved_child.tool_policies = {effects.name: "approval"}
            await db.commit()
    model = _delegation_model(child_ids=[str(child.id)], write_tool=effects.name)
    child_model = scripted_model(turns=[]) if attempt == "failure" else model
    monkeypatch.setattr("services.agents.runtime.loop.build_model", lambda _resolved: child_model)
    boundary = "emit_failure_events" if attempt == "failure" else "finalize_terminal_run"
    finalisation = (
        importlib.import_module("services.agents.runtime.execute.settle_failure")
        if attempt == "failure"
        else execution
    )
    original = getattr(finalisation, boundary)
    winning_error = None

    async def reap_before_finalisation(db, **kwargs):
        nonlocal winning_error
        run_id = kwargs.get("run_id") or kwargs["run"].id
        if run_id != context.run_id:
            await db.commit()
            async with committed_db_session_factory() as remote:
                run = await remote.get(AgentRun, run_id)
                run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
                await remote.flush()
                await reap_abandoned_runs(remote, run_id=run_id)
                await remote.commit()
                winning_error = run.error_message
        return await original(db, **kwargs)

    monkeypatch.setattr(finalisation, boundary, reap_before_finalisation)
    result = await run_scenario(committed_db_session_factory, context, model=model)
    assert result.run.status == "completed"
    [returned] = result.tool_returns("delegate_to_agent")
    assert winning_error in str(returned["content"])
    assert "failed" in str(returned["content"])
    assert not any(event.event == "tool.approval_required" for event in result.events)
    if attempt == "suspension":
        assert effects.calls == []


async def test_parent_timeout_does_not_charge_uncommitted_child_usage_to_parent_model(
    committed_db_session_factory, monkeypatch, effects, caplog
):
    import asyncio
    import importlib

    from services.agents.runtime.execute.bounded_finalisation import bounded_finalisation
    from services.ai_usage.record_in_transaction import record_ai_usage_in_transaction
    from tests.support.scenario import ScenarioBarrier

    execution = importlib.import_module("services.agents.runtime.execute.execute_run")
    context = await build_scenario_agent(committed_db_session_factory)
    child = await add_scenario_delegate(
        committed_db_session_factory, context, tool_names=[effects.name]
    )
    async with committed_db_session_factory() as db:
        saved_child = await db.get(type(child), child.id)
        saved_child.model = "gemini-3.8-flash"
        saved_child.model_provider = "google"
        await db.commit()
    model = _delegation_model(child_ids=[str(child.id)], write_tool=effects.name)
    monkeypatch.setattr("services.agents.runtime.loop.build_model", lambda _resolved: model)
    monkeypatch.setattr(execution, "CANCEL_FINALIZE_TIMEOUT", 0.25)
    barrier = ScenarioBarrier()
    captured = []

    async def blocked_child_insert(db, event):
        recorded = await record_ai_usage_in_transaction(db, event)
        if event.agent_id == child.id:
            captured.append(event)
            commit = db.commit

            async def blocked_commit():
                await barrier.pause()
                await commit()

            monkeypatch.setattr(db, "commit", blocked_commit)
        return recorded

    monkeypatch.setattr(
        "services.agents.runtime.run_persistence.record_ai_usage_in_transaction",
        blocked_child_insert,
    )
    monkeypatch.setattr(
        "services.agents.runtime.execute.finalize.record_ai_usage_in_transaction",
        blocked_child_insert,
    )
    monkeypatch.setattr(
        "services.ai_usage.record_agent_run_fallback.record_ai_usage_in_transaction",
        blocked_child_insert,
    )

    timeout_scope = asyncio.timeout(None)

    async def timed_parent():
        async with timeout_scope:
            await run_scenario(committed_db_session_factory, context, model=model)

    async with barrier.running(timed_parent()) as task:
        await asyncio.wait_for(barrier.reached.wait(), timeout=3)
        timeout_scope.reschedule(asyncio.get_running_loop().time())
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(task, timeout=2)
        assert captured
        assert all(event == captured[0] for event in captured)
        incomplete = [
            record
            for record in caplog.records
            if record.message == "Agent run accounting incomplete"
        ]
        assert incomplete
        assert any(
            record.invocation_id == captured[0].details["invocation_id"]
            and record.provider == captured[0].provider
            and record.model == captured[0].model
            and record.requests == captured[0].requests
            for record in incomplete
        )
        assert not [
            task for task in asyncio.all_tasks() if task.get_name() == "agent-run-finalisation"
        ]
        async with committed_db_session_factory() as db:
            [parent_event] = list(
                await db.scalars(select(AIUsageEvent).where(AIUsageEvent.run_id == context.run_id))
            )
            assert parent_event.requests == 2
            assert parent_event.provider != captured[0].provider
            assert not list(
                await db.scalars(
                    select(AIUsageEvent).where(AIUsageEvent.run_id == captured[0].run_id)
                )
            )

    async def delayed_settlement():
        async with committed_db_session_factory() as db:
            assert await record_ai_usage_in_transaction(db, captured[0])
            assert await record_ai_usage_in_transaction(db, captured[0])
            await db.commit()

    assert await bounded_finalisation(delayed_settlement(), max_wait=1)
    async with committed_db_session_factory() as db:
        rows = list(
            await db.scalars(
                select(AIUsageEvent).where(
                    AIUsageEvent.run_id.in_([context.run_id, captured[0].run_id])
                )
            )
        )
        assert len(rows) == 2
        assert sum(row.requests for row in rows) == 4
        assert captured[0].provider == "google"


async def test_reaped_resumed_child_does_not_propagate_another_approval(
    committed_db_session_factory, monkeypatch, effects
):
    import importlib

    from services.agent_runs import fail_agent_run

    execution = importlib.import_module("services.agents.runtime.execute.execute_run")
    context = await build_scenario_agent(
        committed_db_session_factory,
        trigger="scheduled",
        metadata={"envelope": {"side_effect_policy": "require_approval"}},
    )
    child = await add_scenario_delegate(
        committed_db_session_factory, context, tool_names=[effects.name]
    )
    model = _delegation_model(child_ids=[str(child.id)], write_tool=effects.name)
    monkeypatch.setattr("services.agents.runtime.loop.build_model", lambda _resolved: model)
    suspended = await run_scenario(committed_db_session_factory, context, model=model)
    assert suspended.run.status == "awaiting_approval"
    child_model = scripted_model(
        turns=[ToolTurn((ToolCall(effects.name, {"value": "second effect"}, "second-write"),))]
    )
    monkeypatch.setattr("services.agents.runtime.loop.build_model", lambda _resolved: child_model)
    original = execution.finalize_terminal_run

    async def settled_child(db, **kwargs):
        run_id = kwargs["run"].id
        if run_id != context.run_id:
            await db.commit()
            async with committed_db_session_factory() as remote:
                run = await remote.get(AgentRun, run_id)
                await fail_agent_run(
                    remote,
                    run,
                    error_code="run_abandoned",
                    error_message="Child execution expired.",
                )
                await remote.commit()
        return await original(db, **kwargs)

    monkeypatch.setattr(execution, "finalize_terminal_run", settled_child)
    with pytest.raises(AgentRunResumeRequiresRecoveryError):
        await resume_scenario(
            committed_db_session_factory,
            context,
            model=model,
            decisions=[AgentRunResumeDecision(tool_call_id="child-write", decision="approved")],
        )
    async with committed_db_session_factory() as db:
        root = await db.get(AgentRun, context.run_id)
        assert root.status == "failed"
        assert root.outcome == "blocked"
        assert root.error_code == "agent_run_resume_requires_recovery"
    assert len(effects.calls) == 1
    assert effects.calls[0][1] == "external"


@pytest.mark.parametrize("winner", [None, "reaped", "cancelled", "completed"])
async def test_unavailable_resumed_delegate_preserves_terminal_winner(
    committed_db_session_factory, monkeypatch, effects, winner
):
    import importlib
    from datetime import UTC, datetime, timedelta

    from core.exceptions.general import NotFoundError
    from services.agent_runs import cancel_agent_run, complete_agent_run, start_agent_run
    from services.agent_runs.reap_abandoned import reap_abandoned_runs
    from services.agents.runtime.delegation.constants import DELEGATE_NOT_ALLOWED_ERROR_MESSAGE

    resume = importlib.import_module(
        "services.agents.runtime.delegation.resume_approved_delegate_run"
    )
    context = await build_scenario_agent(
        committed_db_session_factory,
        trigger="scheduled",
        metadata={"envelope": {"side_effect_policy": "require_approval"}},
    )
    child = await add_scenario_delegate(
        committed_db_session_factory, context, tool_names=[effects.name]
    )
    model = _delegation_model(child_ids=[str(child.id)], write_tool=effects.name)
    monkeypatch.setattr("services.agents.runtime.loop.build_model", lambda _resolved: model)
    suspended = await run_scenario(committed_db_session_factory, context, model=model)
    assert suspended.run.status == "awaiting_approval"
    expected = None

    async def unavailable(session, **kwargs):
        nonlocal expected
        await session.commit()
        async with committed_db_session_factory() as remote:
            run = await remote.scalar(
                select(AgentRun).where(AgentRun.parent_run_id == context.run_id)
            )
            if winner == "cancelled":
                await cancel_agent_run(remote, run)
            elif winner in {"reaped", "completed"}:
                await start_agent_run(remote, run)
                if winner == "reaped":
                    run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
                    await remote.flush()
                    await reap_abandoned_runs(remote, run_id=run.id)
                else:
                    await complete_agent_run(remote, run)
            await remote.commit()
            expected = (run.status, run.error_code, run.error_message, run.completion_json)
        raise NotFoundError(
            "Delegate unavailable", resource_type="agent", resource_id=str(child.id)
        )

    monkeypatch.setattr(resume, "get_visible_delegate_agent", unavailable)
    with pytest.raises(AgentRunResumeRequiresRecoveryError):
        await resume_scenario(
            committed_db_session_factory,
            context,
            model=model,
            decisions=[AgentRunResumeDecision(tool_call_id="child-write", decision="approved")],
        )
    assert effects.calls == []
    async with committed_db_session_factory() as db:
        root = await db.get(AgentRun, context.run_id)
        assert root.status == "failed"
        assert root.outcome == "blocked"
        run = await db.scalar(select(AgentRun).where(AgentRun.parent_run_id == context.run_id))
        if winner is not None:
            assert (run.status, run.error_code, run.error_message, run.completion_json) == expected
        else:
            assert run.status == "failed"
            assert run.error_message == DELEGATE_NOT_ALLOWED_ERROR_MESSAGE


@pytest.mark.parametrize("second_decision", ["approved", "denied"])
@pytest.mark.parametrize("legacy", [False, True])
async def test_delegated_workflow_resumes_twice_without_repeating_effects(
    committed_db_session_factory,
    monkeypatch,
    effects,
    code_mode_executor_cleanup,
    second_decision,
    legacy,
):
    from dataclasses import replace

    from services.agents.runtime.tools.contract import ToolFieldPresentation, ToolPresentation
    from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG

    definition = RUNTIME_TOOL_CATALOG[effects.name]
    RUNTIME_TOOL_CATALOG[effects.name] = replace(
        definition,
        presentation=ToolPresentation(
            arg_fields=(
                ToolFieldPresentation(key="value", label="Value", format="text", editable=True),
            )
        ),
    )
    context = await build_scenario_agent(
        committed_db_session_factory,
        trigger="scheduled",
        metadata={
            "envelope": {"side_effect_policy": "require_approval"},
            "completion_contract": {"required": False, "max_requests": 5},
        },
    )
    child = await add_scenario_delegate(
        committed_db_session_factory, context, tool_names=[effects.name]
    )
    async with committed_db_session_factory() as db:
        saved = await db.get(Agent, child.id)
        saved.code_mode_enabled = True
        await db.commit()
    model = _delegation_model(
        child_ids=[str(child.id)],
        write_tool=effects.name,
        workflow_code=f"await {effects.name}(value='first')\ntry:\n    await {effects.name}(value='second')\nexcept PermissionError:\n    pass\n'child result'",
    )
    monkeypatch.setattr("services.agents.runtime.loop.build_model", lambda _resolved: model)
    first = await run_scenario(committed_db_session_factory, context, model=model)
    assert first.run.status == "awaiting_approval"
    [pending] = [event.data for event in first.events if event.event == "tool.approval_required"]
    assert pending["name"] == effects.name
    assert effects.calls == []
    assert first.run.usage_json["requests"] == 3
    async with committed_db_session_factory() as db:
        root = await db.get(AgentRun, context.run_id)
        child_run = await db.scalar(select(AgentRun).where(AgentRun.parent_run_id == root.id))
        for run in [root, child_run]:
            assert run.metadata_json[EFFECTIVE_USAGE_LIMITS_KEY]["limits"]["request_limit"] == 5
            if legacy:
                run.metadata_json = {
                    key: value
                    for key, value in run.metadata_json.items()
                    if key != EFFECTIVE_USAGE_LIMITS_KEY
                }
        if not legacy:
            root.metadata_json = {
                **root.metadata_json,
                "completion_contract": {"required": False, "max_requests": 10},
            }
        await db.commit()
    await close_code_mode_executor()
    second = await resume_scenario(
        committed_db_session_factory,
        context,
        model=model,
        decisions=[
            AgentRunResumeDecision(
                tool_call_id=pending["tool_call_id"],
                decision="approved",
                override_args={"value": "edited"},
            )
        ],
    )
    assert second.run.status == "awaiting_approval"
    assert second.run.usage_json["requests"] == 3
    assert second.run.metadata_json[EFFECTIVE_USAGE_LIMITS_KEY]["limits"]["request_limit"] == 5
    [next_pending] = [
        event.data for event in second.events if event.event == "tool.approval_required"
    ]
    assert next_pending["approval_id"] != pending["approval_id"]
    assert next_pending["approval_revision"] != pending["approval_revision"]
    owner_id = next_pending["owner_run_id"]
    assert [(str(owner), value) for owner, value in effects.calls] == [(owner_id, "edited")]
    await close_code_mode_executor()
    completed = await resume_scenario(
        committed_db_session_factory,
        context,
        model=model,
        decisions=[
            AgentRunResumeDecision(
                tool_call_id=next_pending["tool_call_id"],
                decision=second_decision,
                message="Skip the second action" if second_decision == "denied" else None,
            )
        ],
    )
    assert completed.run.status == "completed"
    assert completed.run.usage_json["requests"] == 5
    assert completed.run.metadata_json[EFFECTIVE_USAGE_LIMITS_KEY]["limits"]["request_limit"] == 5
    assert [value for _, value in effects.calls] == (
        ["edited", "second"] if second_decision == "approved" else ["edited"]
    )
    assert all(str(owner) == owner_id for owner, _ in effects.calls)
    async with committed_db_session_factory() as db:
        [child_run] = list(
            await db.scalars(select(AgentRun).where(AgentRun.parent_run_id == context.run_id))
        )
        assert child_run.status == "completed"
        assert "code_mode_state" not in (child_run.metadata_json or {})
        messages = list(
            await db.scalars(
                select(ConversationMessage).where(
                    ConversationMessage.conversation_id == child_run.conversation_id
                )
            )
        )
        assert any(
            part.get("tool_name") == "run_workflow" and part.get("part_kind") == "tool-return"
            for message in messages
            for part in message.parts["parts"]
        )


@pytest.mark.parametrize("request_limit", [2, 3, 5])
async def test_schedule_budget_stops_delegation_at_exact_shared_request_count(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    effects: ScenarioEffects,
    request_limit: int,
) -> None:
    context = await build_scenario_agent(
        committed_db_session_factory,
        trigger="scheduled",
        metadata={
            "completion_contract": {"required": False, "max_requests": request_limit},
            "envelope": {"side_effect_policy": "allow"},
        },
    )
    children = [
        await add_scenario_delegate(
            committed_db_session_factory, context, tool_names=[effects.name]
        )
        for _ in range(2)
    ]
    seen_requests: list[str] = []
    model = _delegation_model(
        child_ids=[str(child.id) for child in children],
        write_tool=effects.name,
        seen_requests=seen_requests,
    )
    monkeypatch.setattr("services.agents.runtime.loop.build_model", lambda _resolved: model)
    with pytest.raises(BudgetLimitExceeded) as error:
        await run_scenario(committed_db_session_factory, context, model=model)
    assert error.value.inherited
    assert len(seen_requests) == request_limit
    async with committed_db_session_factory() as db:
        root = await db.get(AgentRun, context.run_id)
        child_runs = list(
            await db.scalars(select(AgentRun).where(AgentRun.parent_run_id == root.id))
        )
        assert root.outcome == "budget_exhausted"
        assert root.completion_json["tripped_budget"] == {
            "kind": "requests",
            "limit": request_limit,
            "scope": "inherited",
        }
        assert all(run.status in {"completed", "failed"} for run in child_runs)
        assert len(child_runs) == (2 if request_limit == 5 else 1)
        for run in [root, *child_runs]:
            assert (
                run.metadata_json[EFFECTIVE_USAGE_LIMITS_KEY]["limits"]["request_limit"]
                == request_limit
            )
        events = list(
            await db.scalars(
                select(AIUsageEvent).where(
                    AIUsageEvent.run_id.in_([root.id, *(run.id for run in child_runs)])
                )
            )
        )
        assert sum(event.requests for event in events) == request_limit


@pytest.mark.parametrize("decision", ["approved", "denied"])
@pytest.mark.parametrize("updated_limit", [2, 20])
async def test_last_request_approval_settles_without_widening_saved_budget(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    effects: ScenarioEffects,
    decision: str,
    updated_limit: int,
) -> None:
    context = await build_scenario_agent(
        committed_db_session_factory,
        trigger="scheduled",
        metadata={
            "completion_contract": {"required": False, "max_requests": 3},
            "envelope": {"side_effect_policy": "require_approval"},
        },
    )
    child = await add_scenario_delegate(
        committed_db_session_factory, context, tool_names=[effects.name]
    )
    seen_requests: list[str] = []
    model = _delegation_model(
        child_ids=[str(child.id)], write_tool=effects.name, seen_requests=seen_requests
    )
    monkeypatch.setattr("services.agents.runtime.loop.build_model", lambda _resolved: model)
    parked = await run_scenario(committed_db_session_factory, context, model=model)
    assert parked.run.status == "awaiting_approval"
    assert len(seen_requests) == 3
    assert not effects.calls
    async with committed_db_session_factory() as db:
        root = await db.get(AgentRun, context.run_id)
        root.metadata_json = {
            **root.metadata_json,
            "completion_contract": {"required": False, "max_requests": updated_limit},
        }
        await db.commit()
    with pytest.raises(BudgetLimitExceeded):
        await resume_scenario(
            committed_db_session_factory,
            context,
            model=model,
            decisions=[AgentRunResumeDecision(tool_call_id="child-write", decision=decision)],
        )
    assert len(seen_requests) == 3
    assert len(effects.calls) == (1 if decision == "approved" else 0)
    async with committed_db_session_factory() as db:
        root = await db.get(AgentRun, context.run_id)
        child_run = await db.scalar(select(AgentRun).where(AgentRun.parent_run_id == root.id))
        assert root.outcome == "budget_exhausted"
        assert child_run.outcome == "budget_exhausted"
        assert root.metadata_json[EFFECTIVE_USAGE_LIMITS_KEY]["limits"]["request_limit"] == min(
            3, updated_limit
        )
        assert child_run.metadata_json[EFFECTIVE_USAGE_LIMITS_KEY]["limits"][
            "request_limit"
        ] == min(3, updated_limit)
        events = list(
            await db.scalars(
                select(AIUsageEvent).where(AIUsageEvent.run_id.in_([root.id, child_run.id]))
            )
        )
        assert sum(event.requests for event in events) == 3
        assert root.usage_json["requests"] == 3

    from core.exceptions.general import ConflictError

    settled_effects = list(effects.calls)
    with pytest.raises(ConflictError):
        await run_scenario(committed_db_session_factory, context, model=model, expected_status=None)
    assert len(seen_requests) == 3
    assert effects.calls == settled_effects


@pytest.mark.parametrize("resume", [False, True])
async def test_stricter_child_ceiling_returns_failure_while_parent_can_finish(
    committed_db_session_factory, monkeypatch, effects, resume
):
    context = await build_scenario_agent(
        committed_db_session_factory,
        trigger="scheduled",
        metadata={"envelope": {"side_effect_policy": "require_approval"}},
    )
    child = await add_scenario_delegate(
        committed_db_session_factory, context, tool_names=[effects.name]
    )
    seen_requests: list[str] = []
    model = _delegation_model(
        child_ids=[str(child.id)], write_tool=effects.name, seen_requests=seen_requests
    )
    monkeypatch.setattr("services.agents.runtime.loop.build_model", lambda _resolved: model)
    if resume:
        parked = await run_scenario(committed_db_session_factory, context, model=model)
        assert parked.run.status == "awaiting_approval"
    async with committed_db_session_factory() as db:
        saved_child = await db.get(Agent, child.id)
        saved_child.max_steps = 3 if resume else 2
        await db.commit()
    if resume:
        result = await resume_scenario(
            committed_db_session_factory,
            context,
            model=model,
            decisions=[AgentRunResumeDecision(tool_call_id="child-write", decision="approved")],
        )
    else:
        result = await run_scenario(committed_db_session_factory, context, model=model)
    assert result.run.outcome == "success"
    assert len(seen_requests) == (4 if resume else 3)
    assert len(effects.calls) == (1 if resume else 0)
    async with committed_db_session_factory() as db:
        child_run = await db.scalar(
            select(AgentRun).where(AgentRun.parent_run_id == context.run_id)
        )
        assert child_run.outcome == "budget_exhausted"
        assert child_run.completion_json["tripped_budget"]["scope"] == "local"
        assert result.run.metadata_json[EFFECTIVE_USAGE_LIMITS_KEY]["limits"]["request_limit"] == 20


async def test_inherited_streaming_token_overrun_preserves_mixed_model_ledger(
    committed_db_session_factory, monkeypatch, effects
):
    import importlib

    context = await build_scenario_agent(
        committed_db_session_factory,
        trigger="scheduled",
        metadata={
            "completion_contract": {
                "required": True,
                "criteria": ["Confirm the task result."],
                "max_total_tokens": 1000,
            }
        },
    )
    child = await add_scenario_delegate(committed_db_session_factory, context)
    async with committed_db_session_factory() as db:
        saved = await db.get(Agent, child.id)
        saved.model_provider = "google"
        saved.model = "gemini-3.8-flash"
        await db.commit()
    shared_usage = []
    entry = importlib.import_module("services.agents.runtime.execute_run")
    original = entry.execute_run

    async def capture_usage(db, **kwargs):
        shared_usage.append(kwargs["usage"])
        return await original(db, **kwargs)

    monkeypatch.setattr(entry, "execute_run", capture_usage)
    parent_model = _delegation_model(child_ids=[str(child.id)], write_tool=effects.name)
    chunks = []

    async def stream(messages, info):
        assert "report_completion" not in {tool.name for tool in info.function_tools}
        chunks.append("first")
        yield "token " * 2000
        chunks.append("second")
        yield "unreachable"

    child_model = FunctionModel(stream_function=stream)
    monkeypatch.setattr("services.agents.runtime.loop.build_model", lambda _resolved: child_model)
    with pytest.raises(BudgetLimitExceeded) as error:
        await run_scenario(committed_db_session_factory, context, model=parent_model)
    assert error.value.inherited
    assert error.value.kind == "total_tokens_limit"
    assert chunks == ["first"]
    [usage] = shared_usage
    assert usage.total_tokens > 1000
    async with committed_db_session_factory() as db:
        root = await db.get(AgentRun, context.run_id)
        child_run = await db.scalar(select(AgentRun).where(AgentRun.parent_run_id == root.id))
        assert root.outcome == child_run.outcome == "budget_exhausted"
        events = list(
            await db.scalars(
                select(AIUsageEvent).where(AIUsageEvent.run_id.in_([root.id, child_run.id]))
            )
        )
        assert {(event.provider, event.model) for event in events} == {
            ("openai", "gpt-5.4-mini"),
            ("google", "gemini-3.8-flash"),
        }
        assert sum(event.requests for event in events) == usage.requests == 3
        assert sum(event.input_tokens for event in events) == usage.input_tokens
        assert sum(event.output_tokens for event in events) == usage.output_tokens
