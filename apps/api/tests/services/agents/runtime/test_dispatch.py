"""Runtime dispatch/audit tests for tool execution."""

import asyncio
import importlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel
from pydantic_ai import (
    ApprovalRequired,
    DeferredToolRequests,
    DeferredToolResults,
    ModelRetry,
    RunContext,
    ToolApproved,
)
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.database import set_session_tenant_context
from core.exceptions.integration import (
    IntegrationError,
    IntegrationFailureDisposition,
    IntegrationNotFoundError,
    IntegrationUnverifiedMutationError,
)
from core.settings import settings
from models.agent import Agent
from models.agent_run import AgentRun
from models.audit_event import AuditEvent
from models.classifiers import Classifier
from models.conversation import Conversation, ConversationMessage
from models.session import Session
from models.user import User
from models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from services.agent_runs import create_agent_run
from services.agent_runs.domain import (
    RUN_STATUS_AWAITING_APPROVAL,
    RUN_STATUS_COMPLETED,
    RUN_TRIGGER_SCHEDULED,
)
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.delegation.tool_names import DELEGATION_TOOL_NAMES
from services.agents.runtime.dispatch import (
    _tool_call_args_for_digest,
    _tool_provider,
    digest_args,
    model_visible_integration_failure,
)
from services.agents.runtime.execute_run import execute_run
from services.agents.runtime.sinks import CollectingSink
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_EXTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_EXTERNAL_WRITE,
)
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG, runtime_tool
from services.agents.runtime.untrusted import (
    UNTRUSTED_CONTENT_END,
    UNTRUSTED_CONTENT_START,
    UntrustedContent,
    UntrustedNode,
)
from tests.factories import build_user, build_workspace, build_workspace_membership

pytestmark = pytest.mark.asyncio


class DispatchToolOutput(BaseModel):
    ok: bool


class DispatchUntrustedOutput(BaseModel):
    body: UntrustedNode


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
        "dispatch_internal_write_ok",
        "dispatch_large_structured",
        "dispatch_long_text",
        "dispatch_untrusted",
        "dispatch_write_ok",
        "dispatch_provider_rejected",
    ]
    for name in names:
        RUNTIME_TOOL_CATALOG.pop(name, None)

    counters = {"internal_write_ok": 0, "read_ok": 0, "write_ok": 0, "scope_resolutions": 0}

    def resolve_dispatch_write_scope(_args: dict[str, object]) -> Literal["external"]:
        counters["scope_resolutions"] += 1
        return TOOL_EFFECT_SCOPE_EXTERNAL

    @runtime_tool(
        name="dispatch_secret",
        provider="test",
        label="Dispatch secret",
        description="Return a fixed value for dispatch tests.",
        takes_ctx=True,
    )
    async def dispatch_secret(ctx: RunContext[RuntimeDeps], value: str) -> dict[str, bool]:
        assert ctx.deps.db.in_transaction() is False
        counters["read_ok"] += 1
        return {"ok": bool(value)}

    @runtime_tool(
        name="dispatch_retry",
        provider="test",
        label="Dispatch retry",
        description="Raise a retry for dispatch tests.",
        takes_ctx=True,
    )
    async def dispatch_retry(
        ctx: RunContext[RuntimeDeps],
        value: str,
        conversation_title: str | None = None,
    ) -> str:
        if conversation_title is not None:
            ctx.deps.conversation.title = conversation_title
            await ctx.deps.db.flush()
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
        takes_ctx=True,
    )
    async def dispatch_bad_write(
        ctx: RunContext[RuntimeDeps],
        conversation_title: str | None = None,
    ) -> dict[str, str]:
        if conversation_title is not None:
            ctx.deps.conversation.title = conversation_title
            await ctx.deps.db.flush()
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
        name="dispatch_internal_write_ok",
        provider="test",
        label="Dispatch internal write ok",
        description="Return a valid internal write output for dispatch tests.",
        effect=TOOL_EFFECT_WRITE,
        output_model=DispatchToolOutput,
    )
    async def dispatch_internal_write_ok(value: str) -> dict[str, bool]:
        counters["internal_write_ok"] += 1
        return {"ok": bool(value)}

    @runtime_tool(
        name="dispatch_long_text",
        provider="test",
        label="Dispatch long text",
        description="Return oversized free text for dispatch tests.",
    )
    async def dispatch_long_text(value: str) -> str:
        return value

    @runtime_tool(
        name="dispatch_large_structured",
        provider="test",
        label="Dispatch large structured",
        description="Return an oversized mapping for dispatch tests.",
    )
    async def dispatch_large_structured(value: str) -> dict[str, str]:
        return {"value": value}

    @runtime_tool(
        name="dispatch_untrusted",
        provider="test",
        label="Dispatch untrusted",
        description="Return structured untrusted content for dispatch tests.",
        output_model=DispatchUntrustedOutput,
    )
    async def dispatch_untrusted(value: str) -> dict[str, UntrustedContent]:
        return {
            "body": UntrustedContent(
                source_kind="gmail_message",
                source_ref="message-1",
                content=value,
            )
        }

    @runtime_tool(
        name="dispatch_write_ok",
        provider="test",
        label="Dispatch write ok",
        description="Return a valid write output for dispatch tests.",
        effect=TOOL_EFFECT_WRITE,
        effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
        egress=TOOL_EGRESS_EXTERNAL_WRITE,
        effect_scope_resolver=resolve_dispatch_write_scope,
        output_model=DispatchToolOutput,
    )
    async def dispatch_write_ok(value: str) -> dict[str, bool]:
        counters["write_ok"] += 1
        return {"ok": bool(value)}

    @runtime_tool(
        name="dispatch_provider_rejected",
        provider="test",
        label="Dispatch provider rejected",
        description="Raise a rejected provider read for dispatch tests.",
    )
    async def dispatch_provider_rejected(value: str) -> dict[str, bool]:
        raise IntegrationNotFoundError(
            f"The provider has no record named {value}.",
            provider_key="test",
            operation="read",
            failure_disposition=IntegrationFailureDisposition.REJECTED,
        )

    yield counters

    for name in names:
        RUNTIME_TOOL_CATALOG.pop(name, None)


