# apps/api/tests/services/auth/test_two_factor_concurrency.py

"""Concurrent 2FA verifications against real Postgres row locks."""

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.auth.sessions import session_manager
from models.session import Session
from models.user import User
from services.auth.totp.utils import verify_and_consume_login_second_factor
from tests.factories import build_user

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def committed_user_id(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[UUID]:
    user = build_user(email=f"two-factor-{uuid4().hex[:8]}@example.com")
    async with committed_db_session_factory() as setup:
        setup.add(user)
        await setup.commit()
    try:
        yield user.id
    finally:
        async with committed_db_session_factory() as cleanup:
            await cleanup.execute(delete(Session).where(Session.user_id == user.id))
            await cleanup.execute(delete(User).where(User.id == user.id))
            await cleanup.commit()


async def test_concurrent_upgrades_of_one_partial_session_mint_one_session(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    committed_user_id: UUID,
) -> None:
    async with committed_db_session_factory() as setup:
        partial = await session_manager.create_partial_session(setup, str(committed_user_id))
        await setup.commit()

    async def upgrade() -> dict | None:
        async with committed_db_session_factory() as db:
            upgraded = await session_manager.upgrade_partial_session(db, partial["session_token"])
            await db.commit()
            return upgraded

    results = await asyncio.gather(upgrade(), upgrade())

    assert sum(result is not None for result in results) == 1


async def test_concurrent_uses_of_one_backup_code_succeed_once(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    committed_user_id: UUID,
) -> None:
    async with committed_db_session_factory() as setup:
        user = await setup.get(User, committed_user_id)
        code = (await user.generate_backup_codes_async())[0]
        await setup.commit()

    first_db = committed_db_session_factory()
    second_db = committed_db_session_factory()
    async with first_db, second_db:
        # Both requests hold the unconsumed list in memory before either verifies.
        first_user = await first_db.get(User, committed_user_id)
        second_user = await second_db.get(User, committed_user_id)

        async def verify(db: AsyncSession, user: User) -> bool:
            verified = await verify_and_consume_login_second_factor(
                db, user=user, token=None, backup_code=code
            )
            await (db.commit() if verified else db.rollback())
            return verified

        results = await asyncio.gather(
            verify(first_db, first_user),
            verify(second_db, second_user),
        )

    assert sorted(results) == [False, True]
    async with committed_db_session_factory() as check:
        assert (await check.get(User, committed_user_id)).backup_codes_remaining == 7
