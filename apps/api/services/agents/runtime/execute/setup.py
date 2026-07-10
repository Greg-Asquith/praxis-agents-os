# apps/api/services/agents/runtime/execute/setup.py

"""Prepare database state, prompt content, and runtime deps for execute_run."""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from pydantic_ai import DeferredToolResults
from pydantic_ai.messages import ModelMessage, UserContent
from pydantic_ai.models import Model
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError
from models.agent import Agent
from models.agent_run import AgentRun
from models.conversation import Conversation
from models.skills import Skill
from models.workspace import Workspace
from services.agent_runs.domain import RUN_TRIGGER_DELEGATED
from services.agent_runs.start_with_lease import start_agent_run_with_lease
from services.agents.delegation_approval import (
    DELEGATED_APPROVAL_KIND,
    DELEGATED_APPROVAL_KIND_KEY,
)
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.delegation import list_visible_delegate_agents
from services.agents.runtime.dispatch import record_denied_approval_audit_events
from services.agents.runtime.envelope import RunEnvelope
from services.agents.runtime.load_context import AvailableFile, load_actor_context
from services.agents.runtime.loop import RuntimeAgent
from services.agents.runtime.persistence import load_message_history
from services.agents.runtime.sinks import EventSink
from services.files import build_attachment_user_content, resolve_chat_attachments

from .types import BuiltRuntimeAgent, PreparedRuntime


class RuntimeAgentBuilder(Protocol):
    def __call__(
        self,
        agent: Agent,
        *,
        model: Model | None = None,
        delegate_agents: Sequence[Agent] = (),
        enable_delegation: bool = True,
        force_delegation_tools: bool = False,
        skills: Sequence[Skill] = (),
        available_files: Sequence[AvailableFile] = (),
        skipped_tool_names: list[str] | None = None,
    ) -> RuntimeAgent: ...


class RunEnvelopeBuilder(Protocol):
    def __call__(self, run: AgentRun) -> RunEnvelope: ...


def validate_execution_preconditions(
    run: AgentRun,
    *,
    user_prompt: str | Sequence[UserContent] | None,
    message_history: Sequence[ModelMessage] | None,
    deferred_tool_results: DeferredToolResults | None,
    expected_status: str | None,
) -> None:
    if expected_status is not None and run.status != expected_status:
        raise ConflictError(
            "Agent run is not in the expected state for execution",
            conflicting_resource="agent_run",
            details={
                "run_id": str(run.id),
                "run_status": run.status,
                "expected_status": expected_status,
            },
        )
    if user_prompt is None and deferred_tool_results is None:
        raise ConflictError(
            "Agent run needs a prompt or deferred tool results",
            conflicting_resource="agent_run",
            details={"run_id": str(run.id)},
        )
    if deferred_tool_results is not None and message_history is None:
        raise ConflictError(
            "Agent run resume needs rehydrated message history",
            conflicting_resource="agent_run",
            details={"run_id": str(run.id)},
        )


async def start_run(
    db: AsyncSession,
    run: AgentRun,
    *,
    owner_instance_id: str | None,
) -> None:
    await start_agent_run_with_lease(
        db,
        run,
        owner_instance_id=owner_instance_id,
    )
    await db.commit()


async def prepare_runtime(
    db: AsyncSession,
    *,
    run: AgentRun,
    conversation: Conversation,
    agent: Agent,
    model: Model | None,
    event_sink: EventSink,
    user_prompt: str | Sequence[UserContent] | None,
    attachment_file_ids: Sequence[UUID],
    message_history: Sequence[ModelMessage] | None,
    deferred_tool_results: DeferredToolResults | None,
    skills: Sequence[Skill],
    available_files: Sequence[AvailableFile],
    runtime_agent_builder: RuntimeAgentBuilder,
    run_envelope_builder: RunEnvelopeBuilder,
) -> PreparedRuntime:
    user, workspace = await load_actor_context(db, run)
    prepared_prompt = await assemble_user_prompt(
        db,
        workspace=workspace,
        agent=agent,
        user_prompt=user_prompt,
        attachment_file_ids=attachment_file_ids,
    )
    built_agent = await build_agent_for_run(
        db,
        run=run,
        agent=agent,
        model=model,
        workspace=workspace,
        conversation=conversation,
        message_history=message_history,
        deferred_tool_results=deferred_tool_results,
        skills=skills,
        available_files=available_files,
        runtime_agent_builder=runtime_agent_builder,
    )
    deps = RuntimeDeps(
        db=db,
        user=user,
        workspace=workspace,
        conversation=conversation,
        agent=agent,
        run=run,
        sink=event_sink,
        envelope=run_envelope_builder(run),
        delegation_depth=run.delegation_depth or 0,
    )
    if deferred_tool_results is not None:
        await record_denied_approval_audit_events(
            deps=deps,
            message_history=built_agent.history,
            deferred_tool_results=deferred_tool_results,
        )
    return PreparedRuntime(
        user_prompt=prepared_prompt,
        built_agent=built_agent,
        deps=deps,
    )