async def test_oversized_text_is_model_visible_persisted_and_audited_as_truncated(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    dispatch_test_tools,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = await _create_committed_runtime_context(
        committed_db_session_factory,
        tool_names=["dispatch_long_text"],
    )
    original = "h" * 80 + "middle-content" * 20 + "t" * 20
    seen_messages: list[ModelMessage] = []
    monkeypatch.setattr(settings, "AGENT_TOOL_RESULT_MAX_CHARS", 100)

    try:
        result = await _execute_single_tool(
            committed_db_session_factory,
            context,
            tool_name="dispatch_long_text",
            args={"value": original},
            seen_messages=seen_messages,
        )

        assert result.run.status == RUN_STATUS_COMPLETED
        model_visible = _tool_result_content(seen_messages, "dispatch_long_text")
        assert model_visible.startswith("h" * 80)
        assert model_visible.endswith("t" * 20)
        assert "Tool result truncated" in model_visible

        async with committed_db_session_factory() as db:
            persisted_row = await db.scalar(
                select(ConversationMessage).where(
                    ConversationMessage.conversation_id == context.conversation_id,
                    ConversationMessage.tool_name == "dispatch_long_text",
                    ConversationMessage.role == "tool",
                )
            )
        assert persisted_row is not None
        persisted_content = persisted_row.parts["parts"][0]["content"]
        assert persisted_content == model_visible

        [event] = await _tool_audit_events(
            committed_db_session_factory,
            context,
            tool_name="dispatch_long_text",
        )
        assert event.details["result_chars"] == len(model_visible)
        assert event.details["result_truncated"] is True
        assert event.details["result_original_chars"] == len(original)
    finally:
        await _delete_committed_runtime_context(committed_db_session_factory, context)


async def test_untrusted_result_is_framed_for_model_but_streamed_and_persisted_as_node(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    dispatch_test_tools,
) -> None:
    context = await _create_committed_runtime_context(
        committed_db_session_factory,
        tool_names=["dispatch_untrusted"],
    )
    content = "External body"
    seen_messages: list[ModelMessage] = []
    sink = CollectingSink(
        run_id=context.run_id,
        conversation_id=context.conversation_id,
    )

    try:
        await _execute_single_tool(
            committed_db_session_factory,
            context,
            tool_name="dispatch_untrusted",
            args={"value": content},
            seen_messages=seen_messages,
            sink=sink,
        )

        model_visible = _tool_result_content(seen_messages, "dispatch_untrusted")["body"]
        assert model_visible.count(UNTRUSTED_CONTENT_START) == 1
        assert model_visible.count(UNTRUSTED_CONTENT_END) == 1

        async with committed_db_session_factory() as db:
            persisted_row = await db.scalar(
                select(ConversationMessage).where(
                    ConversationMessage.conversation_id == context.conversation_id,
                    ConversationMessage.tool_name == "dispatch_untrusted",
                    ConversationMessage.role == "tool",
                )
            )
        assert persisted_row is not None
        persisted_body = persisted_row.parts["parts"][0]["content"]["body"]
        assert persisted_body == {
            "node": "praxis_untrusted",
            "source_kind": "gmail_message",
            "source_ref": "message-1",
            "content": content,
        }
        assert UNTRUSTED_CONTENT_START not in json.dumps(persisted_body)
        assert UNTRUSTED_CONTENT_END not in json.dumps(persisted_body)
        tool_results = [event for event in sink.events if event.event == "tool.result"]
        assert tool_results[-1].data["result"]["body"] == persisted_body
        assert UNTRUSTED_CONTENT_START not in json.dumps(tool_results[-1].data["result"])
        assert UNTRUSTED_CONTENT_END not in json.dumps(tool_results[-1].data["result"])
    finally:
        await _delete_committed_runtime_context(committed_db_session_factory, context)


def _integration_error(disposition: IntegrationFailureDisposition | None) -> IntegrationError:
    return IntegrationError(
        "Provider rejected the request.",
        provider_key="test",
        operation="op",
        failure_disposition=disposition,
    )


@pytest.mark.parametrize(
    ("effect", "exc", "expected"),
    [
        ("read", _integration_error(IntegrationFailureDisposition.REJECTED), True),
        ("read", _integration_error(None), True),
        ("read", _integration_error(IntegrationFailureDisposition.AMBIGUOUS), False),
        ("read", IntegrationUnverifiedMutationError("Unverified"), False),
        ("read", RuntimeError("unexpected"), False),
        ("write", _integration_error(IntegrationFailureDisposition.REJECTED), True),
        ("write", _integration_error(IntegrationFailureDisposition.NOT_DISPATCHED), True),
        ("write", _integration_error(None), False),
        ("write", _integration_error(IntegrationFailureDisposition.AMBIGUOUS), False),
    ],
)
async def test_model_visible_integration_failure_only_covers_effect_free_rejections(
    effect, exc, expected, dispatch_test_tools
) -> None:
    definition = RUNTIME_TOOL_CATALOG[
        "dispatch_write_ok" if effect == "write" else "dispatch_secret"
    ]
    message = model_visible_integration_failure(definition, definition.name, exc)
    assert (message is not None) is expected
    if message is not None:
        assert message.startswith(f"{definition.name} did not complete: Provider rejected")
        assert "provider=" not in message


async def test_read_only_role_allows_reads_but_denies_automatic_writes(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    dispatch_test_tools,
) -> None:
    read_context = await _create_committed_runtime_context(
        committed_db_session_factory,
        tool_names=["dispatch_secret"],
        role=WorkspaceRole.READ_ONLY,
    )
    write_context = await _create_committed_runtime_context(
        committed_db_session_factory,
        tool_names=["dispatch_internal_write_ok"],
        role=WorkspaceRole.READ_ONLY,
    )

    try:
        read_result = await _execute_single_tool(
            committed_db_session_factory,
            read_context,
            tool_name="dispatch_secret",
            args={"value": "visible"},
        )
        write_result = await _execute_single_tool(
            committed_db_session_factory,
            write_context,
            tool_name="dispatch_internal_write_ok",
            args={"value": "blocked"},
            final_text="write denied",
        )

        assert read_result.output == "done"
        assert write_result.output == "write denied"
        assert dispatch_test_tools["internal_write_ok"] == 0
        [event] = await _tool_audit_events(
            committed_db_session_factory,
            write_context,
            tool_name="dispatch_internal_write_ok",
        )
        assert event.status == "denied"
        assert event.details["outcome"] == "denied_authorization"
        assert event.details["error_code"] == "WorkspaceRoleDenied"
    finally:
        await _delete_committed_runtime_context(
            committed_db_session_factory,
            read_context,
        )
        await _delete_committed_runtime_context(
            committed_db_session_factory,
            write_context,
        )


async def test_membership_revocation_denies_read_after_runtime_setup(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    dispatch_test_tools,
) -> None:
    context = await _create_committed_runtime_context(
        committed_db_session_factory,
        tool_names=["dispatch_secret"],
    )
    model_started = asyncio.Event()
    continue_model = asyncio.Event()
    state = {"called": False}

    async def stream(
        _messages: list[ModelMessage],
        _info: AgentInfo,
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        if not state["called"]:
            state["called"] = True
            model_started.set()
            await continue_model.wait()
            yield {
                0: DeltaToolCall(
                    name="dispatch_secret",
                    json_args='{"value":"blocked"}',
                    tool_call_id="dispatch_secret-call",
                )
            }
            return
        yield "read denied"

    async def execute_paused_run():
        async with committed_db_session_factory() as db:
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
                    stream_function=stream,
                    model_name="dispatch-revoked-membership",
                ),
            )

    task = asyncio.create_task(execute_paused_run())
    try:
        await asyncio.wait_for(model_started.wait(), timeout=2)

        async with committed_db_session_factory() as db:
            membership = await db.scalar(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == context.workspace_id,
                    WorkspaceMembership.user_id == context.user_id,
                )
            )
            assert membership is not None
            membership.soft_delete()
            await db.commit()

        continue_model.set()
        result = await task

        assert result.output == "read denied"
        assert dispatch_test_tools["read_ok"] == 0
        [event] = await _tool_audit_events(
            committed_db_session_factory,
            context,
            tool_name="dispatch_secret",
        )
        assert event.status == "denied"
        assert event.details["outcome"] == "denied_authorization"
        assert event.details["error_code"] == "WorkspaceMembershipRevoked"
    finally:
        continue_model.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await _delete_committed_runtime_context(committed_db_session_factory, context)


