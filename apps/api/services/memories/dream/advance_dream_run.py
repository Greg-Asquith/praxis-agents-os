# apps/api/services/memories/dream/advance_dream_run.py

"""Advance one dream run by one step: collect, extract, or consolidate and apply."""

import asyncio
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic_ai import Agent as HelperAgent
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.agent import Agent
from models.agent_memories import AgentMemory
from models.jobs import Job
from models.memory_dream_run import MemoryDreamRun
from models.user import User
from models.workspace import Workspace
from services.agents.models import build_model, resolve_dream_model
from services.agents.runtime.persistence import load_message_history_span
from services.ai_usage.domain import PURPOSE_MEMORY_DREAMING, AIUsageEventData
from services.ai_usage.run_metered_helper import run_metered_helper
from services.ai_usage.utils import usage_values
from services.audit_events.enums import AuditAction, AuditActorType, AuditResourceType
from services.audit_events.operations import safe_record_operation_audit_event
from services.conversation_review import collect_finished_conversations, render_transcript
from services.memories.domain import MEMORY_KIND_CORE, MEMORY_SCOPE_WORKSPACE, MemoryScope
from services.memories.dream.apply_dream_operations import apply_dream_operations
from services.memories.dream.domain import (
    DREAM_AUDIT_ACTOR,
    DREAM_ERROR_DISABLED,
    DREAM_STATUS_APPLYING,
    DREAM_STATUS_COLLECTING,
    DREAM_STATUS_COMPLETED,
    DREAM_STATUS_CONSOLIDATING,
    DREAM_STATUS_EXTRACTING,
    DREAM_STATUS_FAILED,
    EXTRACTION_CONCURRENCY,
    FINAL_DREAM_STATUSES,
    MAX_CANDIDATES_PER_CONVERSATION,
    DreamConsolidation,
    DreamExtraction,
    DreamScopeRequest,
    DreamScopeTarget,
    DreamStepError,
)
from services.memories.dream.prompts import (
    CONSOLIDATION_INSTRUCTIONS,
    consolidation_prompt,
    extraction_request,
)
from services.memories.dream.utils import (
    conversation_scope,
    duplicate_pairs,
    enqueue_dream_step,
    is_protected_memory,
    move_dream_run,
    nearest_memories,
    previous_read_end,
)
from services.memories.utils import active_memory_filter, scope_filter, try_embed_memory

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _DreamModel:
    model: Model
    provider: str
    name: str


@dataclass(frozen=True)
class _ModelCall:
    instructions: str
    prompt: str
    event: AIUsageEventData


async def advance_dream_run(db: AsyncSession, job: Job, *, model: Model | None = None) -> None:
    """Runs the step the job was queued for and queues the next one.

    A job whose status no longer matches the run is a repeat and changes nothing.
    """
    run = await db.scalar(
        select(MemoryDreamRun)
        .where(MemoryDreamRun.id == job.subject_id, MemoryDreamRun.workspace_id == job.workspace_id)
        .with_for_update()
    )
    if run is None or run.status != job.payload.get("status"):
        return
    now = datetime.now(UTC)
    if not settings.MEMORY_DREAM_ENABLED:
        move_dream_run(run, DREAM_STATUS_FAILED, now=now, error_code=DREAM_ERROR_DISABLED)
        await db.flush()
        return
    workspace = await db.get(Workspace, run.workspace_id)
    if run.status == DREAM_STATUS_COLLECTING:
        await _collect(db, run, workspace=workspace, now=now)
    elif run.status == DREAM_STATUS_EXTRACTING:
        await _extract(db, run, workspace=workspace, model=_dream_model(model))
    elif run.status == DREAM_STATUS_CONSOLIDATING:
        await _consolidate_and_apply(db, run, workspace=workspace, model=_dream_model(model))
    if run.status in FINAL_DREAM_STATUSES:
        await _audit_finished_run(db, run)
    else:
        await enqueue_dream_step(db, run)
    await db.flush()


async def _collect(
    db: AsyncSession, run: MemoryDreamRun, *, workspace: Workspace, now: datetime
) -> None:
    """Records the conversations to read and the message span read from each."""
    limit = settings.MEMORY_DREAM_MAX_CONVERSATIONS
    found = await collect_finished_conversations(
        db,
        workspace_id=workspace.id,
        window_start=run.window_start,
        window_end=run.window_end,
        limit=limit + 1,
    )
    if len(found) > limit:
        # Leave the rest for the next dream by ending the window before them.
        run.window_end = found[limit].first_finished_at - timedelta(microseconds=1)
        found = found[:limit]
    entries: list[dict[str, Any]] = []
    for conversation in found:
        start = await previous_read_end(
            db, workspace_id=workspace.id, conversation_id=conversation.id
        )
        if start is not None and start >= conversation.end_sequence:
            continue
        entries.append(
            {
                "ref": f"k{len(entries) + 1}",
                "id": str(conversation.id),
                "user_id": str(conversation.user_id),
                "agent_id": str(conversation.agent_id),
                "visibility": conversation.visibility,
                "start_sequence": start,
                "end_sequence": conversation.end_sequence,
                "extracted": False,
                "candidates": [],
            }
        )
    run.conversations = entries
    move_dream_run(run, DREAM_STATUS_EXTRACTING if entries else DREAM_STATUS_COMPLETED, now=now)


