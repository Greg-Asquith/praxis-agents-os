# apps/api/tests/services/agents/runtime/test_delegation.py

"""Runtime delegation tests for allowlists and child agent calls."""

import json
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.exceptions.general import NotFoundError
from models.agent import Agent
from models.agent_run import AgentRun
from models.conversation import Conversation, ConversationMessage
from models.session import Session
from models.user import User
from models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from services.agent_runs import create_agent_run, request_agent_run_cancellation
from services.agent_runs.domain import (
    RUN_STATUS_AWAITING_APPROVAL,
    RUN_STATUS_CANCELLED,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    RUN_TRIGGER_DELEGATED,
)
from services.agent_runs.get_approval_state import get_agent_run_approval_state
from services.agent_runs.resume_run_stream import resume_agent_run_stream
from services.agent_runs.schemas import (
    AgentRunResumeDecision,
    AgentRunResumeRequest,
)
from services.agents.runtime.delegation import (
    DELEGATE_NOT_ALLOWED_ERROR_CODE,
    delegate_to_agent,
    get_visible_delegate_agent,
    list_visible_delegate_agents,
)
from services.agents.runtime.envelope import RunEnvelope
from services.agents.runtime.events import EVENT_TOOL_APPROVAL_REQUIRED
from services.agents.runtime.execute_run import execute_run
from services.agents.runtime.sinks import CollectingSink
from services.agents.runtime.tools import build_runtime_tools
from services.conversations import get_conversation, list_conversations
from tests.factories import build_user, build_workspace

pytestmark = pytest.mark.asyncio


@dataclass(frozen=True)
class DelegationRuntimeContext:
    user_id: UUID
    workspace_id: UUID
    parent_agent_id: UUID
    child_agent_id: UUID
    conversation_id: UUID
    run_id: UUID


async def test_visible_delegate_agents_are_active_same_workspace_allowlist_members(
    db_session: AsyncSession,
) -> None:
    user = build_user(email=f"delegates-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"delegates-{uuid4().hex[:8]}")
    other_workspace = build_workspace(slug=f"delegates-other-{uuid4().hex[:8]}")
    db_session.add_all([user, workspace, other_workspace])
    await db_session.flush()

    caller = _agent("Caller", workspace_id=workspace.id, user_id=user.id)
    first = _agent("First Delegate", workspace_id=workspace.id, user_id=user.id)
    second = _agent("Second Delegate", workspace_id=workspace.id, user_id=user.id)
    inactive = _agent("Inactive Delegate", workspace_id=workspace.id, user_id=user.id)
    inactive.is_active = False
    deleted = _agent("Deleted Delegate", workspace_id=workspace.id, user_id=user.id)
    deleted.deleted = True
    other_workspace_agent = _agent(
        "Other Workspace Delegate",
        workspace_id=other_workspace.id,
        user_id=user.id,
    )
    db_session.add_all([caller, first, second, inactive, deleted, other_workspace_agent])
    await db_session.flush()
    caller.allowed_agent_ids = [
        str(second.id),
        str(caller.id),
        str(inactive.id),
        str(first.id),
        str(deleted.id),
        str(other_workspace_agent.id),
        str(first.id),
    ]
    await db_session.flush()

    delegates = await list_visible_delegate_agents(
        db_session,
        caller=caller,
        workspace=workspace,
    )

    assert [agent.id for agent in delegates] == [second.id, first.id]
    assert await get_visible_delegate_agent(
        db_session,
        caller=caller,
        workspace=workspace,
        target_agent_id=second.id,
    )
    with pytest.raises(NotFoundError):
        await get_visible_delegate_agent(
            db_session,
            caller=caller,
            workspace=workspace,
            target_agent_id=inactive.id,
        )


async def test_runtime_tools_append_delegation_tools_only_when_enabled(
    db_session: AsyncSession,
) -> None:
    user = build_user(email=f"delegate-tools-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"delegate-tools-{uuid4().hex[:8]}")
    db_session.add_all([user, workspace])
    await db_session.flush()

    agent = _agent("Tool Caller", workspace_id=workspace.id, user_id=user.id)
    agent.tool_names = ["test_runtime_context"]
    db_session.add(agent)
    await db_session.flush()

    base_tools = build_runtime_tools(agent)
    delegation_tools = build_runtime_tools(agent, include_delegation=True)

    assert [tool.name for tool in base_tools] == [
        "list_files",
        "promote_scratch",
        "read_file",
        "read_todos",
        "write_file",
        "write_todos",
        "test_runtime_context",
    ]
    assert [tool.name for tool in delegation_tools] == [
        "list_files",
        "promote_scratch",
        "read_file",
        "read_todos",
        "write_file",
        "write_todos",
        "test_runtime_context",
        "list_delegate_agents",
        "delegate_to_agent",
    ]


async def test_delegate_to_agent_enforces_envelope_depth_cap() -> None:
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            envelope=RunEnvelope(principal="delegated", max_delegation_depth=1),
            delegation_depth=1,
        ),
        tool_call_approved=False,
    )

    result = await delegate_to_agent(
        ctx,
        agent_id=uuid4(),
        task="Try to delegate again.",
    )

    assert result.status == "failed"
    assert result.error == "Delegation depth limit reached."


