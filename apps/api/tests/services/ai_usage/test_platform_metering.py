"""Platform ingestion admission, ownership, and durable metering tests."""

import asyncio
from uuid import uuid4

import pytest
import sqlalchemy as sa
from pydantic_ai.usage import RunUsage
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import maintenance_async_db_session
from core.exceptions.auth import AuthorizationError
from core.exceptions.general import RateLimitError
from core.settings import settings
from models.ai_usage_event import AIUsageEvent
from models.embedding_usage import EmbeddingTokenUsage
from models.platform_ingestion_usage import PlatformIngestionUsage
from services.ai_usage.admit_platform_ingestion import admit_platform_ingestion
from services.ai_usage.domain import AIUsageEventData
from services.ai_usage.run_metered_helper import run_metered_helper
from services.embeddings.domain import EmbeddingProviderPartialUsageError
from services.embeddings.embed_texts import embed_texts
from tests.support.embeddings import (
    PartialUsageFailingProvider,
    RecordingProvider,
)
from utils.content import ContentScope


def _event(**overrides) -> AIUsageEventData:
    values = {
        "workspace_id": None,
        "scope": ContentScope.PLATFORM,
        "provider": "test",
        "model": "metered-test",
        "purpose": "kb_annotation",
    }
    values.update(overrides)
    return AIUsageEventData(**values)


@pytest.mark.parametrize(
    "overrides",
    [
        {"scope": ContentScope.WORKSPACE},
        {"workspace_id": uuid4()},
        {"workspace_id": "not-an-owner"},
        {"scope": "unknown"},
        {"purpose": "agent_run"},
        {"purpose": "embedding_kb_search"},
        {"agent_id": uuid4()},
        {"run_id": uuid4()},
        {"conversation_id": uuid4()},
    ],
)
def test_platform_usage_rejects_invalid_ownership(overrides) -> None:
    with pytest.raises(ValueError):
        _event(**overrides)


async def test_platform_provider_work_requires_maintenance() -> None:
    provider = RecordingProvider()

    async def call(usage: RunUsage) -> str:
        pytest.fail("Unauthorised helper reached the provider")

    async with AsyncSession() as db:
        with pytest.raises(AuthorizationError, match="maintenance"):
            await embed_texts(
                db,
                ["text"],
                workspace_id=None,
                scope=ContentScope.PLATFORM,
                purpose="embedding_kb_ingest",
                provider=provider,
            )
        for helper_db in (None, db):
            with pytest.raises(AuthorizationError, match="maintenance"):
                await run_metered_helper(_event(), call, db=helper_db)
    assert provider.call_sizes == []


@pytest.fixture
async def platform_metering_db(committed_db_session_factory):
    async def clear() -> None:
        async with maintenance_async_db_session() as db:
            await db.execute(sa.delete(AIUsageEvent).where(AIUsageEvent.scope == "platform"))
            await db.execute(
                sa.delete(EmbeddingTokenUsage).where(EmbeddingTokenUsage.scope == "platform")
            )
            await db.execute(sa.delete(PlatformIngestionUsage))

    await clear()
    yield
    await clear()


async def test_concurrent_budget_reservations_survive_caller_rollback(
    platform_metering_db, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "PLATFORM_INGESTION_MONTHLY_CALL_BUDGET", 3)

    async def reserve() -> bool:
        async with maintenance_async_db_session() as db:
            try:
                await admit_platform_ingestion(db)
            except RateLimitError:
                return False
            await db.rollback()
            return True

    results = await asyncio.gather(*(reserve() for _ in range(8)))
    assert sum(results) == 3
    async with maintenance_async_db_session() as db:
        assert await db.scalar(sa.select(PlatformIngestionUsage.requests_reserved)) == 3


