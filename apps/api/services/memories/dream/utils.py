# apps/api/services/memories/dream/utils.py

"""Dream run transitions and the guards apply runs before it writes."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError
from core.settings import settings
from models.agent_memories import AgentMemory
from models.conversation import Conversation
from models.memory_dream_run import MemoryDreamRun
from services.embeddings.domain import EmbeddingBatch
from services.memories.domain import (
    ARCHIVE_REASON_FORGOTTEN,
    ARCHIVE_REASON_USER_DELETED,
    MEMORY_CREATED_BY_USER,
    MEMORY_KIND_CORE,
    MEMORY_SCOPE_AGENT,
    MEMORY_SCOPE_USER,
    MEMORY_SCOPE_WORKSPACE,
    MEMORY_STATUS_ARCHIVED,
)
from services.memories.dream.domain import (
    FINAL_DREAM_STATUSES,
    REJECT_REPEATED_REFERENCE,
    REJECT_SCOPE_MISMATCH,
    REJECT_UNKNOWN_REFERENCE,
    DreamCreate,
    DreamMerge,
    DreamOperation,
    DreamScopeRequest,
    can_transition_dream_run,
)
from services.memories.utils import scope_filter


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


def is_protected_memory(memory: AgentMemory) -> bool:
    """A person's memory, one a person edited, and core memory are never changed by a dream."""
    return (
        memory.created_by == MEMORY_CREATED_BY_USER
        or memory.last_edited_by_user_at is not None
        or memory.kind == MEMORY_KIND_CORE
    )


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