async def test_read_only_role_cannot_execute_an_approved_write_replay(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    dispatch_test_tools,
) -> None:
    context = await _create_committed_runtime_context(
        committed_db_session_factory,
        tool_names=["dispatch_internal_write_ok"],
        tool_policies={"dispatch_internal_write_ok": "approval"},
        role=WorkspaceRole.READ_ONLY,
    )
    stream_function, _seen_messages = _single_tool_stream(
        tool_name="dispatch_internal_write_ok",
        args={"value": "blocked"},
        final_text="approval denied by role",
    )

    try:
        async with committed_db_session_factory() as db:
            suspended = await execute_run(
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
                    model_name="dispatch-role-approval",
                ),
            )

        assert isinstance(suspended.output, DeferredToolRequests)
        suspended_state = load_suspended_run_state(suspended.run)
        deferred_tool_results = DeferredToolResults(
            approvals={suspended_state.pending_tool_call_ids[0]: ToolApproved()}
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
                    model_name="dispatch-role-approval",
                ),
                expected_status=RUN_STATUS_AWAITING_APPROVAL,
                message_history=suspended_state.message_history,
                deferred_tool_results=deferred_tool_results,
            )

        assert resumed.output == "approval denied by role"
        assert dispatch_test_tools["internal_write_ok"] == 0
        events = await _tool_audit_events(
            committed_db_session_factory,
            context,
            tool_name="dispatch_internal_write_ok",
        )
        assert [(event.status, event.details["outcome"]) for event in events] == [
            ("pending", "approval_requested"),
            ("denied", "denied_authorization"),
        ]
    finally:
        await _delete_committed_runtime_context(committed_db_session_factory, context)


