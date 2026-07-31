# apps/api/services/agents/runtime/tools/memory.py

"""Agent-memory tools use conditional ApprovalRequired and approved replay.

Pydantic AI exposes ``RunContext.tool_call_approved`` on replay, and the
runtime dispatch layer preserves tool-body ``ApprovalRequired`` requests.
"""

from typing import Annotated
from uuid import UUID

from pydantic import Field
from pydantic_ai import ApprovalRequired, ModelRetry, RunContext

from core.exceptions.general import AppValidationError, ConflictError, NotFoundError
from core.settings import settings
from models.agent_memories import AgentMemory
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    TOOL_EFFECT_WRITE,
    TOOL_POLICY_AUTO,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.agents.runtime.tools.memory_results import (
    SearchMemoryOutput,
    build_bounded_search_output,
)
from services.agents.runtime.tools.registry import runtime_tool
from services.memories import (
    forget_memory as forget_memory_service,
    get_memory,
    save_memory as save_memory_service,
    search_memories,
    update_memory as update_memory_service,
)
from services.memories.domain import (
    MEMORY_KIND_CORE,
    MemoryKind,
    MemoryProvenance,
    MemoryScope,
    MemoryType,
)


def _provenance(ctx: RunContext[RuntimeDeps]) -> MemoryProvenance:
    return MemoryProvenance(
        source=ctx.deps.run.trigger,
        source_conversation_id=ctx.deps.conversation.id,
        source_run_id=ctx.deps.run.id,
        created_by="agent",
        created_by_user_id=ctx.deps.user.id,
    )


def _memory_summary(memory: AgentMemory) -> dict[str, object]:
    return {
        "id": str(memory.id),
        "scope": memory.scope,
        "kind": memory.kind,
        "memory_type": memory.memory_type,
        "title": memory.title,
        "importance": memory.importance,
        "confidence": float(memory.confidence),
        "status": memory.status,
    }


def _service_retry(exc: Exception) -> ModelRetry:
    if isinstance(exc, (AppValidationError, ConflictError, NotFoundError)):
        return ModelRetry(exc.message)
    return ModelRetry("The memory operation could not be completed.")


@runtime_tool(
    name="save_memory",
    provider="core",
    label="Save Memory",
    description=(
        "Save a durable fact, preference, episode, or outcome. Search first; "
        "near duplicates require an explicit resolution."
    ),
    effect=TOOL_EFFECT_WRITE,
    default_policy=TOOL_POLICY_AUTO,
    takes_ctx=True,
    timeout=15,
    configurable=False,
    auto_mount=True,
    presentation=ToolPresentation(
        icon="book",
        running_label="Saving Memory",
        completed_label="Saved Memory",
        failed_label="Couldn't Save Memory",
        arg_fields=(
            ToolFieldPresentation(
                key="kind",
                label="Kind",
                editable=True,
                options=("core", "note"),
            ),
            ToolFieldPresentation(
                key="scope",
                label="Scope",
                editable=True,
                options=("agent", "user", "workspace"),
            ),
            ToolFieldPresentation(key="title", label="Memory", editable=True),
            ToolFieldPresentation(key="content", label="Details", format="markdown", editable=True),
            ToolFieldPresentation(
                key="importance",
                label="Importance",
                format="number",
                editable=True,
            ),
            ToolFieldPresentation(
                key="memory_type",
                label="Memory Type",
                editable=True,
                options=("fact", "preference", "episode", "outcome"),
            ),
            ToolFieldPresentation(
                key="expires_in_days",
                label="Expires in Days",
                format="number",
                editable=True,
                secondary=True,
            ),
        ),
    ),
)
async def save_memory(
    ctx: RunContext[RuntimeDeps],
    title: Annotated[str, Field(min_length=1, max_length=200)],
    content: Annotated[str, Field(min_length=1)],
    scope: MemoryScope = "agent",
    kind: MemoryKind = "note",
    memory_type: MemoryType = "fact",
    importance: Annotated[int, Field(ge=1, le=5)] = 3,
    expires_in_days: Annotated[int | None, Field(gt=0)] = None,
    duplicate_of: str | None = None,
    save_as_new: bool = False,
) -> dict[str, object]:
    """Save a memory with explicit near-duplicate resolution."""
    if kind == MEMORY_KIND_CORE and not ctx.tool_call_approved:
        raise ApprovalRequired(metadata={"reason": "core_memory_write"})
    try:
        result = await save_memory_service(
            ctx.deps.db,
            workspace=ctx.deps.workspace,
            agent=ctx.deps.agent,
            user=ctx.deps.user,
            scope=scope,
            kind=kind,
            memory_type=memory_type,
            title=title,
            content_md=content,
            importance=importance,
            expires_in_days=expires_in_days,
            provenance=_provenance(ctx),
            duplicate_of=UUID(duplicate_of) if duplicate_of is not None else None,
            save_as_new=save_as_new,
        )
    except ValueError as exc:
        raise ModelRetry("duplicate_of must be a valid memory id.") from exc
    except (AppValidationError, ConflictError, NotFoundError) as exc:
        raise _service_retry(exc) from exc

    if result.status == "near_duplicate":
        existing = result.existing_memory
        return {
            "status": result.status,
            "existing_memory": _memory_summary(existing) if existing else None,
            "similarity": result.similarity,
            "next_step": (
                "For a true duplicate, call save_memory again with duplicate_of set "
                "to the existing id. For a correction, update that memory. If the "
                "fact is genuinely distinct, call save_memory with save_as_new=true."
            ),
        }
    return {
        "status": result.status,
        "memory": _memory_summary(result.memory) if result.memory else None,
        "similarity": result.similarity,
    }


