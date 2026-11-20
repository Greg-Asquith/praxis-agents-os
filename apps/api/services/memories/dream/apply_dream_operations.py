# apps/api/services/memories/dream/apply_dream_operations.py

"""Validate and apply one scope's dream operations through the memory write services."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError, ConflictError
from core.settings import settings
from models.agent_memories import AgentMemory
from models.memory_dream_run import MemoryDreamRun
from services.audit_events.enums import AuditAction, AuditActorType, AuditResourceType
from services.audit_events.operations import safe_record_operation_audit_event
from services.memories.domain import (
    ARCHIVE_REASON_CONSOLIDATED,
    MEMORY_CREATED_BY_SYSTEM,
    MEMORY_KIND_NOTE,
    MEMORY_SOURCE_DREAM,
    MEMORY_STATUS_ARCHIVED,
    MEMORY_STATUS_SUPERSEDED,
    MemoryProvenance,
)
from services.memories.dream.domain import (
    DREAM_AUDIT_ACTOR,
    DREAM_STATUS_APPLYING,
    REJECT_SCOPE_MISMATCH,
    SKIP_EMBEDDING_UNAVAILABLE,
    SKIP_INVALID_CONTENT,
    SKIP_NEAR_DUPLICATE,
    SKIP_OVER_LIMIT,
    SKIP_PROTECTED,
    SKIP_REMOVED_BY_PERSON,
    SKIP_STALE,
    DreamApplyResult,
    DreamCreate,
    DreamMerge,
    DreamOperation,
    DreamReinforce,
    DreamRetire,
    DreamRevise,
    DreamScopeRequest,
)
from services.memories.dream.utils import (
    conversations_fit_scope,
    find_reference_problem,
    is_protected_memory,
    matches_removed_memory,
    named_memories,
)
from services.memories.save_memory import save_memory
from services.memories.utils import (
    active_memory_filter,
    lock_memory_scope,
    scope_filter,
    try_embed_memory,
    validate_memory_content,
)


async def apply_dream_operations(
    db: AsyncSession,
    *,
    run: MemoryDreamRun,
    request: DreamScopeRequest,
    operations: Sequence[DreamOperation],
    max_operations: int,
) -> DreamApplyResult:
    """Apply one scope's operations once per run, writing nothing for an unusable response.

    The caller commits; the run row lock and the scope lock last until then.
    """
    await db.flush()
    await db.refresh(run, with_for_update=True)
    if run.status != DREAM_STATUS_APPLYING:
        raise ConflictError(
            "Dream operations apply only while the run is applying",
            conflicting_resource="memory_dream_run",
            details={"dream_run_id": str(run.id), "status": run.status},
        )
    key = request.target.key
    if key in run.applied_scopes:
        return DreamApplyResult(already_applied=True)
    run.applied_scopes = [*run.applied_scopes, key]

    result = DreamApplyResult(rejected=find_reference_problem(request, operations))
    if result.rejected is None and not await conversations_fit_scope(db, request):
        result.rejected = REJECT_SCOPE_MISMATCH
    if result.rejected is None:
        await _apply_all(
            db,
            run=run,
            request=request,
            operations=operations,
            result=result,
            max_operations=max_operations,
        )
    counts = dict(run.operation_counts)
    for op, count in result.applied.items():
        counts[op] = counts.get(op, 0) + count
    for reason, count in result.skipped.items():
        counts[f"skipped_{reason}"] = counts.get(f"skipped_{reason}", 0) + count
    if result.rejected is not None:
        counts[f"rejected_{result.rejected}"] = counts.get(f"rejected_{result.rejected}", 0) + 1
    run.operation_counts = counts
    await db.flush()
    return result


async def _apply_all(
    db: AsyncSession,
    *,
    run: MemoryDreamRun,
    request: DreamScopeRequest,
    operations: Sequence[DreamOperation],
    result: DreamApplyResult,
    max_operations: int,
) -> None:
    target = request.target
    await lock_memory_scope(
        db,
        workspace_id=target.workspace.id,
        agent_id=target.agent.id,
        user_id=target.user.id,
        scope=target.scope,
        kind=MEMORY_KIND_NOTE,
    )
    rows = await db.scalars(
        select(AgentMemory)
        .where(
            AgentMemory.id.in_(set(request.memories.values())),
            scope_filter(
                target.scope,
                workspace_id=target.workspace.id,
                agent_id=target.agent.id,
                user_id=target.user.id,
            ),
            active_memory_filter(),
        )
        .with_for_update()
    )
    active = {memory.id: memory for memory in rows}
    supplied = {
        reference: active.get(memory_id) for reference, memory_id in request.memories.items()
    }
    if len(operations) > max_operations:
        result.skipped[SKIP_OVER_LIMIT] += len(operations) - max_operations
    for operation in operations[:max_operations]:
        skipped = await _apply_one(
            db, run=run, request=request, supplied=supplied, operation=operation
        )
        if skipped is None:
            result.applied[operation.op] += 1
        else:
            result.skipped[skipped] += 1


async def _apply_one(
    db: AsyncSession,
    *,
    run: MemoryDreamRun,
    request: DreamScopeRequest,
    supplied: Mapping[str, AgentMemory | None],
    operation: DreamOperation,
) -> str | None:
    """Apply one operation, or return why it changed nothing."""
    sources = [supplied[reference] for reference in named_memories(operation)]
    if any(source is None for source in sources):
        return SKIP_STALE
    named = [source for source in sources if source is not None]
    if any(is_protected_memory(source) for source in named):
        return SKIP_PROTECTED
    now = datetime.now(UTC)
    if isinstance(operation, DreamReinforce):
        memory = named[0]
        memory.confidence = min(
            1.0, float(memory.confidence) + settings.MEMORY_REINFORCE_CONFIDENCE_STEP
        )
        memory.last_reinforced_at = now
        memory.reinforcement_count += 1
        await _audit(db, run=run, memory=memory, action=AuditAction.UPDATE, event="reinforced")
        return None
    if isinstance(operation, DreamRetire):
        memory = named[0]
        memory.status = MEMORY_STATUS_ARCHIVED
        memory.archived_at = now
        memory.archive_reason = ARCHIVE_REASON_CONSOLIDATED
        await _audit(
            db,
            run=run,
            memory=memory,
            action=AuditAction.DELETE,
            event="archived",
            extra={"reason": ARCHIVE_REASON_CONSOLIDATED},
        )
        return None
    return await _write_content(db, run=run, request=request, operation=operation, sources=named)


async def _write_content(
    db: AsyncSession,
    *,
    run: MemoryDreamRun,
    request: DreamScopeRequest,
    operation: DreamCreate | DreamRevise | DreamMerge,
    sources: list[AgentMemory],
) -> str | None:
    """Save new content as a note, superseding every source row with it."""
    target = request.target
    if isinstance(operation, DreamCreate):
        title, memory_type, importance = (
            operation.title,
            operation.memory_type,
            operation.importance,
        )
    else:
        title = operation.title or sources[0].title
        memory_type = sources[0].memory_type
        importance = max(source.importance for source in sources)
    try:
        validate_memory_content(kind=MEMORY_KIND_NOTE, title=title, content_md=operation.content_md)
    except AppValidationError:
        return SKIP_INVALID_CONTENT
    # Without a vector neither the removed-memory check nor dedup can run, so fail closed.
    embedded = await try_embed_memory(
        db,
        workspace_id=target.workspace.id,
        title=title,
        content_md=operation.content_md,
        agent_id=target.agent.id,
        user_id=target.user.id,
    )
    if embedded is None:
        return SKIP_EMBEDDING_UNAVAILABLE
    if await matches_removed_memory(db, request, embedded):
        return SKIP_REMOVED_BY_PERSON
    conversation = None if isinstance(operation, DreamMerge) else operation.conversation
    saved = await save_memory(
        db,
        workspace=target.workspace,
        agent=target.agent,
        user=target.user,
        scope=target.scope,
        kind=MEMORY_KIND_NOTE,
        memory_type=memory_type,
        title=title,
        content_md=operation.content_md,
        importance=importance,
        provenance=MemoryProvenance(
            source=MEMORY_SOURCE_DREAM,
            source_conversation_id=(
                request.conversations[conversation] if conversation is not None else None
            ),
            source_run_id=None,
            created_by=MEMORY_CREATED_BY_SYSTEM,
            created_by_user_id=None,
        ),
        _replaces_memory_ids=[source.id for source in sources],
        _embedded=embedded,
    )
    if saved.status != "created" or saved.memory is None:
        return SKIP_NEAR_DUPLICATE
    survivor = saved.memory
    if isinstance(operation, DreamRevise):
        survivor.expires_at = sources[0].expires_at
    await _audit(
        db,
        run=run,
        memory=survivor,
        action=AuditAction.CREATE,
        event="learned",
        extra={"operation": operation.op},
    )
    for source in sources:
        source.status = MEMORY_STATUS_SUPERSEDED
        source.superseded_by_id = survivor.id
        await _audit(
            db,
            run=run,
            memory=source,
            action=AuditAction.UPDATE,
            event="superseded",
            extra={"superseded_by_id": str(survivor.id)},
        )
    await db.flush()
    return None


async def _audit(
    db: AsyncSession,
    *,
    run: MemoryDreamRun,
    memory: AgentMemory,
    action: AuditAction,
    event: str,
    extra: Mapping[str, object] | None = None,
) -> None:
    await db.flush()
    await safe_record_operation_audit_event(
        db,
        workspace_id=memory.workspace_id,
        action=action,
        resource_type=AuditResourceType.MEMORY,
        resource_id=memory.id,
        actor_type=AuditActorType.SERVICE,
        actor_display=DREAM_AUDIT_ACTOR,
        details={"event": event, "dream_run_id": str(run.id), **(extra or {})},
    )
