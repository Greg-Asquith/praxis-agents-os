"""Database durability, isolation, and append-only recording tests."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from pydantic_ai.usage import RunUsage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core import database as database_module
from core.database import set_session_tenant_context
from models.ai_usage_event import AIUsageEvent
from models.workspace import Workspace
from services.agents.runtime.run_persistence import persist_failed_run
from services.ai_usage.agent_run_accounting import AgentRunMeteringContext
from services.ai_usage.domain import AIUsageEventData
from services.ai_usage.record_durable import record_ai_usage_durable
from services.ai_usage.record_in_transaction import record_ai_usage_in_transaction
from tests.factories import build_workspace
from tests.support.database import make_async_test_database_url
from tests.support.scenario import build_scenario_agent

pytestmark = pytest.mark.asyncio


def _event(workspace_id, **overrides) -> AIUsageEventData:
    values = {
        "workspace_id": workspace_id,
        "provider": "openai",
        "model": "gpt-5.6-luna",
        "purpose": "conversation_naming",
        "input_tokens": 12,
        "output_tokens": 4,
        "requests": 1,
    }
    values.update(overrides)
    return AIUsageEventData(**values)


async def _committed_workspace(
    session_factory: async_sessionmaker[AsyncSession],
) -> Workspace:
    workspace = build_workspace(name="Metering", slug=f"metering-{uuid4().hex}")
    async with session_factory() as db:
        db.add(workspace)
        await db.commit()
    return workspace


async def test_durable_record_survives_caller_rollback(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workspace = await _committed_workspace(committed_db_session_factory)
    async with committed_db_session_factory() as caller:
        await set_session_tenant_context(caller, workspace_id=workspace.id)
        await caller.execute(sa.select(Workspace.id).where(Workspace.id == workspace.id))
        assert await record_ai_usage_durable(_event(workspace.id))
        await caller.rollback()

    async with committed_db_session_factory() as verify:
        await set_session_tenant_context(verify, workspace_id=workspace.id)
        events = (await verify.scalars(sa.select(AIUsageEvent))).all()
        assert len(events) == 1
        assert events[0].requests == 1
        await verify.delete(workspace)
        await verify.commit()


async def test_durable_pool_progresses_while_normal_pool_is_saturated(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    migrated_test_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = await _committed_workspace(committed_db_session_factory)
    normal_engine = create_async_engine(
        make_async_test_database_url(migrated_test_database),
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.2,
    )
    normal_factory = async_sessionmaker(normal_engine, expire_on_commit=False)
    monkeypatch.setattr(database_module, "_async_engine", normal_engine)
    monkeypatch.setattr(database_module, "_async_session_factory", normal_factory)

    async with normal_factory() as held:
        await held.execute(sa.text("SELECT 1"))
        assert await asyncio.wait_for(record_ai_usage_durable(_event(workspace.id)), timeout=1)

    await normal_engine.dispose()
    async with committed_db_session_factory() as cleanup:
        await set_session_tenant_context(cleanup, workspace_id=workspace.id)
        await cleanup.delete(workspace)
        await cleanup.commit()


async def test_caller_transaction_recorder_uses_savepoint_on_failure(
    db_session: AsyncSession,
) -> None:
    workspace = build_workspace(name="Savepoint", slug=f"savepoint-{uuid4().hex}")
    db_session.add(workspace)
    await db_session.flush()
    failed = await record_ai_usage_in_transaction(
        db_session,
        _event(workspace.id, agent_id=uuid4()),
    )
    assert not failed
    assert await db_session.scalar(sa.select(sa.literal(1))) == 1


async def test_concurrent_terminal_finalization_records_one_event(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await build_scenario_agent(committed_db_session_factory)
    metering = AgentRunMeteringContext(
        invocation_started_at=datetime.now(UTC),
        baseline={
            "input_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "output_tokens": 0,
            "requests": 0,
        },
        usage=RunUsage(input_tokens=9, output_tokens=3, requests=1),
        provider="openai",
        model="gpt-5.6-luna",
    )

    async def finalize() -> None:
        async with committed_db_session_factory() as db:
            await set_session_tenant_context(
                db,
                workspace_id=context.workspace_id,
                user_id=context.user_id,
            )
            await persist_failed_run(
                db,
                run_id=context.run_id,
                error_code="test_failure",
                error_message="test",
                metering=metering,
            )

    await asyncio.gather(finalize(), finalize())

    async with committed_db_session_factory() as verify:
        await set_session_tenant_context(verify, workspace_id=context.workspace_id)
        events = (
            await verify.scalars(
                sa.select(AIUsageEvent).where(AIUsageEvent.run_id == context.run_id)
            )
        ).all()
        assert len(events) == 1
        assert events[0].requests == 1
