"""Absolute scope isolation across every memory read and mutation path."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import set_session_tenant_context
from core.exceptions.general import NotFoundError
from core.settings import settings
from models.agent import Agent
from services.embeddings.domain import EmbeddingProviderError
from services.memories import forget_memory, get_memory, search_memories, update_memory
from services.memories.domain import MemoryProvenance
from tests.factories.memories import build_memory
from tests.factories.users import build_user
from tests.factories.workspaces import build_workspace
from tests.services.memories.conftest import MemoryContext
from tests.support.embeddings import FakeEmbeddingProvider


class FailingEmbeddingProvider(FakeEmbeddingProvider):
    """Force lexical fallback without a live provider."""

    async def embed_texts(self, texts, *, model, dimensions):
        raise EmbeddingProviderError("offline")


async def test_search_returns_only_the_callers_visible_scope_union(
    db_session: AsyncSession,
    memory_context: MemoryContext,
) -> None:
    other_user = build_user(email=f"other-memory-{uuid4().hex}@example.com")
    other_workspace = build_workspace(slug=f"other-memory-{uuid4().hex[:10]}")
    db_session.add_all([other_user, other_workspace])
    await db_session.flush()
    other_agent = Agent(
        name="Other Agent",
        slug=f"other-agent-{uuid4().hex[:10]}",
        instructions="Reply plainly.",
        workspace_id=memory_context.workspace.id,
        created_by=other_user.id,
        tool_names=[],
    )
    db_session.add(other_agent)
    await db_session.flush()
    visible_and_same_workspace_rows = [
        build_memory(
            workspace_id=memory_context.workspace.id,
            scope="agent",
            agent_id=memory_context.agent.id,
            title="Visible agent policy",
            content_md="Weekly summary policy.",
        ),
        build_memory(
            workspace_id=memory_context.workspace.id,
            scope="user",
            user_id=memory_context.user.id,
            title="Visible user policy",
            content_md="Weekly summary policy.",
        ),
        build_memory(
            workspace_id=memory_context.workspace.id,
            scope="workspace",
            title="Visible workspace policy",
            content_md="Weekly summary policy.",
        ),
        build_memory(
            workspace_id=memory_context.workspace.id,
            scope="agent",
            agent_id=other_agent.id,
            title="Hidden agent policy",
            content_md="Weekly summary policy.",
        ),
        build_memory(
            workspace_id=memory_context.workspace.id,
            scope="user",
            user_id=other_user.id,
            title="Hidden user policy",
            content_md="Weekly summary policy.",
        ),
    ]
    db_session.add_all(visible_and_same_workspace_rows)
    await db_session.flush()
    await set_session_tenant_context(
        db_session,
        workspace_id=other_workspace.id,
        user_id=memory_context.user.id,
    )
    db_session.add(
        build_memory(
            workspace_id=other_workspace.id,
            scope="workspace",
            title="Hidden workspace policy",
            content_md="Weekly summary policy.",
        )
    )
    await db_session.flush()
    await set_session_tenant_context(
        db_session,
        workspace_id=memory_context.workspace.id,
        user_id=memory_context.user.id,
    )
    result = await search_memories(
        db_session,
        workspace=memory_context.workspace,
        agent=memory_context.agent,
        user=memory_context.user,
        query="weekly summary policy",
        provider=FailingEmbeddingProvider(),
    )
    assert {hit.memory.title for hit in result.results} == {
        "Visible agent policy",
        "Visible user policy",
        "Visible workspace policy",
    }


async def test_search_excludes_expired_rows_before_the_sweeper_runs(
    db_session: AsyncSession,
    memory_context: MemoryContext,
) -> None:
    now = datetime.now(UTC)
    rows = [
        build_memory(
            workspace_id=memory_context.workspace.id,
            title="Current renewal policy",
            content_md="The renewal policy is current.",
            expires_at=now + timedelta(days=1),
        ),
        build_memory(
            workspace_id=memory_context.workspace.id,
            title="Expired renewal policy",
            content_md="The renewal policy is expired.",
            expires_at=now - timedelta(seconds=1),
        ),
    ]
    db_session.add_all(rows)
    await db_session.flush()

    result = await search_memories(
        db_session,
        workspace=memory_context.workspace,
        agent=memory_context.agent,
        user=memory_context.user,
        query="renewal policy",
        provider=FailingEmbeddingProvider(),
    )

    assert [hit.memory.title for hit in result.results] == ["Current renewal policy"]


async def test_hybrid_search_configures_filtered_hnsw_before_querying(
    db_session: AsyncSession,
    memory_context: MemoryContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert await db_session.scalar(text("SELECT current_user")) == "praxis_app"
    provider = FakeEmbeddingProvider()
    embedded = await provider.embed_texts(
        ["Quarterly renewal policy"],
        model=settings.EMBEDDINGS_MODEL,
        dimensions=settings.EMBEDDINGS_DIMENSIONS,
    )
    memory = build_memory(
        workspace_id=memory_context.workspace.id,
        title="Quarterly renewal",
        content_md="Quarterly renewal policy",
        embedding=embedded.vectors[0],
        embedding_provider=embedded.provider,
        embedding_model=embedded.model,
        embedding_dims=embedded.dimensions,
    )
    db_session.add(memory)
    await db_session.flush()
    statements: list[str] = []
    original_execute = db_session.execute

    async def capture_execute(statement, *args, **kwargs):
        statements.append(str(statement))
        return await original_execute(statement, *args, **kwargs)

    monkeypatch.setattr(db_session, "execute", capture_execute)
    result = await search_memories(
        db_session,
        workspace=memory_context.workspace,
        agent=memory_context.agent,
        user=memory_context.user,
        query="quarterly renewal",
        provider=provider,
    )

    assert result.mode == "hybrid"
    iterative_index = statements.index("SET LOCAL hnsw.iterative_scan = 'relaxed_order'")
    ef_search_index = next(
        index
        for index, statement in enumerate(statements)
        if statement.startswith("SET LOCAL hnsw") and "ef_search" in statement
    )
    search_index = next(
        index
        for index, statement in enumerate(statements)
        if "WITH lexical AS" in statement and "semantic AS" in statement
    )
    assert iterative_index < ef_search_index < search_index


async def test_agent_scope_get_hides_another_agent(
    db_session: AsyncSession,
    memory_context: MemoryContext,
) -> None:
    other_agent = Agent(
        name="Hidden Agent",
        slug=f"hidden-agent-{uuid4().hex[:10]}",
        instructions="Reply plainly.",
        workspace_id=memory_context.workspace.id,
        created_by=memory_context.user.id,
        tool_names=[],
    )
    db_session.add(other_agent)
    await db_session.flush()
    hidden = build_memory(
        workspace_id=memory_context.workspace.id,
        scope="agent",
        agent_id=other_agent.id,
    )
    db_session.add(hidden)
    await db_session.flush()
    with pytest.raises(NotFoundError):
        await get_memory(
            db_session,
            workspace=memory_context.workspace,
            agent=memory_context.agent,
            user=memory_context.user,
            memory_id=hidden.id,
        )


async def test_out_of_scope_update_and_forget_are_not_found(
    db_session: AsyncSession,
    memory_context: MemoryContext,
) -> None:
    other_user = build_user(email=f"hidden-user-{uuid4().hex}@example.com")
    db_session.add(other_user)
    await db_session.flush()
    hidden = build_memory(
        workspace_id=memory_context.workspace.id,
        scope="user",
        user_id=other_user.id,
    )
    db_session.add(hidden)
    await db_session.flush()
    provenance = MemoryProvenance(
        source="interactive",
        source_conversation_id=None,
        source_run_id=None,
        created_by="agent",
        created_by_user_id=memory_context.user.id,
    )
    with pytest.raises(NotFoundError):
        await update_memory(
            db_session,
            workspace=memory_context.workspace,
            agent=memory_context.agent,
            user=memory_context.user,
            memory_id=hidden.id,
            content_md="Do not expose whether this exists.",
            provenance=provenance,
        )
    with pytest.raises(NotFoundError):
        await forget_memory(
            db_session,
            workspace=memory_context.workspace,
            agent=memory_context.agent,
            user=memory_context.user,
            memory_id=hidden.id,
        )
