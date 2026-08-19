# apps/api/services/agents/runtime/execute/setup.py

"""Prepare database state, prompt content, and runtime deps for execute_run."""

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from pydantic_ai import DeferredToolResults
from pydantic_ai.messages import (
    ModelMessage,
    UserContent,
)
from pydantic_ai.models import Model
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError
from core.settings import settings
from models.agent import Agent
from models.agent_run import AgentRun
from models.conversation import Conversation
from models.skills import Skill
from models.workspace import Workspace
from services.agent_runs.domain import RUN_TRIGGER_DELEGATED, RUN_TRIGGER_SCHEDULED
from services.agent_runs.start_with_lease import start_agent_run_with_lease
from services.agents.delegation_approval import (
    DELEGATED_APPROVAL_KIND,
    DELEGATED_APPROVAL_KIND_KEY,
)
from services.agents.models import resolve_agent_model, resolve_model_context_budget
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.delegation import list_visible_delegate_agents
from services.agents.runtime.dispatch import record_denied_approval_audit_events
from services.agents.runtime.envelope import build_run_envelope
from services.agents.runtime.history import (
    HistoryCompaction,
    history_exceeds_context_budget,
    trim_boundary_count,
    trim_watermark_key,
)
from services.agents.runtime.load_context import AvailableFile, load_actor_context
from services.agents.runtime.loop import _runtime_instructions, build_runtime_agent
from services.agents.runtime.persistence import (
    load_history_watermark_keys,
    load_message_history,
)
from services.agents.runtime.prompt import render_conversation_context_block
from services.agents.runtime.sinks import EventSink
from services.agents.runtime.tools.contract import RuntimeToolDefinition
from services.agents.runtime.tools.workspace_tools import load_workspace_tool_definitions
from services.completion_contract import (
    REPORT_COMPLETION_TOOL_NAME,
    ScheduleCompletionContract,
    completion_contract_from_run_metadata,
    render_completion_contract_instructions,
)
from services.conversation_summaries.load_history_summary import load_history_summary
from services.files import build_attachment_user_content, resolve_chat_attachments
from services.integrations.context import resolve_active_context
from services.integrations.context.domain import EMPTY_ACTIVE_CONTEXT, ResolvedActiveContext
from services.memories.core_block import load_core_memories, render_core_memory_block
from services.tools import get_disabled_tools

from .types import BuiltRuntimeAgent, PreparedRuntime

