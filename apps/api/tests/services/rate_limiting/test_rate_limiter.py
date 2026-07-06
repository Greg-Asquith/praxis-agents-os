"""Tests for the PostgreSQL-backed rate limiter."""

from datetime import UTC, datetime, timedelta
from ipaddress import ip_address

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import core.rate_limiting as rate_limiting_module
from core.rate_limiting import RateLimiter, normalize_endpoint
from core.settings import settings
from models.jobs import Job
from models.rate_limiting import RateLimitAttempt
from services.jobs.domain import JOB_STATUS_PENDING
from services.jobs.handlers.sweep_rate_limit_attempts import sweep_rate_limit_attempts
from tests.factories import build_job

pytestmark = pytest.mark.asyncio


async def test_normalize_endpoint_collapses_uuid_and_numeric_segments() -> None:
    assert (
        normalize_endpoint("/api/v1/conversations/9b2f4f3a-5f61-49e1-9df8-9f083f8d7a1c/messages")
        == "/api/v1/conversations/{id}/messages"
    )
    assert normalize_endpoint("/api/v1/files/123/revisions/456") == (
        "/api/v1/files/{id}/revisions/{id}"
    )
    assert normalize_endpoint("/api/v1/auth/login") == "/api/v1/auth/login"


async def test_check_rate_limit_increments_existing_bucket(db_session: AsyncSession) -> None:
    limiter = RateLimiter()

    first = await limiter.check_rate_limit(
        ip="203.0.113.10",
        endpoint="/api/v1/auth/login",
        limit_type="login_attempts",
        db=db_session,
    )
    second = await limiter.check_rate_limit(
        ip="203.0.113.10",
        endpoint="/api/v1/auth/login",
        limit_type="login_attempts",
        db=db_session,
    )

    assert first.attempts == 1
    assert second.attempts == 2
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(RateLimitAttempt)
            .where(
                RateLimitAttempt.ip_address == "203.0.113.10",
                RateLimitAttempt.endpoint == "/api/v1/auth/login",
                RateLimitAttempt.limit_type == "login_attempts",
            )
        )
        == 1
    )


async def test_check_rate_limit_denies_after_limit(db_session: AsyncSession) -> None:
    limiter = RateLimiter()

    results = [
        await limiter.check_rate_limit(
            ip="203.0.113.11",
            endpoint="/api/v1/auth/login",
            limit_type="login_attempts",
            custom_limit=3,
            custom_window=60,
            db=db_session,
        )
        for _ in range(4)
    ]

    assert [result.allowed for result in results] == [True, True, True, False]
    assert results[-1].attempts == 4
    assert results[-1].retry_after is not None
    assert results[-1].retry_after > 0


async def test_check_rate_limit_uses_new_bucket_after_window_rollover(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limiter = RateLimiter()

    class FrozenDateTime(datetime):
        current = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return cls.current.replace(tzinfo=None)
            return cls.current.astimezone(tz)

    monkeypatch.setattr(rate_limiting_module, "datetime", FrozenDateTime)

    first = await limiter.check_rate_limit(
        ip="203.0.113.12",
        endpoint="/api/v1/auth/login",
        limit_type="login_attempts",
        custom_limit=3,
        custom_window=60,
        db=db_session,
    )
    FrozenDateTime.current = FrozenDateTime.current + timedelta(seconds=61)
    second = await limiter.check_rate_limit(
        ip="203.0.113.12",
        endpoint="/api/v1/auth/login",
        limit_type="login_attempts",
        custom_limit=3,
        custom_window=60,
        db=db_session,
    )

    assert first.attempts == 1
    assert second.attempts == 1
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(RateLimitAttempt)
            .where(
                RateLimitAttempt.ip_address == "203.0.113.12",
                RateLimitAttempt.endpoint == "/api/v1/auth/login",
            )
        )
        == 2
    )


async def test_invalid_ip_is_denied_with_most_restrictive_limit(
    db_session: AsyncSession,
) -> None:
    limiter = RateLimiter()

    result = await limiter.check_rate_limit(
        ip="not-an-ip",
        endpoint="/api/v1/auth/login",
        limit_type="login_attempts",
        db=db_session,
    )

    assert result.allowed is False
    assert result.limit == 1
    assert result.retry_after == 3600


async def test_disabled_limiter_allows_without_limit(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limiter = RateLimiter()
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    monkeypatch.setattr(limiter, "enabled", settings.RATE_LIMIT_ENABLED)

    result = await limiter.check_rate_limit(
        ip="203.0.113.13",
        endpoint="/api/v1/auth/login",
        limit_type="login_attempts",
        db=db_session,
    )

    assert result.allowed is True
    assert result.limit is None
    assert result.attempts == 0


async def test_sweep_rate_limit_attempts_deletes_old_rows_and_reschedules(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    monkeypatch.setattr(settings, "RATE_LIMIT_RETENTION_SECONDS", 86400)
    old_attempt = RateLimitAttempt(
        ip_address="203.0.113.14",
        endpoint="/api/v1/auth/login",
        limit_type="login_attempts",
        window_seconds=3600,
        attempts=2,
        window_start=now - timedelta(days=2),
        created_at=now - timedelta(days=2),
        updated_at=now - timedelta(days=2),
    )
    fresh_attempt = RateLimitAttempt(
        ip_address="203.0.113.15",
        endpoint="/api/v1/auth/login",
        limit_type="login_attempts",
        window_seconds=3600,
        attempts=1,
        window_start=now,
        created_at=now,
        updated_at=now,
    )
    current_job = build_job(kind="rate_limits.sweep_attempts", payload={"current": True})
    db_session.add_all([old_attempt, fresh_attempt, current_job])
    await db_session.flush()

    await sweep_rate_limit_attempts(db_session, current_job)

    remaining_attempts = set(
        await db_session.scalars(
            select(RateLimitAttempt.ip_address).where(
                RateLimitAttempt.endpoint == "/api/v1/auth/login",
                RateLimitAttempt.limit_type == "login_attempts",
            )
        )
    )
    assert ip_address("203.0.113.14") not in remaining_attempts
    assert ip_address("203.0.113.15") in remaining_attempts
    follow_up = await db_session.scalar(
        select(Job).where(
            Job.kind == "rate_limits.sweep_attempts",
            Job.status == JOB_STATUS_PENDING,
            Job.content_hash == f"rate-limit-sweep:{current_job.id}",
        )
    )
    assert follow_up is not None
