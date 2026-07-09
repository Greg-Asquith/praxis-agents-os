"""Runtime dispatch/audit tests for tool execution."""

import asyncio
import importlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel
from pydantic_ai import (
    ApprovalRequired,
    DeferredToolRequests,
    DeferredToolResults,
    ModelRetry,
    ToolDenied,
)
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.agent import Agent
from models.agent_run import AgentRun
from models.audit_event import AuditEvent
from models.conversation import Conversation, ConversationMessage
from models.session import Session
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.agent_runs import create_agent_run
from services.agent_runs.domain import (
    RUN_STATUS_AWAITING_APPROVAL,
    RUN_STATUS_CANCELLED,
    RUN_STATUS_COMPLETED,
)
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.cancellation import request_agent_run_task_cancel
from services.agents.runtime.delegation.tool_names import DELEGATION_TOOL_NAMES
from services.agents.runtime.dispatch import (
    _tool_call_args_for_digest,
    _tool_provider,
    digest_args,
)
from services.agents.runtime.envelope import RunEnvelope
from services.agents.runtime.execute_run import execute_run
from services.agents.runtime.sinks import CollectingSink
from services.agents.runtime.tools.contract import TOOL_EFFECT_WRITE
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG, runtime_tool
from tests.factories import build_user, build_workspace

pytestmark = pytest.mark.asyncio

execute_run_module = importlib.import_module("services.agents.runtime.execute_run")


class DispatchToolOutput(BaseModel):
    ok: bool


@dataclass(frozen=True)
class DispatchRuntimeContext:
    user_id: UUID
    workspace_id: UUID
    agent_id: UUID
    conversation_id: UUID
    run_id: UUID


@pytest.fixture
def dispatch_test_tools():
    names = [
        "dispatch_secret",
        "dispatch_retry",
        "dispatch_bad_read",
        "dispatch_bad_write",
        "dispatch_needs_approval",
        "dispatch_write_ok",
    ]
    for name in names:
        RUNTIME_TOOL_CATALOG.pop(name, None)

    counters = {"write_ok": 0}

    @runtime_tool(
        name="dispatch_secret",
        provider="test",
        label="Dispatch secret",
        description="Return a fixed value for dispatch tests.",
    )
    async def dispatch_secret(value: str) -> dict[str, bool]:
        return {"ok": bool(value)}

    @runtime_tool(
        name="dispatch_retry",
        provider="test",
        label="Dispatch retry",
        description="Raise a retry for dispatch tests.",
    )
    async def dispatch_retry(value: str) -> str:
        raise ModelRetry(f"retry requested for {value}")

    @runtime_tool(
        name="dispatch_bad_read",
        provider="test",
        label="Dispatch bad read",
        description="Return an invalid read output for dispatch tests.",
        output_model=DispatchToolOutput,
    )
    async def dispatch_bad_read() -> dict[str, str]:
        return {"wrong": "shape"}

    @runtime_tool(
        name="dispatch_bad_write",
        provider="test",
        label="Dispatch bad write",
        description="Return an invalid write output for dispatch tests.",
        effect=TOOL_EFFECT_WRITE,
        output_model=DispatchToolOutput,
    )
    async def dispatch_bad_write() -> dict[str, str]:
        return {"wrong": "shape"}

    @runtime_tool(
        name="dispatch_needs_approval",
        provider="test",
        label="Dispatch needs approval",
        description="Suspend execution for dispatch approval tests.",
    )
    async def dispatch_needs_approval(value: str) -> str:
        raise ApprovalRequired(metadata={"value_length": len(value)})

    @runtime_tool(
        name="dispatch_write_ok",
        provider="test",
        label="Dispatch write ok",
        description="Return a valid write output for dispatch tests.",
        effect=TOOL_EFFECT_WRITE,
        output_model=DispatchToolOutput,
    )
    async def dispatch_write_ok(value: str) -> dict[str, bool]:
        counters["write_ok"] += 1
        return {"ok": bool(value)}

    yield counters

    for name in names:
        RUNTIME_TOOL_CATALOG.pop(name, None)


