# apps/api/tests/support/scenario.py

"""Small, declarative helpers for end-to-end agent runtime scenarios.

Pydantic AI 2.1.0 probe: ``execute_run`` uses streamed requests, so
``FunctionModel`` needs ``stream_function``. It receives ``(messages,
AgentInfo)`` once per model request; yielding ``DeltaToolCall`` values drives
real tool execution and the next declared turn follows tool results or resume.
"""

import json
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic_ai import DeferredToolResults
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai.usage import RunUsage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.agent import Agent
from models.agent_run import AgentRun
from models.audit_event import AuditEvent
from models.conversation import ConversationMessage
from models.workspace import WorkspaceRole
from services.agent_runs import create_agent_run
from services.agent_runs.domain import RUN_STATUS_PENDING
from services.agents.runtime.execute.types import ExecuteRunResult
from services.agents.runtime.execute_run import execute_run
from services.agents.runtime.sinks import CollectingSink, SinkEvent
from tests.factories import (
    build_conversation,
    build_user,
    build_workspace,
    build_workspace_membership,
)


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: Mapping[str, Any]
    call_id: str | None = None


@dataclass(frozen=True)
class ToolTurn:
    calls: tuple[ToolCall, ...]


type ScriptedTurn = str | ToolTurn


@dataclass(frozen=True)
class ScenarioContext:
    user_id: UUID
    workspace_id: UUID
    agent_id: UUID
    conversation_id: UUID
    run_id: UUID
    agent: Agent


@dataclass(frozen=True)
class ScenarioResult:
    run: AgentRun
    output: Any
    execute_result: ExecuteRunResult
    events: list[SinkEvent]
    messages: list[ConversationMessage]
    audit_rows: list[AuditEvent]

    def event_names(self) -> list[str]:
        return [event.event for event in self.events]

    def tool_calls(self, name: str | None = None) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []
        for message in self.messages:
            for value in _walk_json(message.parts):
                if not isinstance(value, dict) or "tool_name" not in value:
                    continue
                if value.get("part_kind") not in {"tool-call", "builtin-tool-call"}:
                    continue
                if name is None or value.get("tool_name") == name:
                    calls.append(value)
        return calls


async def build_scenario_agent(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    instructions: str = "Reply plainly and use configured tools when needed.",
    tool_names: Sequence[str] = (),
    tool_policies: Mapping[str, str] | None = None,
    allowed_agent_ids: Sequence[UUID] = (),
    trigger: Literal["interactive", "scheduled", "delegated"] = "interactive",
    metadata: dict[str, Any] | None = None,
    role: WorkspaceRole = WorkspaceRole.MEMBER,
    code_mode_enabled: bool = False,
) -> ScenarioContext:
    """Persist the minimum real workspace graph needed by ``execute_run``."""
    async with session_factory() as db:
        suffix = uuid4().hex
        user = build_user(email=f"scenario-{suffix}@example.com")
        workspace = build_workspace(slug=f"scenario-{suffix[:12]}")
        db.add_all([user, workspace])
        await db.flush()
        db.add(
            build_workspace_membership(
                workspace_id=workspace.id,
                user_id=user.id,
                role=role,
            )
        )
        agent = Agent(
            name="Scenario Agent",
            slug=f"scenario-agent-{suffix[:12]}",
            instructions=instructions,
            workspace_id=workspace.id,
            created_by=user.id,
            tool_names=list(tool_names),
            tool_policies=dict(tool_policies) if tool_policies else None,
            code_mode_enabled=code_mode_enabled,
            allowed_agent_ids=[str(value) for value in allowed_agent_ids],
            model_provider="openai",
            model="gpt-5.4-mini",
        )
        db.add(agent)
        await db.flush()
        conversation = build_conversation(user=user, workspace=workspace, active_agent_id=agent.id)
        db.add(conversation)
        await db.flush()
        run = await create_agent_run(
            db,
            conversation_id=conversation.id,
            agent_id=agent.id,
            workspace_id=workspace.id,
            user_id=user.id,
            trigger=trigger,
            metadata=metadata,
        )
        await db.commit()
        return ScenarioContext(
            user_id=user.id,
            workspace_id=workspace.id,
            agent_id=agent.id,
            conversation_id=conversation.id,
            run_id=run.id,
            agent=agent,
        )