@runtime_tool(
    name="search_memory",
    provider="core",
    label="Search Memory",
    description="Search active memories visible to this agent and user.",
    effect=TOOL_EFFECT_READ,
    default_policy=TOOL_POLICY_AUTO,
    takes_ctx=True,
    timeout=15,
    configurable=False,
    auto_mount=True,
    output_model=SearchMemoryOutput,
    presentation=ToolPresentation(
        icon="search",
        running_label="Searching Memory for {query}",
        completed_label="Searched Memory for {query}",
        failed_label="Couldn't Search Memory",
        arg_fields=(ToolFieldPresentation(key="query", label="Search"),),
        result_fields=(ToolFieldPresentation(key="results", label="Matches", format="list"),),
    ),
)
async def search_memory(
    ctx: RunContext[RuntimeDeps],
    query: Annotated[str, Field(min_length=1, max_length=1000)],
    scope: MemoryScope | None = None,
    kind: MemoryKind | None = None,
    memory_type: MemoryType | None = None,
    limit: Annotated[int, Field(ge=1, le=settings.MEMORY_SEARCH_MAX_LIMIT)] = (
        settings.MEMORY_SEARCH_DEFAULT_LIMIT
    ),
) -> dict[str, object]:
    """Search trusted internal memory with server-minted provenance."""
    try:
        result = await search_memories(
            ctx.deps.db,
            workspace=ctx.deps.workspace,
            agent=ctx.deps.agent,
            user=ctx.deps.user,
            query=query,
            scope=scope,
            kind=kind,
            memory_type=memory_type,
            limit=limit,
        )
    except AppValidationError as exc:
        raise _service_retry(exc) from exc
    hits = [
        {
            "id": str(hit.memory.id),
            "scope": hit.memory.scope,
            "kind": hit.memory.kind,
            "memory_type": hit.memory.memory_type,
            "title": hit.memory.title,
            "content": hit.memory.content_md,
            "source": hit.memory.source,
            "created_by": hit.memory.created_by,
            "created_by_user_id": (
                str(hit.memory.created_by_user_id)
                if hit.memory.created_by_user_id is not None
                else None
            ),
            "effective_confidence": hit.effective_confidence,
            "score": hit.score,
        }
        for hit in result.results
    ]
    return build_bounded_search_output(
        query=result.query,
        hits=hits,
        used_lexical_fallback=result.mode == "lexical_fallback",
        max_chars=settings.MEMORY_SEARCH_RESULT_MAX_CHARS,
    )