async def _extract(
    db: AsyncSession, run: MemoryDreamRun, *, workspace: Workspace, model: _DreamModel
) -> None:
    """Asks the model what each conversation showed is worth remembering. Writes no memory."""
    known_by_scope: dict[tuple[MemoryScope, UUID | None], list[tuple[str, str]]] = {}
    calls: list[_ModelCall] = []
    for entry in run.conversations:
        scope, user_id = conversation_scope(workspace, entry)
        if (scope, user_id) not in known_by_scope:
            known_by_scope[(scope, user_id)] = await _known_core_memories(
                db, workspace=workspace, scope=scope, entry=entry
            )
        messages = await load_message_history_span(
            db,
            conversation_id=UUID(entry["id"]),
            start_sequence=entry["start_sequence"],
            end_sequence=entry["end_sequence"],
        )
        transcript = render_transcript(
            messages,
            source_ref=f"{entry['id']}:{entry['end_sequence']}",
            max_chars=settings.MEMORY_DREAM_TRANSCRIPT_MAX_CHARS,
        )
        instructions, prompt = extraction_request(
            transcript=transcript,
            known=known_by_scope[(scope, user_id)],
            workspace_visible=scope == MEMORY_SCOPE_WORKSPACE,
        )
        calls.append(
            _ModelCall(
                instructions=instructions,
                prompt=prompt,
                event=_usage_event(
                    model,
                    workspace=workspace,
                    agent_id=UUID(entry["agent_id"]),
                    user_id=UUID(entry["user_id"]),
                    conversation_id=UUID(entry["id"]),
                ),
            )
        )
    outputs = await _call_all(run, model, DreamExtraction, calls)
    if all(output is None for output in outputs):
        raise DreamStepError("Every extraction call failed")
    run.conversations = [
        {
            **entry,
            "extracted": output is not None,
            "candidates": (
                [
                    candidate.model_dump(mode="json")
                    for candidate in output.memories[:MAX_CANDIDATES_PER_CONVERSATION]
                ]
                if output is not None
                else []
            ),
        }
        for entry, output in zip(run.conversations, outputs, strict=True)
    ]
    move_dream_run(run, DREAM_STATUS_CONSOLIDATING, now=datetime.now(UTC))


async def _consolidate_and_apply(
    db: AsyncSession, run: MemoryDreamRun, *, workspace: Workspace, model: _DreamModel
) -> None:
    """Asks for one scope's operations at a time, then applies them all in this transaction."""
    groups: dict[tuple[MemoryScope, UUID | None], list[Mapping[str, Any]]] = {}
    for entry in run.conversations:
        if entry["extracted"]:
            groups.setdefault(conversation_scope(workspace, entry), []).append(entry)
    requests: list[DreamScopeRequest] = []
    calls: list[_ModelCall] = []
    for (scope, user_id), entries in groups.items():
        agent = await db.get(Agent, UUID(entries[0]["agent_id"]))
        user = await db.get(User, user_id or UUID(entries[0]["user_id"]))
        target = DreamScopeTarget(workspace=workspace, scope=scope, agent=agent, user=user)
        built = await _consolidation_request(db, run, target=target, entries=entries)
        if built is None:
            continue
        request, prompt = built
        requests.append(request)
        calls.append(
            _ModelCall(
                instructions=CONSOLIDATION_INSTRUCTIONS,
                prompt=prompt,
                event=_usage_event(model, workspace=workspace, agent_id=agent.id, user_id=user.id),
            )
        )
    outputs = await _call_all(run, model, DreamConsolidation, calls)
    if calls and all(output is None for output in outputs):
        raise DreamStepError("Every consolidation call failed")
    now = datetime.now(UTC)
    move_dream_run(run, DREAM_STATUS_APPLYING, now=now)
    for request, output in zip(requests, outputs, strict=True):
        if output is not None:
            await apply_dream_operations(
                db,
                run=run,
                request=request,
                operations=output.operations,
                max_operations=settings.MEMORY_DREAM_MAX_OPERATIONS_PER_SCOPE,
            )
    move_dream_run(run, DREAM_STATUS_COMPLETED, now=now)


