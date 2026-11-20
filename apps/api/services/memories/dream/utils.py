# apps/api/services/memories/dream/utils.py

"""Dream run transitions, scope choice, memory lookups, and the guards apply runs."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from core.exceptions.general import ConflictError
from core.settings import settings
from models.agent_memories import AgentMemory
from models.conversation import Conversation
from models.jobs import Job
from models.memory_dream_run import MemoryDreamRun
from models.workspace import Workspace
from services.embeddings.domain import EmbeddingBatch
from services.memories.domain import (
    ARCHIVE_REASON_FORGOTTEN,
    ARCHIVE_REASON_USER_DELETED,
    MEMORY_CREATED_BY_USER,
    MEMORY_SCOPE_AGENT,
    MEMORY_SCOPE_USER,
    MEMORY_SCOPE_WORKSPACE,
    MEMORY_STATUS_ARCHIVED,
    MemoryScope,
)
from services.memories.dream.domain import (
    DREAM_RUN_SUBJECT_TYPE,
    DREAM_STATUS_COMPLETED,
    DUPLICATE_CLUSTER_RECENT_MEMORIES,
    DUPLICATE_CLUSTER_SIMILARITY,
    FINAL_DREAM_STATUSES,
    MAX_DUPLICATE_PAIRS,
    MEMORY_DREAM_JOB_KIND,
    NEAREST_MEMORIES_PER_CANDIDATE,
    REJECT_REPEATED_REFERENCE,
    REJECT_SCOPE_MISMATCH,
    REJECT_UNKNOWN_REFERENCE,
    DreamCreate,
    DreamMerge,
    DreamOperation,
    DreamScopeRequest,
    can_transition_dream_run,
)
from services.memories.utils import active_memory_filter, scope_filter


def move_dream_run(
    run: MemoryDreamRun, target: str, *, now: datetime, error_code: str | None = None
) -> None:
    """Moves a dream run the caller has locked to target, or raises ConflictError."""
    if not can_transition_dream_run(run.status, target):
        raise ConflictError(
            f"Cannot move dream run from {run.status!r} to {target!r}",
            conflicting_resource="memory_dream_run",
            details={"dream_run_id": str(run.id), "from": run.status, "to": target},
        )
    run.status = target
    run.error_code = error_code
    if target in FINAL_DREAM_STATUSES:
        run.finished_at = now


async def enqueue_dream_step(
    db: AsyncSession, run: MemoryDreamRun, *, run_after: datetime | None = None
) -> Job:
    """Queues the job that advances the run from its current status, once per status.

    A status that waits on a batch queues its next check the same way, at `run_after`.
    """
    from services.jobs.enqueue_job import enqueue_job

    return await enqueue_job(
        db,
        kind=MEMORY_DREAM_JOB_KIND,
        workspace_id=run.workspace_id,
        subject_type=DREAM_RUN_SUBJECT_TYPE,
        subject_id=run.id,
        payload={"status": run.status},
        content_hash=f"memory-dream:{run.id}:{run.status}",
        run_after=run_after,
    )


def conversation_scope(
    workspace: Workspace, entry: Mapping[str, Any]
) -> tuple[MemoryScope, UUID | None]:
    """Returns the scope and user a conversation's learning is written to.

    Only a workspace-visible conversation in a team workspace writes workspace scope;
    everything else stays with the conversation's owner.
    """
    if workspace.is_personal or entry["visibility"] != "workspace":
        return MEMORY_SCOPE_USER, UUID(entry["user_id"])
    return MEMORY_SCOPE_WORKSPACE, None


async def previous_read_end(
    db: AsyncSession, *, workspace_id: UUID, conversation_id: UUID
) -> int | None:
    """Returns where the newest completed dream stopped reading a conversation, if any."""
    marker = [{"id": str(conversation_id), "extracted": True}]
    run = await db.scalar(
        select(MemoryDreamRun)
        .where(
            MemoryDreamRun.workspace_id == workspace_id,
            MemoryDreamRun.status == DREAM_STATUS_COMPLETED,
            MemoryDreamRun.conversations.contains(marker),
        )
        .order_by(MemoryDreamRun.window_end.desc())
        .limit(1)
    )
    if run is None:
        return None
    return next(
        entry["end_sequence"] for entry in run.conversations if entry["id"] == str(conversation_id)
    )


async def nearest_memories(
    db: AsyncSession,
    *,
    target_filter: ColumnElement[bool],
    embedded: EmbeddingBatch,
) -> list[AgentMemory]:
    """Returns the active memories in one scope closest to an embedded candidate."""
    distance = AgentMemory.embedding.cosine_distance(embedded.vectors[0])
    return list(
        await db.scalars(
            select(AgentMemory)
            .where(
                target_filter,
                active_memory_filter(),
                AgentMemory.embedding_provider == embedded.provider,
                AgentMemory.embedding_model == embedded.model,
                AgentMemory.embedding_dims == embedded.dimensions,
            )
            .order_by(distance, AgentMemory.id)
            .limit(NEAREST_MEMORIES_PER_CANDIDATE)
        )
    )


async def duplicate_pairs(
    db: AsyncSession, *, target_filter: ColumnElement[bool]
) -> list[tuple[UUID, UUID]]:
    """Returns pairs among a scope's recent notes that are close enough to be duplicates."""
    recent = (
        select(
            AgentMemory.id,
            AgentMemory.embedding,
            AgentMemory.embedding_model,
            AgentMemory.embedding_dims,
        )
        .where(
            target_filter,
            active_memory_filter(),
            AgentMemory.embedding.is_not(None),
        )
        .order_by(AgentMemory.updated_at.desc(), AgentMemory.id)
        .limit(DUPLICATE_CLUSTER_RECENT_MEMORIES)
        .subquery()
    )
    left, right = aliased(recent), aliased(recent)
    distance = left.c.embedding.cosine_distance(right.c.embedding)
    rows = await db.execute(
        select(left.c.id, right.c.id)
        .where(
            left.c.id < right.c.id,
            left.c.embedding_model == right.c.embedding_model,
            left.c.embedding_dims == right.c.embedding_dims,
            distance <= 1.0 - DUPLICATE_CLUSTER_SIMILARITY,
        )
        .order_by(distance)
        .limit(MAX_DUPLICATE_PAIRS)
    )
    return [(first, second) for first, second in rows.tuples()]