async def add_scenario_delegate(
    session_factory: async_sessionmaker[AsyncSession],
    context: ScenarioContext,
    *,
    tool_names: Sequence[str] = (),
) -> Agent:
    """Add one allowed child agent to an existing scenario graph."""
    async with session_factory() as db:
        parent = await db.get(Agent, context.agent_id)
        assert parent is not None
        child = Agent(
            name="Scenario Delegate",
            slug=f"scenario-delegate-{uuid4().hex[:12]}",
            instructions="Complete the delegated task and return a concise result.",
            workspace_id=context.workspace_id,
            created_by=context.user_id,
            tool_names=list(tool_names),
            allowed_agent_ids=[],
            model_provider="openai",
            model="gpt-5.4-mini",
        )
        db.add(child)
        await db.flush()
        parent.allowed_agent_ids = [str(child.id)]
        await db.commit()
        return child


async def next_scenario_run(
    session_factory: async_sessionmaker[AsyncSession],
    context: ScenarioContext,
) -> ScenarioContext:
    """Create the next interactive run in an existing scenario conversation."""
    async with session_factory() as db:
        run = await create_agent_run(
            db,
            conversation_id=context.conversation_id,
            agent_id=context.agent_id,
            workspace_id=context.workspace_id,
            user_id=context.user_id,
            trigger="interactive",
        )
        await db.commit()
    return replace(context, run_id=run.id)


def scripted_model(
    *,
    turns: Sequence[ScriptedTurn],
    name: str = "scenario-script",
    seen_requests: list[tuple[list[ModelMessage], AgentInfo]] | None = None,
) -> FunctionModel:
    """Return a deterministic model whose model requests consume declared turns."""
    declared = tuple(turns)
    cursor = 0

    async def stream(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        nonlocal cursor
        if seen_requests is not None:
            seen_requests.append((list(messages), info))
        if cursor >= len(declared):
            raise AssertionError("Scripted model received more requests than declared turns")
        turn = declared[cursor]
        cursor += 1
        if isinstance(turn, str):
            yield turn
            return
        yield {
            index: DeltaToolCall(
                name=call.name,
                json_args=json.dumps(dict(call.args)),
                tool_call_id=call.call_id or f"{call.name}-{cursor}-{index}",
            )
            for index, call in enumerate(turn.calls)
        }

    return FunctionModel(stream_function=stream, model_name=name)


async def run_scenario(
    session_factory: async_sessionmaker[AsyncSession],
    context: ScenarioContext,
    *,
    model: Model,
    prompt: str | None = "Run the scenario.",
    expected_status: str | None = RUN_STATUS_PENDING,
    message_history: Sequence[ModelMessage] | None = None,
    deferred_tool_results: DeferredToolResults | None = None,
    usage: RunUsage | None = None,
    attachment_file_ids: Sequence[UUID] = (),
    sink: CollectingSink | None = None,
) -> ScenarioResult:
    """Execute one real runtime turn and collect its durable evidence."""
    event_sink = sink or CollectingSink(
        run_id=context.run_id,
        conversation_id=context.conversation_id,
    )
    async with session_factory() as db:
        result = await execute_run(
            db,
            conversation_id=context.conversation_id,
            run_id=context.run_id,
            user_prompt=prompt,
            attachment_file_ids=attachment_file_ids,
            sink=event_sink,
            model=model,
            expected_status=expected_status,
            message_history=message_history,
            deferred_tool_results=deferred_tool_results,
            usage=usage,
        )

    async with session_factory() as db:
        run = await db.get(AgentRun, context.run_id)
        assert run is not None
        messages = list(
            (
                await db.scalars(
                    select(ConversationMessage)
                    .where(ConversationMessage.conversation_id == context.conversation_id)
                    .order_by(ConversationMessage.sequence)
                )
            ).all()
        )
        audit_rows = list(
            (
                await db.scalars(
                    select(AuditEvent)
                    .where(AuditEvent.details["run_id"].astext == str(context.run_id))
                    .order_by(AuditEvent.occurred_at, AuditEvent.id)
                )
            ).all()
        )
    return ScenarioResult(
        run=run,
        output=result.output,
        execute_result=result,
        events=list(event_sink.events),
        messages=messages,
        audit_rows=audit_rows,
    )


def _walk_json(value: Any):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)