async def _consolidation_request(
    db: AsyncSession,
    run: MemoryDreamRun,
    *,
    target: DreamScopeTarget,
    entries: Sequence[Mapping[str, Any]],
) -> tuple[DreamScopeRequest, str] | None:
    """Builds what the model sees for one scope, or None when there's nothing to decide."""
    target_filter = scope_filter(
        target.scope,
        workspace_id=target.workspace.id,
        agent_id=target.agent.id,
        user_id=target.user.id,
    )
    candidates = [
        {"conversation": entry["ref"], **candidate}
        for entry in entries
        for candidate in entry["candidates"]
    ]
    shown: dict[UUID, AgentMemory] = {}
    for candidate in candidates:
        embedded = await try_embed_memory(
            db,
            workspace_id=target.workspace.id,
            title=candidate["title"],
            content_md=candidate["content_md"],
            agent_id=target.agent.id,
            user_id=target.user.id,
        )
        if embedded is not None:
            for memory in await nearest_memories(
                db, target_filter=target_filter, embedded=embedded
            ):
                shown.setdefault(memory.id, memory)
    pairs = await duplicate_pairs(db, target_filter=target_filter)
    if not candidates and not pairs:
        return None
    missing = {memory_id for pair in pairs for memory_id in pair} - shown.keys()
    if missing:
        for memory in await db.scalars(select(AgentMemory).where(AgentMemory.id.in_(missing))):
            shown[memory.id] = memory
    references = {memory_id: f"m{index}" for index, memory_id in enumerate(shown, start=1)}
    memories = [
        {
            "ref": references[memory.id],
            "title": memory.title,
            "content": memory.content_md,
            "type": memory.memory_type,
            "read_only": is_protected_memory(memory),
        }
        for memory in shown.values()
    ]
    prompt = consolidation_prompt(
        memories=memories,
        pairs=[(references[first], references[second]) for first, second in pairs],
        candidates=candidates,
        source_ref=str(run.id),
    )
    request = DreamScopeRequest(
        target=target,
        memories={reference: memory_id for memory_id, reference in references.items()},
        conversations={entry["ref"]: UUID(entry["id"]) for entry in entries},
    )
    return request, prompt


async def _known_core_memories(
    db: AsyncSession, *, workspace: Workspace, scope: MemoryScope, entry: Mapping[str, Any]
) -> list[tuple[str, str]]:
    rows = await db.execute(
        select(AgentMemory.title, AgentMemory.content_md)
        .where(
            scope_filter(
                scope,
                workspace_id=workspace.id,
                agent_id=UUID(entry["agent_id"]),
                user_id=UUID(entry["user_id"]),
            ),
            AgentMemory.kind == MEMORY_KIND_CORE,
            active_memory_filter(),
        )
        .order_by(AgentMemory.created_at, AgentMemory.id)
    )
    return list(rows.tuples())


async def _call_all[T](
    run: MemoryDreamRun,
    model: _DreamModel,
    output_type: type[T],
    calls: Sequence[_ModelCall],
) -> list[T | None]:
    """Runs the calls a few at a time; a failed call returns None and changes nothing."""
    semaphore = asyncio.Semaphore(EXTRACTION_CONCURRENCY)
    usages: list[RunUsage] = []

    async def one(call: _ModelCall) -> T | None:
        helper = HelperAgent(
            model.model,
            name="memory_dream",
            output_type=output_type,
            instructions=call.instructions,
        )

        async def run_helper(usage: RunUsage) -> T:
            usages.append(usage)
            return (await helper.run(call.prompt, usage=usage)).output

        async with semaphore:
            try:
                return await run_metered_helper(call.event, run_helper)
            except Exception:
                logger.warning(
                    "Dream model call failed; it changes nothing",
                    exc_info=True,
                    extra={"dream_run_id": str(run.id), "output": output_type.__name__},
                )
                return None

    outputs = await asyncio.gather(*(one(call) for call in calls))
    totals = dict(run.usage_totals)
    for usage in usages:
        for name, value in usage_values(usage).items():
            totals[name] = totals.get(name, 0) + value
    run.usage_totals = totals
    return list(outputs)


def _dream_model(model: Model | None) -> _DreamModel:
    if model is not None:
        return _DreamModel(model=model, provider=model.system, name=model.model_name)
    resolved = resolve_dream_model()
    return _DreamModel(model=build_model(resolved), provider=resolved.provider, name=resolved.model)


def _usage_event(
    model: _DreamModel,
    *,
    workspace: Workspace,
    agent_id: UUID,
    user_id: UUID,
    conversation_id: UUID | None = None,
) -> AIUsageEventData:
    return AIUsageEventData(
        workspace_id=workspace.id,
        provider=model.provider,
        model=model.name,
        purpose=PURPOSE_MEMORY_DREAMING,
        agent_id=agent_id,
        user_id=user_id,
        conversation_id=conversation_id,
    )


async def _audit_finished_run(db: AsyncSession, run: MemoryDreamRun) -> None:
    await safe_record_operation_audit_event(
        db,
        workspace_id=run.workspace_id,
        action=AuditAction.EXECUTE,
        resource_type=AuditResourceType.MEMORY_DREAM_RUN,
        resource_id=run.id,
        actor_type=AuditActorType.SERVICE,
        actor_display=DREAM_AUDIT_ACTOR,
        details={
            "event": run.status,
            "error_code": run.error_code,
            "conversations_read": sum(1 for entry in run.conversations if entry["extracted"]),
            "operation_counts": run.operation_counts,
        },
    )