async def assemble_user_prompt(
    db: AsyncSession,
    *,
    workspace: Workspace,
    agent: Agent,
    user_prompt: str | Sequence[UserContent] | None,
    attachment_file_ids: Sequence[UUID],
) -> str | Sequence[UserContent] | None:
    if not attachment_file_ids:
        return user_prompt

    attachment_files = await resolve_chat_attachments(
        db,
        workspace_id=workspace.id,
        agent=agent,
        file_ids=attachment_file_ids,
    )
    attachment_contents = await build_attachment_user_content(
        db,
        files=attachment_files,
    )
    if isinstance(user_prompt, str):
        return [user_prompt, *attachment_contents]
    if user_prompt is not None:
        return [*user_prompt, *attachment_contents]
    return user_prompt


async def build_agent_for_run(
    db: AsyncSession,
    *,
    run: AgentRun,
    agent: Agent,
    model: Model | None,
    workspace: Workspace,
    conversation: Conversation,
    message_history: Sequence[ModelMessage] | None,
    deferred_tool_results: DeferredToolResults | None,
    skills: Sequence[Skill],
    available_files: Sequence[AvailableFile],
    runtime_agent_builder: RuntimeAgentBuilder,
) -> BuiltRuntimeAgent:
    enable_delegation = run.trigger != RUN_TRIGGER_DELEGATED
    delegate_agents = (
        await list_visible_delegate_agents(db, caller=agent, workspace=workspace)
        if enable_delegation
        else []
    )
    # Pydantic AI still needs the original tool registered to resolve an approved deferred delegation; the tool body re-checks live policy.
    force_delegation_tools = has_delegated_deferred_results(deferred_tool_results)
    skipped_tool_names: list[str] = []
    runtime_agent = runtime_agent_builder(
        agent,
        model=model,
        delegate_agents=delegate_agents,
        enable_delegation=enable_delegation,
        force_delegation_tools=force_delegation_tools,
        skills=skills,
        available_files=available_files,
        skipped_tool_names=skipped_tool_names,
    )
    _record_skipped_runtime_tools(run, skipped_tool_names)
    if run.model_name is None:
        run.model_name = runtime_agent.resolved_model.qualified_id

    history = (
        list(message_history)
        if message_history is not None
        else await load_message_history(db, conversation_id=conversation.id)
    )
    await db.commit()
    return BuiltRuntimeAgent(runtime_agent=runtime_agent, history=history)


def _record_skipped_runtime_tools(run: AgentRun, skipped_tool_names: Sequence[str]) -> None:
    if not skipped_tool_names:
        return
    metadata = dict(run.metadata_json or {})
    existing = metadata.get("skipped_tool_names", [])
    existing_names = existing if isinstance(existing, list) else []
    metadata["skipped_tool_names"] = sorted(
        {
            *(name for name in existing_names if isinstance(name, str)),
            *skipped_tool_names,
        }
    )
    run.metadata_json = metadata


def has_delegated_deferred_results(
    deferred_tool_results: DeferredToolResults | None,
) -> bool:
    if deferred_tool_results is None:
        return False

    return any(
        isinstance(metadata, dict)
        and metadata.get(DELEGATED_APPROVAL_KIND_KEY) == DELEGATED_APPROVAL_KIND
        for metadata in deferred_tool_results.metadata.values()
    )