async def test_tool_turn_releases_transaction_before_each_model_request(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    dispatch_test_tools,
) -> None:
    context = await _create_committed_runtime_context(
        committed_db_session_factory,
        tool_names=["dispatch_secret"],
    )

    try:
        async with committed_db_session_factory() as db:
            await set_session_tenant_context(
                db,
                workspace_id=context.workspace_id,
                user_id=context.user_id,
            )
            stream_function, _seen_messages = _single_tool_stream(
                tool_name="dispatch_secret",
                args={"value": "transaction-boundary"},
            )

            async def asserting_stream(messages, info):
                assert db.in_transaction() is False
                async for event in stream_function(messages, info):
                    yield event

            result = await execute_run(
                db,
                conversation_id=context.conversation_id,
                run_id=context.run_id,
                user_prompt="Use the tool.",
                sink=CollectingSink(
                    run_id=context.run_id,
                    conversation_id=context.conversation_id,
                ),
                model=FunctionModel(
                    stream_function=asserting_stream,
                    model_name="transaction-boundary-model",
                ),
            )

        assert result.run.status == RUN_STATUS_COMPLETED
        assert dispatch_test_tools["read_ok"] == 1
    finally:
        await _delete_committed_runtime_context(committed_db_session_factory, context)


async def test_envelope_allows_external_write_with_explicit_scheduled_grant(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    dispatch_test_tools,
) -> None:
    context = await _create_committed_runtime_context(
        committed_db_session_factory,
        tool_names=["dispatch_write_ok"],
        trigger=RUN_TRIGGER_SCHEDULED,
        metadata={"envelope": {"side_effect_policy": "allow"}},
    )

    try:
        result = await _execute_single_tool(
            committed_db_session_factory,
            context,
            tool_name="dispatch_write_ok",
            args={"value": "allowed"},
        )

        assert result.run.status == RUN_STATUS_COMPLETED
        assert dispatch_test_tools["write_ok"] == 1
        [event] = await _tool_audit_events(
            committed_db_session_factory,
            context,
            tool_name="dispatch_write_ok",
        )
        assert event.status == "success"
        assert event.details["outcome"] == "completed"
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
    trigger: str = "interactive",
    metadata: dict[str, object] | None = None,
    role: WorkspaceRole = WorkspaceRole.MEMBER,
) -> DispatchRuntimeContext:
    async with session_factory() as db:
        user = build_user(email=f"runtime-dispatch-{uuid4().hex}@example.com")
        workspace = build_workspace(slug=f"runtime-dispatch-{uuid4().hex[:8]}")
        membership = build_workspace_membership(
            workspace_id=workspace.id,
            user_id=user.id,
            role=role,
        )
        db.add_all([user, workspace, membership])
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
            trigger=trigger,
            metadata={
                "audit_context": {
                    "request_id": "dispatch-test-request",
                    "ip_address": "203.0.113.24",
                    "user_agent": "dispatch-test-agent/1.0",
                },
                **(metadata or {}),
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
        await set_session_tenant_context(
            db,
            workspace_id=context.workspace_id,
            user_id=context.user_id,
        )
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
        await db.execute(delete(Classifier).where(Classifier.workspace_id == context.workspace_id))
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
    sink: CollectingSink | None = None,
):
    stream_function, _seen_messages = _single_tool_stream(
        tool_name=tool_name,
        args=args,
        final_text=final_text,
        seen_messages=seen_messages,
    )
    async with session_factory() as db:
        await set_session_tenant_context(
            db,
            workspace_id=context.workspace_id,
            user_id=context.user_id,
        )
        return await execute_run(
            db,
            conversation_id=context.conversation_id,
            run_id=context.run_id,
            user_prompt="Use the tool.",
            sink=sink
            or CollectingSink(
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


def _tool_result_content(messages: list[ModelMessage], tool_name: str):
    for message in messages:
        for part in message.parts:
            if (
                getattr(part, "part_kind", None) == "tool-return"
                and getattr(part, "tool_name", None) == tool_name
            ):
                return part.content
    raise AssertionError(f"No tool result found for {tool_name}")


async def _tool_audit_events(
    session_factory: async_sessionmaker[AsyncSession],
    context: DispatchRuntimeContext,
    *,
    tool_name: str,
) -> list[AuditEvent]:
    async with session_factory() as db:
        await set_session_tenant_context(
            db,
            workspace_id=context.workspace_id,
            user_id=context.user_id,
        )
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