def is_protected_memory(memory: AgentMemory) -> bool:
    """A person's memory and one a person edited are never changed by a dream."""
    return memory.created_by == MEMORY_CREATED_BY_USER or memory.last_edited_by_user_at is not None


def named_memories(operation: DreamOperation) -> list[str]:
    """Returns the memory references one operation names."""
    if isinstance(operation, DreamCreate):
        return []
    if isinstance(operation, DreamMerge):
        return list(operation.memories)
    return [operation.memory]


def find_reference_problem(
    request: DreamScopeRequest, operations: Sequence[DreamOperation]
) -> str | None:
    """Returns why the response is unusable, or None. One bad reference spoils the response."""
    seen: set[str] = set()
    for operation in operations:
        if isinstance(operation, DreamCreate) and request.target.scope == MEMORY_SCOPE_AGENT:
            return REJECT_SCOPE_MISMATCH
        conversation = getattr(operation, "conversation", None)
        if conversation is not None and conversation not in request.conversations:
            return REJECT_UNKNOWN_REFERENCE
        for reference in named_memories(operation):
            if reference not in request.memories:
                return REJECT_UNKNOWN_REFERENCE
            if reference in seen:
                return REJECT_REPEATED_REFERENCE
            seen.add(reference)
    return None


async def conversations_fit_scope(db: AsyncSession, request: DreamScopeRequest) -> bool:
    """Checks what a request learned from could be read by everyone who reads its scope.

    Workspace scope takes only workspace-visible conversations in a team workspace; user
    scope takes only the target user's own conversations.
    """
    if not request.conversations:
        return True
    target = request.target
    if target.scope == MEMORY_SCOPE_AGENT:
        return False
    rows = (
        await db.execute(
            select(Conversation.user_id, Conversation.visibility).where(
                Conversation.id.in_(set(request.conversations.values())),
                Conversation.workspace_id == target.workspace.id,
            )
        )
    ).all()
    if len(rows) != len(set(request.conversations.values())):
        return False
    if target.scope == MEMORY_SCOPE_USER:
        return all(user_id == target.user.id for user_id, _visibility in rows)
    return (
        target.scope == MEMORY_SCOPE_WORKSPACE
        and not target.workspace.is_personal
        and all(visibility == "workspace" for _user_id, visibility in rows)
    )


async def matches_removed_memory(
    db: AsyncSession, request: DreamScopeRequest, embedded: EmbeddingBatch
) -> bool:
    """Checks whether content matches a memory a person or agent removed from this scope."""
    target = request.target
    distance = AgentMemory.embedding.cosine_distance(embedded.vectors[0])
    nearest = await db.scalar(
        select(distance)
        .where(
            scope_filter(
                target.scope,
                workspace_id=target.workspace.id,
                agent_id=target.agent.id,
                user_id=target.user.id,
            ),
            AgentMemory.status == MEMORY_STATUS_ARCHIVED,
            AgentMemory.archive_reason.in_((ARCHIVE_REASON_FORGOTTEN, ARCHIVE_REASON_USER_DELETED)),
            AgentMemory.embedding_provider == embedded.provider,
            AgentMemory.embedding_model == embedded.model,
            AgentMemory.embedding_dims == embedded.dimensions,
        )
        .order_by(distance)
        .limit(1)
    )
    return nearest is not None and 1.0 - float(nearest) >= settings.MEMORY_DEDUP_SIMILARITY