async def test_exhausted_budget_blocks_embedding_and_helper_provider_work(
    platform_metering_db, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "PLATFORM_INGESTION_MONTHLY_CALL_BUDGET", 1)
    provider = RecordingProvider()

    async def call(usage: RunUsage) -> str:
        pytest.fail("Exhausted budget reached the provider")

    async with maintenance_async_db_session() as db:
        await admit_platform_ingestion(db)
        with pytest.raises(RateLimitError, match="monthly call budget"):
            await embed_texts(
                db,
                ["text"],
                workspace_id=None,
                scope=ContentScope.PLATFORM,
                purpose="embedding_kb_ingest",
                provider=provider,
            )
        with pytest.raises(RateLimitError, match="monthly call budget"):
            await run_metered_helper(_event(), call, db=db)
    assert provider.call_sizes == []


@pytest.mark.parametrize("fails", [False, True])
async def test_platform_embedding_ledger_and_total_survive_caller_rollback(
    platform_metering_db, fails
) -> None:
    provider = PartialUsageFailingProvider() if fails else RecordingProvider()
    async with maintenance_async_db_session() as db:
        if fails:
            with pytest.raises(EmbeddingProviderPartialUsageError):
                await embed_texts(
                    db,
                    ["text"],
                    workspace_id=None,
                    scope=ContentScope.PLATFORM,
                    purpose="embedding_kb_ingest",
                    provider=provider,
                )
        else:
            await embed_texts(
                db,
                ["text"],
                workspace_id=None,
                scope=ContentScope.PLATFORM,
                purpose="embedding_kb_ingest",
                provider=provider,
            )
        await db.rollback()

    async with maintenance_async_db_session() as db:
        events = (
            await db.scalars(sa.select(AIUsageEvent).where(AIUsageEvent.scope == "platform"))
        ).all()
        assert len(events) == 1
        assert events[0].workspace_id is None
        assert events[0].input_tokens == (4 if fails else 3)
        assert events[0].requests == 1
        total = await db.scalar(
            sa.select(EmbeddingTokenUsage).where(EmbeddingTokenUsage.scope == "platform")
        )
        assert total.workspace_id is None
        assert total.tokens_used == events[0].input_tokens
        assert await db.scalar(sa.select(PlatformIngestionUsage.requests_reserved)) == 1


@pytest.mark.parametrize("fails", [False, True])
async def test_platform_helper_retains_usage_and_reservation(platform_metering_db, fails) -> None:
    async def call(usage: RunUsage) -> str:
        usage.requests = 2
        usage.input_tokens = 7
        if fails:
            raise LookupError("provider failure")
        return "annotation"

    async with maintenance_async_db_session() as db:
        if fails:
            with pytest.raises(LookupError, match="provider failure"):
                await run_metered_helper(_event(), call, db=db)
        else:
            assert await run_metered_helper(_event(), call, db=db) == "annotation"
        await db.rollback()

    async with maintenance_async_db_session() as db:
        events = (
            await db.scalars(sa.select(AIUsageEvent).where(AIUsageEvent.scope == "platform"))
        ).all()
        assert len(events) == 1
        assert events[0].input_tokens == 7
        assert events[0].requests == 2
        assert events[0].workspace_id is None
        assert await db.scalar(sa.select(PlatformIngestionUsage.requests_reserved)) == 1
        assert (
            await db.scalar(
                sa.select(sa.func.count())
                .select_from(EmbeddingTokenUsage)
                .where(EmbeddingTokenUsage.scope == "platform")
            )
            == 0
        )