@runtime_tool(
    name="update_memory",
    provider="core",
    label="Update Memory",
    description="Edit memory metadata or supersede its content while preserving history.",
    effect=TOOL_EFFECT_WRITE,
    default_policy=TOOL_POLICY_AUTO,
    takes_ctx=True,
    timeout=15,
    configurable=False,
    auto_mount=True,
    presentation=ToolPresentation(
        icon="book",
        running_label="Updating Memory",
        completed_label="Updated Memory",
        failed_label="Couldn't Update Memory",
        arg_fields=(
            ToolFieldPresentation(key="memory_id", label="Memory"),
            ToolFieldPresentation(key="title", label="Title", editable=True),
            ToolFieldPresentation(
                key="content",
                label="Details",
                format="markdown",
                editable=True,
            ),
            ToolFieldPresentation(
                key="importance",
                label="Importance",
                format="number",
                editable=True,
            ),
            ToolFieldPresentation(
                key="expires_in_days",
                label="Expires in Days",
                format="number",
                editable=True,
                secondary=True,
            ),
        ),
    ),
)
async def update_memory(
    ctx: RunContext[RuntimeDeps],
    memory_id: str,
    title: str | None = None,
    content: str | None = None,
    importance: Annotated[int | None, Field(ge=1, le=5)] = None,
    expires_in_days: Annotated[int | None, Field(gt=0)] = None,
) -> dict[str, object]:
    """Update a memory; core targets conditionally require approval."""
    try:
        parsed_id = UUID(memory_id)
        target = await get_memory(
            ctx.deps.db,
            workspace=ctx.deps.workspace,
            agent=ctx.deps.agent,
            user=ctx.deps.user,
            memory_id=parsed_id,
        )
        if target.kind == MEMORY_KIND_CORE and not ctx.tool_call_approved:
            raise ApprovalRequired(metadata={"reason": "core_memory_write"})
        result = await update_memory_service(
            ctx.deps.db,
            workspace=ctx.deps.workspace,
            agent=ctx.deps.agent,
            user=ctx.deps.user,
            memory_id=parsed_id,
            title=title,
            content_md=content,
            importance=importance,
            expires_in_days=expires_in_days,
            provenance=_provenance(ctx),
        )
    except ValueError as exc:
        raise ModelRetry("memory_id must be a valid memory id.") from exc
    except (AppValidationError, ConflictError, NotFoundError) as exc:
        raise _service_retry(exc) from exc
    return {
        "status": "superseded" if result.superseded_memory_id else "updated",
        "memory": _memory_summary(result.memory),
        "superseded_memory_id": (
            str(result.superseded_memory_id) if result.superseded_memory_id else None
        ),
    }


@runtime_tool(
    name="forget_memory",
    provider="core",
    label="Forget Memory",
    description="Archive a stale memory without deleting its history.",
    effect=TOOL_EFFECT_WRITE,
    default_policy=TOOL_POLICY_AUTO,
    takes_ctx=True,
    timeout=15,
    configurable=False,
    auto_mount=True,
    presentation=ToolPresentation(
        icon="book",
        running_label="Forgetting Memory",
        completed_label="Forgot Memory",
        failed_label="Couldn't Forget Memory",
        arg_fields=(
            ToolFieldPresentation(key="memory_id", label="Memory"),
            ToolFieldPresentation(
                key="reason",
                label="Reason",
                format="multiline",
            ),
        ),
    ),
)
async def forget_memory(
    ctx: RunContext[RuntimeDeps],
    memory_id: str,
    reason: str | None = None,
) -> dict[str, object]:
    """Archive one visible memory."""
    try:
        result = await forget_memory_service(
            ctx.deps.db,
            workspace=ctx.deps.workspace,
            agent=ctx.deps.agent,
            user=ctx.deps.user,
            memory_id=UUID(memory_id),
            reason=reason,
        )
    except ValueError as exc:
        raise ModelRetry("memory_id must be a valid memory id.") from exc
    except (AppValidationError, ConflictError, NotFoundError) as exc:
        raise _service_retry(exc) from exc
    return {
        "status": "already_archived" if result.already_archived else "archived",
        "memory": _memory_summary(result.memory),
    }
