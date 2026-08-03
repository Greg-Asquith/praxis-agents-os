# apps/api/tests/services/embeddings/test_usage_counter.py

"""Embedding usage counter persistence and concurrency tests."""

import asyncio
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.database import set_session_tenant_context
from models.embedding_usage import EmbeddingTokenUsage
from models.workspace import Workspace
from services.embeddings.get_embedding_usage import get_embedding_usage
from services.embeddings.record_embedding_usage import record_embedding_usage
from tests.factories import build_workspace

pytestmark = pytest.mark.asyncio


async def test_usage_upsert_increments_and_periods_are_isolated(
    db_session: AsyncSession,
) -> None:
    first = build_workspace(slug=f"usage-first-{uuid4().hex}")
    second = build_workspace(slug=f"usage-second-{uuid4().hex}")
    db_session.add_all([first, second])
    await db_session.flush()
    january = date(2026, 1, 1)
    january_later = date(2026, 1, 19)
    february = date(2026, 2, 1)

    await set_session_tenant_context(db_session, workspace_id=first.id)
    assert (
        await record_embedding_usage(
            db_session,
            workspace_id=first.id,
            tokens=4,
            period_month=january_later,
        )
        == 4
    )
    assert (
        await record_embedding_usage(
            db_session,
            workspace_id=first.id,
            tokens=6,
            period_month=january,
        )
        == 10
    )
    await record_embedding_usage(
        db_session,
        workspace_id=first.id,
        tokens=3,
        period_month=february,
    )
    await set_session_tenant_context(db_session, workspace_id=second.id)
    await record_embedding_usage(
        db_session,
        workspace_id=second.id,
        tokens=8,
        period_month=january,
    )

    await set_session_tenant_context(db_session, workspace_id=first.id)
    assert (
        await get_embedding_usage(
            db_session,
            workspace_id=first.id,
            period_month=january,
        )
        == 10
    )
    assert (
        await get_embedding_usage(
            db_session,
            workspace_id=first.id,
            period_month=february,
        )
        == 3
    )
    await set_session_tenant_context(db_session, workspace_id=second.id)
    assert (
        await get_embedding_usage(
            db_session,
            workspace_id=second.id,
            period_month=january,
        )
        == 8
    )


async def test_nonpositive_tokens_are_a_read_only_noop(db_session: AsyncSession) -> None:
    workspace = build_workspace(slug=f"usage-noop-{uuid4().hex}")
    db_session.add(workspace)
    await db_session.flush()

    assert await record_embedding_usage(db_session, workspace_id=workspace.id, tokens=0) == 0
    assert await record_embedding_usage(db_session, workspace_id=workspace.id, tokens=-1) == 0


async def test_usage_upsert_advances_updated_at(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workspace = build_workspace(slug=f"usage-timestamp-{uuid4().hex}")
    async with committed_db_session_factory() as db:
        db.add(workspace)
        await db.commit()

    try:
        async with committed_db_session_factory() as db:
            await record_embedding_usage(
                db,
                workspace_id=workspace.id,
                tokens=2,
            )
            await db.commit()

        async with committed_db_session_factory() as db:
            first_updated_at = await db.scalar(
                select(EmbeddingTokenUsage.updated_at).where(
                    EmbeddingTokenUsage.workspace_id == workspace.id
                )
            )

        async with committed_db_session_factory() as db:
            await record_embedding_usage(
                db,
                workspace_id=workspace.id,
                tokens=3,
            )
            await db.commit()

        async with committed_db_session_factory() as db:
            second_updated_at = await db.scalar(
                select(EmbeddingTokenUsage.updated_at).where(
                    EmbeddingTokenUsage.workspace_id == workspace.id
                )
            )

        assert first_updated_at is not None
        assert second_updated_at is not None
        assert second_updated_at > first_updated_at
    finally:
        async with committed_db_session_factory() as db:
            await db.execute(
                delete(EmbeddingTokenUsage).where(EmbeddingTokenUsage.workspace_id == workspace.id)
            )
            await db.execute(delete(Workspace).where(Workspace.id == workspace.id))
            await db.commit()


async def test_concurrent_increments_do_not_lose_updates(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workspace = build_workspace(slug=f"usage-concurrent-{uuid4().hex}")
    async with committed_db_session_factory() as db:
        db.add(workspace)
        await db.commit()

    async def increment(tokens: int) -> None:
        async with committed_db_session_factory() as db:
            await record_embedding_usage(
                db,
                workspace_id=workspace.id,
                tokens=tokens,
            )
            await db.commit()

    try:
        await asyncio.gather(increment(7), increment(11))
        async with committed_db_session_factory() as db:
            assert await get_embedding_usage(db, workspace_id=workspace.id) == 18
    finally:
        async with committed_db_session_factory() as db:
            await db.execute(
                delete(EmbeddingTokenUsage).where(EmbeddingTokenUsage.workspace_id == workspace.id)
            )
            await db.execute(delete(Workspace).where(Workspace.id == workspace.id))
            await db.commit()
