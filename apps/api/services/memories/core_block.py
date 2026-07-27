# apps/api/services/memories/core_block.py

"""Load and deterministically render the core-memory prompt block."""

import json
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import Agent
from models.agent_memories import AgentMemory
from models.user import User
from models.workspace import Workspace
from services.memories.domain import MEMORY_KIND_CORE
from services.memories.utils import active_memory_filter, visible_scope_filter

_HEADER = (
    "## Memory\n"
    "\n"
    "These are standing memories saved from previous work.\n"
    "Verify anything surprising and use search_memory for more details and notes."
)


async def load_core_memories(
    db: AsyncSession,
    *,
    workspace: Workspace,
    agent: Agent,
    user: User,
) -> list[AgentMemory]:
    """Load active, unexpired core memories visible to one runtime principal."""
    rows = await db.scalars(
        select(AgentMemory).where(
            visible_scope_filter(
                workspace_id=workspace.id,
                agent_id=agent.id,
                user_id=user.id,
            ),
            AgentMemory.kind == MEMORY_KIND_CORE,
            active_memory_filter(now=datetime.now(UTC)),
        )
    )
    return list(rows)


def render_core_memory_block(
    memories: Sequence[AgentMemory],
    *,
    now: datetime,
    budget: int,
    line_max_chars: int,
) -> str:
    """Render a hard-budgeted summary whose ordering is invariant across time.

    ``now`` is deliberately inert. Output is a pure function of the rows,
    budget, and line limit so provider prompt-cache prefixes change only when
    stored memory changes.
    """
    del now
    if not memories or budget < len(_HEADER):
        return ""

    ranked = sorted(
        memories,
        key=lambda memory: (
            -int(memory.importance),
            -float(memory.confidence),
            -_rank_timestamp(memory).timestamp(),
            str(memory.id),
        ),
    )
    lines = [_render_memory_line(memory, line_max_chars=line_max_chars) for memory in ranked]
    selected: list[str] = []

    for line in lines:
        prospective_count = len(selected) + 1
        omitted_count = len(lines) - prospective_count
        candidate = _assemble([*selected, line], footer=_omitted_footer(omitted_count))
        if len(candidate) <= budget:
            selected.append(line)

    omitted_count = len(lines) - len(selected)
    rendered = _assemble(selected, footer=_omitted_footer(omitted_count))
    if len(rendered) > budget:
        return ""
    return rendered


def _assemble(memory_lines: Sequence[str], *, footer: str) -> str:
    # Blank lines keep the list from swallowing the intro and footer when rendered as markdown.
    parts = [_HEADER]
    if memory_lines:
        parts.extend(["", *memory_lines])
    if footer:
        parts.extend(["", footer])
    return "\n".join(parts)


def _rank_timestamp(memory: AgentMemory) -> datetime:
    return memory.last_reinforced_at or memory.created_at


def _render_memory_line(memory: AgentMemory, *, line_max_chars: int) -> str:
    provenance = f"{memory.created_by}-written"
    title = _single_line(memory.title)
    content = _single_line(memory.content_md)
    leader = f"- [{memory.scope} {memory.memory_type}] [{provenance}] "
    prefix = f"{leader}{title}: "
    line = f"{prefix}{content}"
    if len(line) <= line_max_chars:
        return line

    query_limit = min(48, len(title))
    while True:
        query_title = _clip_at_word(title, query_limit) or "memory"
        suffix = f"… (full text: search_memory({json.dumps(query_title)}))"
        title_budget = line_max_chars - len(leader) - len(": ") - len(suffix)
        if title_budget >= 8 or query_limit <= 8:
            break
        query_limit -= 1

    visible_title = title
    if len(visible_title) > title_budget:
        visible_title = f"{_clip_at_word(visible_title, max(1, title_budget - 1))}…"
    prefix = f"{leader}{visible_title}: "
    content_budget = max(0, line_max_chars - len(prefix) - len(suffix) - 1)
    clipped_content = _clip_at_word(content, content_budget)
    separator = " " if clipped_content else ""
    return f"{prefix}{clipped_content}{separator}{suffix}"


def _single_line(value: str) -> str:
    return " ".join(value.split())


def _clip_at_word(value: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(value) <= limit:
        return value
    clipped = value[:limit].rstrip()
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0]
    return clipped.rstrip()


def _omitted_footer(count: int) -> str:
    if count <= 0:
        return ""
    return f"{count} more core memories not shown — retrieve them with search_memory."