async def test_tool_invocation_writes_digest_only_audit_row(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    dispatch_test_tools,
) -> None:
    context = await _create_committed_runtime_context(
        committed_db_session_factory,
        tool_names=["dispatch_secret"],
    )
    marker = f"raw-value-{uuid4().hex}"

    try:
        result = await _execute_single_tool(
            committed_db_session_factory,
            context,
            tool_name="dispatch_secret",
            args={"value": marker},
        )

        assert result.run.status == RUN_STATUS_COMPLETED

        [event] = await _tool_audit_events(
            committed_db_session_factory,
            context,
            tool_name="dispatch_secret",
        )
        expected_sha, expected_bytes = digest_args({"value": marker})

        assert event.action == "execute"
        assert event.resource_type == "tool_call"
        assert event.resource_id == "dispatch_secret-call"
        assert event.actor_type == "user"
        assert event.actor_id == str(context.user_id)
        assert event.actor_user_id == context.user_id
        assert event.actor_display is not None
        assert event.requested_by_user_id == context.user_id
        assert event.request_id == "dispatch-test-request"
        assert event.ip_address == "203.0.113.24"
        assert event.user_agent == "dispatch-test-agent/1.0"
        assert event.tool_provider == "test"
        assert event.status == "success"
        assert event.summary.startswith(f"{event.actor_display} ran tool dispatch_secret")
        assert event.details["outcome"] == "completed"
        assert "args" not in event.details
        assert event.details["args_sha256"] == expected_sha
        assert event.details["args_bytes"] == expected_bytes
        assert event.details["latency_ms"] >= 1
        assert event.details["run_id"] == str(context.run_id)
        assert event.details["agent_id"] == str(context.agent_id)
        assert marker not in json.dumps(event.details)
    finally:
        await _delete_committed_runtime_context(committed_db_session_factory, context)


async def test_tool_model_retry_records_failure_and_run_continues(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    dispatch_test_tools,
) -> None:
    context = await _create_committed_runtime_context(
        committed_db_session_factory,
        tool_names=["dispatch_retry"],
    )

    try:
        result = await _execute_single_tool(
            committed_db_session_factory,
            context,
            tool_name="dispatch_retry",
            args={"value": "bad"},
            final_text="after retry",
        )

        assert result.output == "after retry"
        [event] = await _tool_audit_events(
            committed_db_session_factory,
            context,
            tool_name="dispatch_retry",
        )
        assert event.status == "failure"
        assert event.details["outcome"] == "failed"
        assert event.details["error_code"] == "ToolRetryError"
    finally:
        await _delete_committed_runtime_context(committed_db_session_factory, context)


async def test_output_contract_failures_record_mutation_risk(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    dispatch_test_tools,
) -> None:
    read_messages: list[ModelMessage] = []
    write_messages: list[ModelMessage] = []
    read_context = await _create_committed_runtime_context(
        committed_db_session_factory,
        tool_names=["dispatch_bad_read"],
    )
    write_context = await _create_committed_runtime_context(
        committed_db_session_factory,
        tool_names=["dispatch_bad_write"],
    )

    try:
        await _execute_single_tool(
            committed_db_session_factory,
            read_context,
            tool_name="dispatch_bad_read",
            args={},
            final_text="read recovered",
            seen_messages=read_messages,
        )
        await _execute_single_tool(
            committed_db_session_factory,
            write_context,
            tool_name="dispatch_bad_write",
            args={},
            final_text="write recovered",
            seen_messages=write_messages,
        )

        [read_event] = await _tool_audit_events(
            committed_db_session_factory,
            read_context,
            tool_name="dispatch_bad_read",
        )
        [write_event] = await _tool_audit_events(
            committed_db_session_factory,
            write_context,
            tool_name="dispatch_bad_write",
        )
        assert read_event.status == "failure"
        assert read_event.details["outcome"] == "failed"
        assert write_event.status == "failure"
        assert write_event.details["outcome"] == "unverified_mutation"
        assert "Tool output did not match" in " ".join(map(str, read_messages))
        assert "external action may have completed" in " ".join(map(str, write_messages))
    finally:
        await _delete_committed_runtime_context(
            committed_db_session_factory,
            read_context,
        )
        await _delete_committed_runtime_context(
            committed_db_session_factory,
            write_context,
        )