async def test_execute_run_can_delegate_to_child_agent_and_hide_child_from_list(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_context = await _create_committed_delegation_context(
        committed_db_session_factory,
    )
    sink = CollectingSink(
        run_id=runtime_context.run_id,
        conversation_id=runtime_context.conversation_id,
    )

    async def stream_delegate_flow(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        tool_names = {tool.name for tool in info.function_tools}
        if "list_delegate_agents" not in tool_names:
            yield "child result"
            return

        if not _has_tool_return(messages, "list_delegate_agents"):
            yield {
                0: DeltaToolCall(
                    name="list_delegate_agents",
                    json_args="{}",
                    tool_call_id="list-delegates",
                )
            }
            return

        if not _has_tool_return(messages, "delegate_to_agent"):
            yield {
                0: DeltaToolCall(
                    name="delegate_to_agent",
                    json_args=json.dumps(
                        {
                            "agent_id": str(runtime_context.child_agent_id),
                            "task": "Run the child task.",
                        }
                    ),
                    tool_call_id="delegate-child",
                )
            }
            return

        yield "parent final"

    monkeypatch.setattr(
        "services.agents.runtime.loop.build_model",
        lambda _resolved_model: FunctionModel(
            stream_function=stream_delegate_flow,
            model_name="delegate-flow",
        ),
    )

    try:
        async with committed_db_session_factory() as db:
            result = await execute_run(
                db,
                conversation_id=runtime_context.conversation_id,
                run_id=runtime_context.run_id,
                user_prompt="Use the specialist.",
                sink=sink,
            )

        assert result.output == "parent final"
        assert result.run.status == RUN_STATUS_COMPLETED

        async with committed_db_session_factory() as db:
            parent_run = await db.get(AgentRun, runtime_context.run_id)
            assert parent_run is not None
            child_runs = (
                await db.scalars(
                    select(AgentRun).where(AgentRun.parent_run_id == runtime_context.run_id)
                )
            ).all()
            assert len(child_runs) == 1
            child_run = child_runs[0]
            assert child_run.status == RUN_STATUS_COMPLETED, child_run.error_message
            assert child_run.trigger == RUN_TRIGGER_DELEGATED
            assert child_run.delegation_depth == 1
            assert child_run.agent_id == runtime_context.child_agent_id

            child_conversation = await db.get(Conversation, child_run.conversation_id)
            assert child_conversation is not None
            assert child_conversation.source == "delegated"
            assert child_conversation.active_agent_id == runtime_context.child_agent_id
            assert child_conversation.metadata_json["parent_run_id"] == str(runtime_context.run_id)

            parent_messages = (
                await db.scalars(
                    select(ConversationMessage)
                    .where(ConversationMessage.conversation_id == runtime_context.conversation_id)
                    .order_by(ConversationMessage.sequence)
                )
            ).all()
            child_messages = (
                await db.scalars(
                    select(ConversationMessage)
                    .where(ConversationMessage.conversation_id == child_conversation.id)
                    .order_by(ConversationMessage.sequence)
                )
            ).all()
            assert [message.role for message in parent_messages] == [
                "user",
                "assistant",
                "tool",
                "assistant",
                "tool",
                "assistant",
            ]
            assert [message.role for message in child_messages] == ["user", "assistant"]

            user = await db.get(User, runtime_context.user_id)
            workspace = await db.get(Workspace, runtime_context.workspace_id)
            assert user is not None
            assert workspace is not None
            listed = await list_conversations(
                db,
                actor=user,
                workspace=workspace,
                limit=20,
                offset=0,
            )
            assert [conversation.id for conversation in listed.conversations] == [
                runtime_context.conversation_id
            ]
            fetched_child = await get_conversation(
                db,
                actor=user,
                workspace=workspace,
                conversation_id=child_conversation.id,
            )
            assert fetched_child.id == child_conversation.id
            assert fetched_child.source == "delegated"
    finally:
        await _delete_committed_delegation_context(
            committed_db_session_factory,
            runtime_context,
        )


async def test_delegated_child_approval_is_visible_and_resumes_parent(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_context = await _create_committed_delegation_context(
        committed_db_session_factory,
        child_tool_names=["test_add_numbers"],
        child_tool_policies={"test_add_numbers": "approval"},
    )
    sink = CollectingSink(
        run_id=runtime_context.run_id,
        conversation_id=runtime_context.conversation_id,
    )

    async def stream_delegate_approval_flow(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        tool_names = {tool.name for tool in info.function_tools}
        if "list_delegate_agents" not in tool_names:
            if "test_add_numbers" in tool_names and not _has_tool_return(
                messages, "test_add_numbers"
            ):
                yield {
                    0: DeltaToolCall(
                        name="test_add_numbers",
                        json_args=json.dumps({"a": 2, "b": 3}),
                        tool_call_id="child-add",
                    )
                }
                return
            yield "child approved result"
            return

        if not _has_tool_return(messages, "list_delegate_agents"):
            yield {
                0: DeltaToolCall(
                    name="list_delegate_agents",
                    json_args="{}",
                    tool_call_id="list-delegates",
                )
            }
            return

        if not _has_tool_return(messages, "delegate_to_agent"):
            yield {
                0: DeltaToolCall(
                    name="delegate_to_agent",
                    json_args=json.dumps(
                        {
                            "agent_id": str(runtime_context.child_agent_id),
                            "task": "Add two numbers.",
                        }
                    ),
                    tool_call_id="delegate-child",
                )
            }
            return

        yield "parent final after approval"

    monkeypatch.setattr(
        "services.agents.runtime.loop.build_model",
        lambda _resolved_model: FunctionModel(
            stream_function=stream_delegate_approval_flow,
            model_name="delegate-approval-flow",
        ),
    )

    try:
        async with committed_db_session_factory() as db:
            suspended = await execute_run(
                db,
                conversation_id=runtime_context.conversation_id,
                run_id=runtime_context.run_id,
                user_prompt="Use the specialist.",
                sink=sink,
            )

        assert suspended.run.status == RUN_STATUS_AWAITING_APPROVAL
        approval_events = [
            event.data for event in sink.events if event.event == EVENT_TOOL_APPROVAL_REQUIRED
        ]
        assert [(event["tool_call_id"], event["name"]) for event in approval_events] == [
            ("child-add", "test_add_numbers")
        ]
        delegated_metadata = suspended.run.metadata_json["approval_state"][
            "deferred_tool_requests"
        ]["metadata"]["delegate-child"]
        assert approval_events[0]["delegation"] == {
            "parent_tool_call_id": "delegate-child",
            "child_agent_id": str(runtime_context.child_agent_id),
            "child_agent_name": "Child Delegate",
            "child_conversation_id": str(delegated_metadata["child_conversation_id"]),
            "child_run_id": str(delegated_metadata["child_run_id"]),
            "pending_approval_count": 1,
        }

        async with committed_db_session_factory() as db:
            parent_run = await db.get(AgentRun, runtime_context.run_id)
            assert parent_run is not None
            child_run = await db.scalar(
                select(AgentRun).where(AgentRun.parent_run_id == runtime_context.run_id)
            )
            assert child_run is not None
            assert child_run.status == RUN_STATUS_AWAITING_APPROVAL

            user = await db.get(User, runtime_context.user_id)
            workspace = await db.get(Workspace, runtime_context.workspace_id)
            assert user is not None
            assert workspace is not None
            approval_state = await get_agent_run_approval_state(
                db,
                actor=user,
                workspace=workspace,
                run_id=runtime_context.run_id,
            )
            assert len(approval_state.delegations) == 1
            assert approval_state.delegations[0].parent_tool_call_id == "delegate-child"
            assert approval_state.delegations[0].child_agent_id == runtime_context.child_agent_id
            assert approval_state.delegations[0].child_agent_name == "Child Delegate"
            assert approval_state.delegations[0].child_run_id == child_run.id
            assert approval_state.delegations[0].child_conversation_id == child_run.conversation_id
            assert approval_state.delegations[0].pending_approval_count == 1
            assert [
                (
                    approval.tool_call_id,
                    approval.name,
                    json.loads(approval.args) if isinstance(approval.args, str) else approval.args,
                )
                for approval in approval_state.approvals
            ] == [("child-add", "test_add_numbers", {"a": 2, "b": 3})]
            assert approval_state.approvals[0].delegation is not None
            assert approval_state.approvals[0].delegation.child_run_id == child_run.id
            assert approval_state.approvals[0].delegation.parent_tool_call_id == "delegate-child"

            response = await resume_agent_run_stream(
                db,
                actor=user,
                workspace=workspace,
                run_id=runtime_context.run_id,
                payload=AgentRunResumeRequest(
                    decisions=[
                        AgentRunResumeDecision(
                            tool_call_id="child-add",
                            decision="approved",
                        )
                    ]
                ),
            )

        body = await _read_streaming_response(response)
        assert "parent final after approval" in body

        async with committed_db_session_factory() as db:
            parent_run = await db.get(AgentRun, runtime_context.run_id)
            assert parent_run is not None
            child_run = await db.scalar(
                select(AgentRun).where(AgentRun.parent_run_id == runtime_context.run_id)
            )
            assert child_run is not None
            assert parent_run.status == RUN_STATUS_COMPLETED
            assert child_run.status == RUN_STATUS_COMPLETED

            parent_messages = (
                await db.scalars(
                    select(ConversationMessage)
                    .where(ConversationMessage.conversation_id == runtime_context.conversation_id)
                    .order_by(ConversationMessage.sequence)
                )
            ).all()
            assert parent_messages[-1].role == "assistant"
            assert "parent final after approval" in str(parent_messages[-1].parts)
    finally:
        await _delete_committed_delegation_context(
            committed_db_session_factory,
            runtime_context,
        )


async def test_cancelling_suspended_delegated_parent_cancels_child_approval_run(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_context = await _create_committed_delegation_context(
        committed_db_session_factory,
        child_tool_names=["test_add_numbers"],
        child_tool_policies={"test_add_numbers": "approval"},
    )
    sink = CollectingSink(
        run_id=runtime_context.run_id,
        conversation_id=runtime_context.conversation_id,
    )

    async def stream_delegate_approval_flow(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        tool_names = {tool.name for tool in info.function_tools}
        if "list_delegate_agents" not in tool_names:
            if "test_add_numbers" in tool_names and not _has_tool_return(
                messages, "test_add_numbers"
            ):
                yield {
                    0: DeltaToolCall(
                        name="test_add_numbers",
                        json_args=json.dumps({"a": 2, "b": 3}),
                        tool_call_id="child-add",
                    )
                }
                return
            yield "child approved result"
            return

        if not _has_tool_return(messages, "list_delegate_agents"):
            yield {
                0: DeltaToolCall(
                    name="list_delegate_agents",
                    json_args="{}",
                    tool_call_id="list-delegates",
                )
            }
            return

        if not _has_tool_return(messages, "delegate_to_agent"):
            yield {
                0: DeltaToolCall(
                    name="delegate_to_agent",
                    json_args=json.dumps(
                        {
                            "agent_id": str(runtime_context.child_agent_id),
                            "task": "Add two numbers.",
                        }
                    ),
                    tool_call_id="delegate-child",
                )
            }
            return

        yield "parent final after approval"

    monkeypatch.setattr(
        "services.agents.runtime.loop.build_model",
        lambda _resolved_model: FunctionModel(
            stream_function=stream_delegate_approval_flow,
            model_name="delegate-approval-cancel-flow",
        ),
    )

    try:
        async with committed_db_session_factory() as db:
            suspended = await execute_run(
                db,
                conversation_id=runtime_context.conversation_id,
                run_id=runtime_context.run_id,
                user_prompt="Use the specialist.",
                sink=sink,
            )

        assert suspended.run.status == RUN_STATUS_AWAITING_APPROVAL

        async with committed_db_session_factory() as db:
            user = await db.get(User, runtime_context.user_id)
            workspace = await db.get(Workspace, runtime_context.workspace_id)
            assert user is not None
            assert workspace is not None
            cancel_response = await request_agent_run_cancellation(
                db,
                actor=user,
                workspace=workspace,
                membership=WorkspaceMembership(
                    workspace_id=workspace.id,
                    user_id=user.id,
                    role=WorkspaceRole.OWNER.value,
                ),
                run_id=runtime_context.run_id,
            )

        assert cancel_response.run.status == RUN_STATUS_CANCELLED

        async with committed_db_session_factory() as db:
            parent_run = await db.get(AgentRun, runtime_context.run_id)
            assert parent_run is not None
            child_run = await db.scalar(
                select(AgentRun).where(AgentRun.parent_run_id == runtime_context.run_id)
            )
            assert child_run is not None
            assert parent_run.status == RUN_STATUS_CANCELLED
            assert child_run.status == RUN_STATUS_CANCELLED
    finally:
        await _delete_committed_delegation_context(
            committed_db_session_factory,
            runtime_context,
        )


async def test_delegated_child_approval_resume_rechecks_allowlist(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_context = await _create_committed_delegation_context(
        committed_db_session_factory,
        child_tool_names=["test_add_numbers"],
        child_tool_policies={"test_add_numbers": "approval"},
    )
    sink = CollectingSink(
        run_id=runtime_context.run_id,
        conversation_id=runtime_context.conversation_id,
    )
    child_resumed_after_approval = False

    async def stream_delegate_approval_flow(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        nonlocal child_resumed_after_approval

        tool_names = {tool.name for tool in info.function_tools}
        if "list_delegate_agents" not in tool_names:
            if "test_add_numbers" in tool_names and not _has_tool_return(
                messages, "test_add_numbers"
            ):
                yield {
                    0: DeltaToolCall(
                        name="test_add_numbers",
                        json_args=json.dumps({"a": 2, "b": 3}),
                        tool_call_id="child-add",
                    )
                }
                return
            child_resumed_after_approval = True
            yield "child should not resume"
            return

        if not _has_tool_return(messages, "list_delegate_agents"):
            yield {
                0: DeltaToolCall(
                    name="list_delegate_agents",
                    json_args="{}",
                    tool_call_id="list-delegates",
                )
            }
            return

        if not _has_tool_return(messages, "delegate_to_agent"):
            yield {
                0: DeltaToolCall(
                    name="delegate_to_agent",
                    json_args=json.dumps(
                        {
                            "agent_id": str(runtime_context.child_agent_id),
                            "task": "Add two numbers.",
                        }
                    ),
                    tool_call_id="delegate-child",
                )
            }
            return

        yield "parent handled delegated failure"

    monkeypatch.setattr(
        "services.agents.runtime.loop.build_model",
        lambda _resolved_model: FunctionModel(
            stream_function=stream_delegate_approval_flow,
            model_name="delegate-approval-revoked-flow",
        ),
    )

    try:
        async with committed_db_session_factory() as db:
            suspended = await execute_run(
                db,
                conversation_id=runtime_context.conversation_id,
                run_id=runtime_context.run_id,
                user_prompt="Use the specialist.",
                sink=sink,
            )

        assert suspended.run.status == RUN_STATUS_AWAITING_APPROVAL

        async with committed_db_session_factory() as db:
            parent_agent = await db.get(Agent, runtime_context.parent_agent_id)
            assert parent_agent is not None
            parent_agent.allowed_agent_ids = []
            await db.commit()

        async with committed_db_session_factory() as db:
            user = await db.get(User, runtime_context.user_id)
            workspace = await db.get(Workspace, runtime_context.workspace_id)
            assert user is not None
            assert workspace is not None
            response = await resume_agent_run_stream(
                db,
                actor=user,
                workspace=workspace,
                run_id=runtime_context.run_id,
                payload=AgentRunResumeRequest(
                    decisions=[
                        AgentRunResumeDecision(
                            tool_call_id="child-add",
                            decision="approved",
                        )
                    ]
                ),
            )

        body = await _read_streaming_response(response)
        assert "parent handled delegated failure" in body
        assert child_resumed_after_approval is False

        async with committed_db_session_factory() as db:
            parent_run = await db.get(AgentRun, runtime_context.run_id)
            assert parent_run is not None
            child_run = await db.scalar(
                select(AgentRun).where(AgentRun.parent_run_id == runtime_context.run_id)
            )
            assert child_run is not None
            assert parent_run.status == RUN_STATUS_COMPLETED
            assert child_run.status == RUN_STATUS_FAILED
            assert child_run.error_code == DELEGATE_NOT_ALLOWED_ERROR_CODE
    finally:
        await _delete_committed_delegation_context(
            committed_db_session_factory,
            runtime_context,
        )


def _agent(name: str, *, workspace_id: UUID, user_id: UUID) -> Agent:
    slug = name.lower().replace(" ", "-")
    return Agent(
        name=name,
        slug=f"{slug}-{uuid4().hex[:8]}",
        instructions=f"{name} instructions.",
        workspace_id=workspace_id,
        created_by=user_id,
        model_provider="openai",
        model="gpt-5.4-mini",
    )


def _has_tool_return(messages: list[ModelMessage], tool_name: str) -> bool:
    return any(
        getattr(part, "part_kind", None) == "tool-return"
        and getattr(part, "tool_name", None) == tool_name
        for message in messages
        for part in getattr(message, "parts", [])
    )


async def _read_streaming_response(response) -> str:
    chunks = [
        chunk.decode() if isinstance(chunk, bytes) else chunk
        async for chunk in response.body_iterator
    ]
    return "".join(chunks)


async def _create_committed_delegation_context(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    child_tool_names: list[str] | None = None,
    child_tool_policies: dict[str, str] | None = None,
) -> DelegationRuntimeContext:
    async with session_factory() as db:
        user = build_user(email=f"runtime-delegation-{uuid4().hex}@example.com")
        workspace = build_workspace(slug=f"runtime-delegation-{uuid4().hex[:8]}")
        db.add_all([user, workspace])
        await db.flush()

        child_agent = _agent("Child Delegate", workspace_id=workspace.id, user_id=user.id)
        child_agent.tool_names = child_tool_names or []
        child_agent.tool_policies = child_tool_policies
        parent_agent = _agent("Parent Caller", workspace_id=workspace.id, user_id=user.id)
        db.add_all([child_agent, parent_agent])
        await db.flush()
        parent_agent.allowed_agent_ids = [str(child_agent.id)]

        conversation = Conversation(
            user_id=user.id,
            workspace_id=workspace.id,
            created_by=user.id,
            active_agent_id=parent_agent.id,
        )
        db.add(conversation)
        await db.flush()

        run = await create_agent_run(
            db,
            conversation_id=conversation.id,
            agent_id=parent_agent.id,
            workspace_id=workspace.id,
            user_id=user.id,
            trigger="interactive",
        )
        await db.commit()

    return DelegationRuntimeContext(
        user_id=user.id,
        workspace_id=workspace.id,
        parent_agent_id=parent_agent.id,
        child_agent_id=child_agent.id,
        conversation_id=conversation.id,
        run_id=run.id,
    )


async def _delete_committed_delegation_context(
    session_factory: async_sessionmaker[AsyncSession],
    context: DelegationRuntimeContext,
) -> None:
    async with session_factory() as db:
        conversation_ids = (
            await db.scalars(
                select(Conversation.id).where(Conversation.workspace_id == context.workspace_id)
            )
        ).all()
        await db.execute(
            delete(ConversationMessage).where(
                ConversationMessage.conversation_id.in_(conversation_ids)
            )
        )
        await db.execute(delete(AgentRun).where(AgentRun.workspace_id == context.workspace_id))
        await db.execute(
            delete(Conversation).where(Conversation.workspace_id == context.workspace_id)
        )
        await db.execute(delete(Agent).where(Agent.workspace_id == context.workspace_id))
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
        with suppress(Exception):
            await db.commit()
