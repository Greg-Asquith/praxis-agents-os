# apps/api/tests/services/memories/test_core_memory_block.py

"""Tests for deterministic core-memory prompt rendering."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import Agent
from models.agent_memories import AgentMemory
from services.memories.core_block import load_core_memories, render_core_memory_block
from tests.factories.memories import build_memory
from tests.factories.users import build_user
from tests.services.memories.conftest import MemoryContext

NOW = datetime(2026, 7, 27, 12, tzinfo=UTC)


def test_empty_input_omits_the_block() -> None:
    assert (
        render_core_memory_block(
            [],
            now=NOW,
            budget=2_000,
            line_max_chars=300,
        )
        == ""
    )


def test_rendering_is_hard_budgeted_across_supported_sizes() -> None:
    memories = [_memory(index=index, content="durable " * 60) for index in range(8)]

    for budget in (200, 500, 2_000):
        rendered = render_core_memory_block(
            memories,
            now=NOW,
            budget=budget,
            line_max_chars=300,
        )
        assert len(rendered) <= budget


def test_ranking_uses_importance_confidence_recency_and_id() -> None:
    memories = [
        _memory(index=4, title="Later id", reinforced_at=NOW),
        _memory(index=3, title="Earlier id", reinforced_at=NOW),
        _memory(index=2, title="Newer", confidence=0.8, reinforced_at=NOW),
        _memory(
            index=1,
            title="Higher confidence",
            confidence=0.9,
            reinforced_at=NOW - timedelta(days=2),
        ),
        _memory(
            index=0,
            title="Higher importance",
            importance=5,
            confidence=0.1,
            reinforced_at=NOW - timedelta(days=10),
        ),
    ]

    rendered = render_core_memory_block(
        memories,
        now=NOW,
        budget=2_000,
        line_max_chars=300,
    )

    assert rendered.index("Higher importance") < rendered.index("Higher confidence")
    assert rendered.index("Higher confidence") < rendered.index("Newer")
    assert rendered.index("Newer") < rendered.index("Earlier id")
    assert rendered.index("Earlier id") < rendered.index("Later id")


def test_long_lines_clamp_at_a_word_and_point_to_search() -> None:
    memory = _memory(index=1, title="Working preferences", content="alpha beta gamma " * 50)

    rendered = render_core_memory_block(
        [memory],
        now=NOW,
        budget=500,
        line_max_chars=180,
    )
    memory_line = rendered.splitlines()[-1]

    assert len(memory_line) <= 180
    assert 'search_memory("Working preferences")' in memory_line
    assert "… (full text:" in memory_line
    assert "\nalpha" not in memory_line


def test_long_quoted_title_keeps_the_complete_search_pointer() -> None:
    memory = _memory(
        index=1,
        title='"quoted title" ' * 20,
        content="durable detail " * 30,
    )

    rendered = render_core_memory_block(
        [memory],
        now=NOW,
        budget=500,
        line_max_chars=120,
    )
    memory_line = rendered.splitlines()[-1]

    assert len(memory_line) <= 120
    assert memory_line.endswith("))")
    assert "search_memory(" in memory_line


def test_omitted_footer_is_exact_and_provenance_is_visible() -> None:
    rendered = render_core_memory_block(
        [_memory(index=index, content="x" * 100) for index in range(3)],
        now=NOW,
        budget=360,
        line_max_chars=180,
    )

    assert rendered.endswith("2 more core memories not shown — retrieve them with search_memory.")
    assert "[agent-written]" in rendered


def test_rendering_is_invariant_to_input_order_and_time() -> None:
    memories = [_memory(index=index) for index in range(6)]
    shuffled = list(reversed(memories))

    first = render_core_memory_block(
        memories,
        now=NOW,
        budget=2_000,
        line_max_chars=300,
    )
    second = render_core_memory_block(
        shuffled,
        now=NOW + timedelta(weeks=7),
        budget=2_000,
        line_max_chars=300,
    )

    assert first == second
    assert NOW.isoformat() not in first
    assert all(str(memory.id) not in first for memory in memories)


async def test_loader_returns_only_active_core_rows_for_the_three_runtime_scopes(
    db_session: AsyncSession,
    memory_context: MemoryContext,
) -> None:
    other_user = build_user(email="other-core-loader@example.com")
    db_session.add(other_user)
    await db_session.flush()
    other_agent = Agent(
        name="Other Agent",
        slug="other-core-loader",
        instructions="Other.",
        workspace_id=memory_context.workspace.id,
        created_by=other_user.id,
    )
    db_session.add(other_agent)
    await db_session.flush()
    expected = [
        build_memory(
            workspace_id=memory_context.workspace.id,
            scope="agent",
            agent_id=memory_context.agent.id,
            title="Visible agent",
            kind="core",
        ),
        build_memory(
            workspace_id=memory_context.workspace.id,
            scope="user",
            user_id=memory_context.user.id,
            title="Visible user",
            kind="core",
        ),
        build_memory(
            workspace_id=memory_context.workspace.id,
            scope="workspace",
            title="Visible workspace",
            kind="core",
        ),
    ]
    hidden = [
        build_memory(
            workspace_id=memory_context.workspace.id,
            scope="agent",
            agent_id=other_agent.id,
            title="Other agent",
            kind="core",
        ),
        build_memory(
            workspace_id=memory_context.workspace.id,
            scope="user",
            user_id=other_user.id,
            title="Other user",
            kind="core",
        ),
        build_memory(
            workspace_id=memory_context.workspace.id,
            scope="workspace",
            title="Note",
            kind="note",
        ),
        build_memory(
            workspace_id=memory_context.workspace.id,
            scope="workspace",
            title="Archived",
            kind="core",
            status="archived",
            archived_at=NOW,
        ),
        build_memory(
            workspace_id=memory_context.workspace.id,
            scope="workspace",
            title="Expired",
            kind="core",
            expires_at=datetime(2020, 1, 1, tzinfo=UTC),
        ),
    ]
    db_session.add_all([*expected, *hidden])
    await db_session.flush()

    loaded = await load_core_memories(
        db_session,
        workspace=memory_context.workspace,
        agent=memory_context.agent,
        user=memory_context.user,
    )

    assert {memory.title for memory in loaded} == {
        "Visible agent",
        "Visible user",
        "Visible workspace",
    }


def _memory(
    *,
    index: int,
    title: str | None = None,
    content: str = "Remember this durable detail.",
    importance: int = 3,
    confidence: float = 0.8,
    reinforced_at: datetime | None = None,
) -> AgentMemory:
    created_at = NOW - timedelta(days=20 - index)
    return AgentMemory(
        id=UUID(int=index + 1),
        workspace_id=UUID(int=100),
        scope="agent",
        agent_id=UUID(int=200),
        user_id=None,
        kind="core",
        memory_type="fact",
        title=title or f"Memory {index}",
        content_md=content,
        importance=importance,
        confidence=confidence,
        last_reinforced_at=reinforced_at,
        status="active",
        source="interactive",
        created_by="agent",
        created_at=created_at,
        updated_at=created_at,
    )