logger = logging.getLogger(__name__)


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
) -> PreparedRuntime:
    user, workspace, membership = await load_actor_context(db, run)
    conversation_context_block = render_conversation_context_block(
        user=user,
        workspace=workspace,
    )
    core_memories = await load_core_memories(
        db,
        workspace=workspace,
        agent=agent,
        user=user,
    )
    core_memory_block = render_core_memory_block(
        core_memories,
        now=datetime.now(UTC),
        budget=settings.MEMORY_CORE_CHAR_BUDGET,
        line_max_chars=settings.MEMORY_CORE_LINE_MAX_CHARS,
    )
    try:
        active_context = await resolve_active_context(
            db,
            run=run,
            user=user,
            workspace=workspace,
        )
    except Exception:
        logger.exception(
            "Active integration context resolution failed; continuing without context",
            extra={"agent_run_id": str(run.id)},
        )
        active_context = EMPTY_ACTIVE_CONTEXT
    prepared_prompt = await assemble_user_prompt(
        db,
        workspace=workspace,
        agent=agent,
        user_prompt=user_prompt,
        attachment_file_ids=attachment_file_ids,
    )
    completion_contract = (
        completion_contract_from_run_metadata(run.metadata_json)
        if run.trigger == RUN_TRIGGER_SCHEDULED
        else None
    )
    completion_contract_block = render_completion_contract_instructions(completion_contract)
    completion_tool_names = (
        (REPORT_COMPLETION_TOOL_NAME,)
        if completion_contract is not None and completion_contract.required
        else ()
    )
    workspace_definitions = await load_workspace_tool_definitions(db, workspace)
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
        conversation_context_block=conversation_context_block,
        core_memory_block=core_memory_block,
        completion_contract_block=completion_contract_block,
        completion_contract=completion_contract,
        completion_tool_names=completion_tool_names,
        available_files=available_files,
        active_context=active_context,
        workspace_definitions=workspace_definitions,
    )
    deps = RuntimeDeps(
        db=db,
        user=user,
        workspace=workspace,
        membership=membership,
        conversation=conversation,
        agent=agent,
        run=run,
        sink=event_sink,
        envelope=build_run_envelope(run),
        delegation_depth=run.delegation_depth or 0,
        active_context=active_context,
        workspace_tool_definitions=tuple(workspace_definitions),
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
    conversation_context_block: str,
    core_memory_block: str,
    completion_contract_block: str,
    completion_contract: ScheduleCompletionContract | None,
    completion_tool_names: Sequence[str],
    available_files: Sequence[AvailableFile],
    active_context: ResolvedActiveContext,
    workspace_definitions: Sequence[RuntimeToolDefinition],
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
    disabled_tool_names = await get_disabled_tools(db, workspace)
    history = (
        list(message_history)
        if message_history is not None
        else await load_message_history(db, conversation_id=conversation.id)
    )
    history_compaction = await _prepare_history_compaction(
        db,
        agent=agent,
        conversation=conversation,
        history=history,
        include_delegation=enable_delegation,
        conversation_context_block=conversation_context_block,
        core_memory_block=core_memory_block,
        completion_contract_block=completion_contract_block,
        available_files=available_files,
        active_context=active_context,
        exclude_run_id=run.id if message_history is not None else None,
    )
    runtime_agent = build_runtime_agent(
        agent,
        model=model,
        delegate_agents=delegate_agents,
        enable_delegation=enable_delegation,
        force_delegation_tools=force_delegation_tools,
        skills=skills,
        conversation_context_block=conversation_context_block,
        core_memory_block=core_memory_block,
        completion_contract_block=completion_contract_block,
        completion_contract=completion_contract,
        available_files=available_files,
        active_context=active_context,
        skipped_tool_names=skipped_tool_names,
        workspace=workspace,
        disabled_tool_names=disabled_tool_names,
        additional_tool_names=completion_tool_names,
        workspace_definitions=workspace_definitions,
        history_compaction=history_compaction,
    )
    _record_skipped_runtime_tools(run, skipped_tool_names)
    run.model_name = runtime_agent.resolved_model.qualified_id

    await db.commit()
    return BuiltRuntimeAgent(runtime_agent=runtime_agent, history=history)


async def _prepare_history_compaction(
    db: AsyncSession,
    *,
    agent: Agent,
    conversation: Conversation,
    history: list[ModelMessage],
    include_delegation: bool,
    conversation_context_block: str,
    core_memory_block: str,
    completion_contract_block: str,
    available_files: Sequence[AvailableFile],
    active_context: ResolvedActiveContext,
    exclude_run_id: UUID | None,
) -> HistoryCompaction:
    max_turns = settings.AGENT_HISTORY_MAX_TURNS
    if max_turns is None:
        return HistoryCompaction()

    resolved_model = resolve_agent_model(agent)
    model_context = resolve_model_context_budget(resolved_model)
    system_prompt = _runtime_instructions(
        agent,
        include_delegation=include_delegation,
        conversation_context_block=conversation_context_block,
        core_memory_block=core_memory_block,
        completion_contract_block=completion_contract_block,
        available_files=available_files,
        active_context=active_context,
        chars_per_token=model_context.chars_per_token,
    )
    token_pressure = history_exceeds_context_budget(
        history,
        system_prompt=system_prompt,
        context_window=model_context.context_window,
        chars_per_token=model_context.chars_per_token,
        context_fraction=settings.AGENT_HISTORY_CONTEXT_FRACTION,
    )
    boundary_count = trim_boundary_count(history)
    boundary_keys = await load_history_watermark_keys(
        db,
        conversation_id=conversation.id,
        limit=boundary_count,
        exclude_run_id=exclude_run_id,
    )
    watermark_key = trim_watermark_key(
        history,
        max_turns=max_turns,
        keep_turns=settings.AGENT_HISTORY_KEEP_TURNS,
        token_pressure=token_pressure,
        boundary_keys=boundary_keys,
    )
    summary = await load_history_summary(
        db,
        conversation_id=conversation.id,
        watermark_key=watermark_key,
    )
    return HistoryCompaction(
        summary=summary,
        token_pressure=token_pressure,
        boundary_keys=boundary_keys,
    )


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
