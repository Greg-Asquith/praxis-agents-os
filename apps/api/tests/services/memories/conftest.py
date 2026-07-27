"""Shared memory-service fixtures."""

from dataclasses import dataclass
from uuid import uuid4

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.agent import Agent
from models.user import User
from models.workspace import Workspace
from services.embeddings.domain import EmbeddingBatch
from services.memories.domain import MemoryProvenance
from tests.factories.users import build_user
from tests.factories.workspaces import build_workspace
from tests.support.embeddings import FakeEmbeddingProvider


@dataclass(frozen=True)
class MemoryContext:
    user: User
    workspace: Workspace
    agent: Agent
    provenance: MemoryProvenance


@pytest_asyncio.fixture
async def memory_context(db_session: AsyncSession) -> MemoryContext:
    """Persist one user/workspace/agent context."""
    suffix = uuid4().hex
    user = build_user(email=f"memory-{suffix}@example.com")
    workspace = build_workspace(slug=f"memory-{suffix[:12]}")
    db_session.add_all([user, workspace])
    await db_session.flush()
    agent = Agent(
        name="Memory Agent",
        slug=f"memory-agent-{suffix[:10]}",
        instructions="Remember carefully.",
        workspace_id=workspace.id,
        created_by=user.id,
        tool_names=["save_memory", "search_memory", "update_memory", "forget_memory"],
    )
    db_session.add(agent)
    await db_session.flush()
    return MemoryContext(
        user=user,
        workspace=workspace,
        agent=agent,
        provenance=MemoryProvenance(
            source="interactive",
            source_conversation_id=None,
            source_run_id=None,
            created_by="agent",
            created_by_user_id=user.id,
        ),
    )


def install_fake_embeddings(monkeypatch, *, fail: bool = False) -> None:
    """Patch write-time embedding at its memory-service seam."""
    provider = FakeEmbeddingProvider()

    async def fake_embed_texts(
        _db,
        texts,
        *,
        workspace_id,
        provider=None,
    ) -> EmbeddingBatch:
        del workspace_id, provider
        if fail:
            raise TimeoutError
        return await provider_instance.embed_texts(
            texts,
            model=settings.EMBEDDINGS_MODEL,
            dimensions=settings.EMBEDDINGS_DIMENSIONS,
        )

    provider_instance = provider
    monkeypatch.setattr("services.memories.utils.embed_texts", fake_embed_texts)