async def test_platform_budget_does_not_charge_or_block_workspace_embeddings(
    platform_metering_db, committed_db_session_factory, monkeypatch
) -> None:
    from core.database import set_session_tenant_context
    from services.embeddings.get_embedding_usage import get_embedding_usage
    from tests.factories import build_workspace

    monkeypatch.setattr(settings, "PLATFORM_INGESTION_MONTHLY_CALL_BUDGET", 1)
    workspace = build_workspace(slug=f"platform-metering-{uuid4().hex}")
    async with committed_db_session_factory() as db:
        db.add(workspace)
        await db.commit()
    try:
        async with maintenance_async_db_session() as db:
            await embed_texts(
                db,
                ["platform text"],
                workspace_id=None,
                scope=ContentScope.PLATFORM,
                purpose="embedding_kb_ingest",
                provider=RecordingProvider(),
            )
        async with committed_db_session_factory() as db:
            await set_session_tenant_context(db, workspace_id=workspace.id)
            assert await get_embedding_usage(db, workspace_id=workspace.id) == 0
            result = await embed_texts(
                db,
                ["workspace text"],
                workspace_id=workspace.id,
                purpose="embedding_kb_ingest",
                provider=RecordingProvider(),
            )
            assert result.total_tokens == 3
            assert await get_embedding_usage(db, workspace_id=workspace.id) == 3
            events = (
                await db.scalars(
                    sa.select(AIUsageEvent).where(AIUsageEvent.workspace_id == workspace.id)
                )
            ).all()
            assert len(events) == 1
            assert events[0].scope == ContentScope.WORKSPACE
            await db.commit()
        async with maintenance_async_db_session() as db:
            assert await db.scalar(sa.select(PlatformIngestionUsage.requests_reserved)) == 1
            assert (
                await db.scalar(
                    sa.select(EmbeddingTokenUsage.tokens_used).where(
                        EmbeddingTokenUsage.scope == ContentScope.PLATFORM
                    )
                )
                == 3
            )
    finally:
        async with committed_db_session_factory() as db:
            await set_session_tenant_context(db, workspace_id=workspace.id)
            await db.delete(workspace)
            await db.commit()


@pytest.mark.parametrize("budget", [0, -1, 1_000_001])
def test_platform_ingestion_budget_rejects_invalid_limits(budget: int) -> None:
    from pydantic import ValidationError

    from core.settings import Settings

    with pytest.raises(ValidationError, match="PLATFORM_INGESTION_MONTHLY_CALL_BUDGET"):
        Settings(PLATFORM_INGESTION_MONTHLY_CALL_BUDGET=budget)


async def test_budget_exhaustion_after_completed_batch_records_partial_usage(
    platform_metering_db, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "PLATFORM_INGESTION_MONTHLY_CALL_BUDGET", 1)
    monkeypatch.setattr(settings, "EMBEDDINGS_MAX_BATCH_TEXTS", 1)
    provider = RecordingProvider()
    async with maintenance_async_db_session() as db:
        with pytest.raises(RateLimitError, match="monthly call budget"):
            await embed_texts(
                db,
                ["first", "second"],
                workspace_id=None,
                scope=ContentScope.PLATFORM,
                purpose="embedding_kb_ingest",
                provider=provider,
            )
        await db.rollback()
    assert provider.call_sizes == [1]
    async with maintenance_async_db_session() as db:
        events = (
            await db.scalars(
                sa.select(AIUsageEvent).where(AIUsageEvent.scope == ContentScope.PLATFORM)
            )
        ).all()
        assert len(events) == 1
        assert events[0].input_tokens == 3
        assert events[0].requests == 1
        assert (
            await db.scalar(
                sa.select(EmbeddingTokenUsage.tokens_used).where(
                    EmbeddingTokenUsage.scope == ContentScope.PLATFORM
                )
            )
            == 3
        )
        assert await db.scalar(sa.select(PlatformIngestionUsage.requests_reserved)) == 1


async def test_empty_platform_embedding_does_not_reserve_budget(platform_metering_db) -> None:
    provider = RecordingProvider()
    async with maintenance_async_db_session() as db:
        result = await embed_texts(
            db,
            [],
            workspace_id=None,
            scope=ContentScope.PLATFORM,
            purpose="embedding_kb_ingest",
            provider=provider,
        )
    assert result.requests == 0
    assert provider.call_sizes == []
    async with maintenance_async_db_session() as db:
        assert await db.scalar(sa.select(sa.func.count()).select_from(PlatformIngestionUsage)) == 0
        assert (
            await db.scalar(
                sa.select(sa.func.count())
                .select_from(AIUsageEvent)
                .where(AIUsageEvent.scope == ContentScope.PLATFORM)
            )
            == 0
        )