async def test_envelope_denies_write_tool_before_execution(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    dispatch_test_tools,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = await _create_committed_runtime_context(
        committed_db_session_factory,
        tool_names=["dispatch_write_ok"],
    )
    monkeypatch.setattr(
        execute_run_module,
        "build_run_envelope",
        lambda _run: RunEnvelope(
            principal="interactive",
            side_effect_policy="deny",
        ),
    )

    try:
        result = await _execute_single_tool(
            committed_db_session_factory,
            context,
            tool_name="dispatch_write_ok",
            args={"value": "do it"},
            final_text="denied and recovered",
        )

        assert result.output == "denied and recovered"
        assert dispatch_test_tools["write_ok"] == 0
        [event] = await _tool_audit_events(
            committed_db_session_factory,
            context,
            tool_name="dispatch_write_ok",
        )
        assert event.status == "denied"
        assert event.details["outcome"] == "denied_envelope"
    finally:
        await _delete_committed_runtime_context(committed_db_session_factory, context)


async def test_audit_writer_failure_does_not_fail_tool_call(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    dispatch_test_tools,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool_events_module = importlib.import_module("services.audit_events.tool_events")
    context = await _create_committed_runtime_context(
        committed_db_session_factory,
        tool_names=["dispatch_secret"],
    )

    def fail_session_factory():
        raise RuntimeError("audit database unavailable")

    monkeypatch.setattr(
        tool_events_module,
        "get_async_db_session_factory",
        fail_session_factory,
    )

    try:
        result = await _execute_single_tool(
            committed_db_session_factory,
            context,
            tool_name="dispatch_secret",
            args={"value": "still-runs"},
        )

        assert result.output == "done"
        assert (
            await _tool_audit_events(
                committed_db_session_factory,
                context,
                tool_name="dispatch_secret",
            )
        ) == []
    finally:
        await _delete_committed_runtime_context(committed_db_session_factory, context)


async def test_tool_body_approval_required_records_pending_audit(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    dispatch_test_tools,
) -> None:
    context = await _create_committed_runtime_context(
        committed_db_session_factory,
        tool_names=["dispatch_needs_approval"],
    )

    try:
        result = await _execute_single_tool(
            committed_db_session_factory,
            context,
            tool_name="dispatch_needs_approval",
            args={"value": "pause"},
        )

        assert isinstance(result.output, DeferredToolRequests)
        assert result.run.status == RUN_STATUS_AWAITING_APPROVAL
        [event] = await _tool_audit_events(
            committed_db_session_factory,
            context,
            tool_name="dispatch_needs_approval",
        )
        assert event.status == "pending"
        assert event.details["outcome"] == "approval_requested"
        assert event.details["approval_ref"] == "dispatch_needs_approval-call"
    finally:
        await _delete_committed_runtime_context(committed_db_session_factory, context)


async def test_denied_approval_records_audit_without_executing_tool(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    dispatch_test_tools,
) -> None:
    context = await _create_committed_runtime_context(
        committed_db_session_factory,
        tool_names=["dispatch_write_ok"],
        tool_policies={"dispatch_write_ok": "approval"},
    )
    stream_function, seen_messages = _single_tool_stream(
        tool_name="dispatch_write_ok",
        args={"value": "do not run"},
        final_text="denial handled",
    )

    try:
        async with committed_db_session_factory() as db:
            suspended = await execute_run(
                db,
                conversation_id=context.conversation_id,
                run_id=context.run_id,
                user_prompt="Need approval.",
                sink=CollectingSink(
                    run_id=context.run_id,
                    conversation_id=context.conversation_id,
                ),
                model=FunctionModel(
                    stream_function=stream_function,
                    model_name="dispatch-denied-approval",
                ),
            )

        assert isinstance(suspended.output, DeferredToolRequests)
        assert suspended.run.status == RUN_STATUS_AWAITING_APPROVAL
        assert dispatch_test_tools["write_ok"] == 0

        suspended_state = load_suspended_run_state(suspended.run)
        deferred_tool_results = DeferredToolResults()
        deferred_tool_results.approvals[suspended_state.pending_tool_call_ids[0]] = ToolDenied(
            "Denied in test"
        )

        async with committed_db_session_factory() as db:
            resumed = await execute_run(
                db,
                conversation_id=context.conversation_id,
                run_id=context.run_id,
                user_prompt=None,
                sink=CollectingSink(
                    run_id=context.run_id,
                    conversation_id=context.conversation_id,
                ),
                model=FunctionModel(
                    stream_function=stream_function,
                    model_name="dispatch-denied-approval",
                ),
                expected_status=RUN_STATUS_AWAITING_APPROVAL,
                message_history=suspended_state.message_history,
                deferred_tool_results=deferred_tool_results,
            )

        assert resumed.output == "denial handled"
        assert seen_messages
        assert dispatch_test_tools["write_ok"] == 0
        [event] = await _tool_audit_events(
            committed_db_session_factory,
            context,
            tool_name="dispatch_write_ok",
        )
        assert event.status == "denied"
        assert event.details["outcome"] == "denied_approval"
        assert event.details["approval_ref"] == suspended_state.pending_tool_call_ids[0]
        assert event.details["error_code"] == "ToolDenied"
        expected_sha, expected_bytes = digest_args({"value": "do not run"})
        assert event.details["args_sha256"] == expected_sha
        assert event.details["args_bytes"] == expected_bytes
    finally:
        await _delete_committed_runtime_context(committed_db_session_factory, context)


async def test_cancelled_tool_call_records_cancelled_audit_row(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tool_name = f"dispatch_cancel_{uuid4().hex}"
    tool_started = asyncio.Event()
    RUNTIME_TOOL_CATALOG.pop(tool_name, None)

    @runtime_tool(
        name=tool_name,
        provider="test",
        label="Dispatch cancel",
        description="Sleep until the run is cancelled.",
        effect=TOOL_EFFECT_WRITE,
    )
    async def dispatch_cancel(value: str) -> dict[str, bool]:
        tool_started.set()
        await asyncio.sleep(10)
        return {"ok": bool(value)}

    context = await _create_committed_runtime_context(
        committed_db_session_factory,
        tool_names=[tool_name],
    )

    try:
        task = asyncio.create_task(
            _execute_single_tool(
                committed_db_session_factory,
                context,
                tool_name=tool_name,
                args={"value": "interrupt"},
            )
        )
        await asyncio.wait_for(tool_started.wait(), timeout=2)
        request_agent_run_task_cancel(task, run_id=context.run_id)

        with pytest.raises(asyncio.CancelledError):
            await task

        async with committed_db_session_factory() as db:
            run = await db.get(AgentRun, context.run_id)
            assert run is not None
            assert run.status == RUN_STATUS_CANCELLED

        [event] = await _tool_audit_events(
            committed_db_session_factory,
            context,
            tool_name=tool_name,
        )
        assert event.status == "failure"
        assert event.details["outcome"] == "cancelled"
        assert event.details["error_code"] == "CancelledError"
        assert event.details["args_sha256"]
    finally:
        RUNTIME_TOOL_CATALOG.pop(tool_name, None)
        await _delete_committed_runtime_context(committed_db_session_factory, context)


async def test_delegation_tool_names_are_audited_as_delegation_provider() -> None:
    for tool_name in DELEGATION_TOOL_NAMES:
        assert _tool_provider(tool_name, None) == "delegation"


async def test_raw_json_tool_call_args_digest_like_execution_args() -> None:
    assert _tool_call_args_for_digest('{"value":"same"}') == {"value": "same"}
    assert digest_args(_tool_call_args_for_digest('{"value":"same"}')) == digest_args(
        {"value": "same"}
    )


async def _create_committed_runtime_context(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tool_names: list[str],
    tool_policies: dict[str, str] | None = None,
) -> DispatchRuntimeContext:
    async with session_factory() as db:
        user = build_user(email=f"runtime-dispatch-{uuid4().hex}@example.com")
        workspace = build_workspace(slug=f"runtime-dispatch-{uuid4().hex[:8]}")
        db.add_all([user, workspace])
        await db.flush()

        agent = Agent(
            name="Dispatch Runtime Agent",
            slug=f"dispatch-runtime-agent-{uuid4().hex[:8]}",
            instructions="Reply plainly.",
            workspace_id=workspace.id,
            created_by=user.id,
            model_provider="openai",
            model="gpt-5.4-mini",
            tool_names=tool_names,
            tool_policies=tool_policies,
        )
        db.add(agent)
        await db.flush()

        conversation = Conversation(
            user_id=user.id,
            workspace_id=workspace.id,
            created_by=user.id,
            active_agent_id=agent.id,
        )
        db.add(conversation)
        await db.flush()

        run = await create_agent_run(
            db,
            conversation_id=conversation.id,
            agent_id=agent.id,
            workspace_id=workspace.id,
            user_id=user.id,
            trigger="interactive",
            metadata={
                "audit_context": {
                    "request_id": "dispatch-test-request",
                    "ip_address": "203.0.113.24",
                    "user_agent": "dispatch-test-agent/1.0",
                }
            },
        )
        await db.commit()

    return DispatchRuntimeContext(
        user_id=user.id,
        workspace_id=workspace.id,
        agent_id=agent.id,
        conversation_id=conversation.id,
        run_id=run.id,
    )


async def _delete_committed_runtime_context(
    session_factory: async_sessionmaker[AsyncSession],
    context: DispatchRuntimeContext,
) -> None:
    async with session_factory() as db:
        await db.execute(
            delete(AuditEvent).where(
                or_(
                    AuditEvent.workspace_id == context.workspace_id,
                    AuditEvent.requested_by_user_id == context.user_id,
                )
            )
        )
        await db.execute(
            delete(ConversationMessage).where(
                ConversationMessage.conversation_id == context.conversation_id
            )
        )
        await db.execute(
            delete(AgentRun).where(AgentRun.conversation_id == context.conversation_id)
        )
        await db.execute(delete(Conversation).where(Conversation.id == context.conversation_id))
        await db.execute(delete(Agent).where(Agent.id == context.agent_id))
        await db.execute(
            delete(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == context.workspace_id
            )
        )
        await db.execute(delete(Session).where(Session.user_id == context.user_id))
        await db.execute(
            update(User).where(User.id == context.user_id).values(default_workspace_id=None)
        )
        await db.execute(delete(User).where(User.id == context.user_id))
        await db.execute(delete(Workspace).where(Workspace.id == context.workspace_id))
        await db.commit()


async def _execute_single_tool(
    session_factory: async_sessionmaker[AsyncSession],
    context: DispatchRuntimeContext,
    *,
    tool_name: str,
    args: dict[str, object],
    final_text: str = "done",
    seen_messages: list[ModelMessage] | None = None,
):
    stream_function, _seen_messages = _single_tool_stream(
        tool_name=tool_name,
        args=args,
        final_text=final_text,
        seen_messages=seen_messages,
    )
    async with session_factory() as db:
        return await execute_run(
            db,
            conversation_id=context.conversation_id,
            run_id=context.run_id,
            user_prompt="Use the tool.",
            sink=CollectingSink(
                run_id=context.run_id,
                conversation_id=context.conversation_id,
            ),
            model=FunctionModel(
                stream_function=stream_function,
                model_name=f"{tool_name}-model",
            ),
        )


def _single_tool_stream(
    *,
    tool_name: str,
    args: dict[str, object],
    final_text: str = "done",
    seen_messages: list[ModelMessage] | None = None,
):
    state = {"called": False}
    captured_messages = seen_messages if seen_messages is not None else []

    async def stream(
        messages: list[ModelMessage],
        _info: AgentInfo,
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        captured_messages[:] = messages
        if not state["called"]:
            state["called"] = True
            yield {
                0: DeltaToolCall(
                    name=tool_name,
                    json_args=json.dumps(args),
                    tool_call_id=f"{tool_name}-call",
                )
            }
            return
        yield final_text

    return stream, captured_messages


async def _tool_audit_events(
    session_factory: async_sessionmaker[AsyncSession],
    context: DispatchRuntimeContext,
    *,
    tool_name: str,
) -> list[AuditEvent]:
    async with session_factory() as db:
        return list(
            (
                await db.scalars(
                    select(AuditEvent)
                    .where(
                        AuditEvent.workspace_id == context.workspace_id,
                        AuditEvent.tool_name == tool_name,
                        AuditEvent.details["run_id"].astext == str(context.run_id),
                    )
                    .order_by(AuditEvent.occurred_at)
                )
            ).all()
        )
