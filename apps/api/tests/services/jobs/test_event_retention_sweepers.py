"""Audit and security event retention sweeper tests."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

import services.jobs.handlers.sweep_expired_security_events as security_sweeper_module
from core.settings import Settings, settings
from models.audit_event import AuditEvent
from models.jobs import Job
from models.security import SecurityEvent
from models.user import User
from models.workspace import Workspace
from services.jobs.domain import JOB_STATUS_PENDING, JOB_STATUS_RUNNING
from services.jobs.handlers.sweep_expired_audit_events import (
    SWEEP_EXPIRED_AUDIT_EVENTS_KIND,
    ensure_audit_event_sweep_job,
    sweep_expired_audit_events,
)
from services.jobs.handlers.sweep_expired_security_events import (
    SWEEP_EXPIRED_SECURITY_EVENTS_KIND,
    ensure_security_event_sweep_job,
    handle_sweep_expired_security_events,
    sweep_expired_security_events,
)
from tests.factories import build_job, build_user, build_workspace


def _production_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "ENVIRONMENT": "production",
        "STORAGE_PROVIDER": "s3",
        "EMAIL_PROVIDER": "ses",
        "SECRET_PROVIDER": "aws_secrets_manager",
        "CREDENTIAL_MASTER_KEYS": "",
        "DATABASE_URL": (
            "postgresql+asyncpg://praxis_app:postgres@db.example.com/postgres?sslmode=require"
        ),
        "DATABASE_MAINTENANCE_URL": (
            "postgresql+asyncpg://maintenance:postgres@db.example.com/postgres?sslmode=require"
        ),
        "SECRET_KEY": "x" * 40,
        "ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "SECURE_COOKIES": True,
        "INTERNAL_SCHEDULE_TRIGGER_SECRET": "test-schedule-secret-value",
        "S3_PUBLIC_ASSETS_BUCKET": "public-assets",
        "WORKSPACE_BUCKET_PREFIX": "praxis-test",
        "AWS_REGION": "eu-west-2",
        "AWS_ACCOUNT_ID": "123456789012",
        "PUBLIC_ASSETS_BASE_URL": "https://assets.example.com",
        "INTEGRATIONS_OAUTH_REDIRECT_URI": ("https://api.example.com/integrations/oauth/callback"),
        "ARTIFACT_SHARING_ENABLED": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_event_retention_settings_enforce_positive_values_and_production_floor() -> None:
    resolved = Settings(_env_file=None)
    assert resolved.AUDIT_EVENTS_RETENTION_DAYS == 400
    assert resolved.SECURITY_EVENTS_RETENTION_DAYS == 400
    assert _production_settings().AUDIT_EVENTS_RETENTION_DAYS == 400

    staging = _production_settings(
        ENVIRONMENT="staging",
        AUDIT_EVENTS_RETENTION_DAYS=90,
        SECURITY_EVENTS_RETENTION_DAYS=90,
    )
    assert staging.AUDIT_EVENTS_RETENTION_DAYS == 90
    assert staging.SECURITY_EVENTS_RETENTION_DAYS == 90

    with pytest.raises(ValidationError, match="AUDIT_EVENTS_RETENTION_DAYS"):
        Settings(_env_file=None, AUDIT_EVENTS_RETENTION_DAYS=0)
    with pytest.raises(ValidationError, match="SECURITY_EVENTS_RETENTION_DAYS"):
        Settings(_env_file=None, SECURITY_EVENTS_RETENTION_DAYS=0)
    with pytest.raises(ValidationError, match="AUDIT_EVENTS_RETENTION_DAYS"):
        _production_settings(AUDIT_EVENTS_RETENTION_DAYS=399)
    with pytest.raises(ValidationError, match="SECURITY_EVENTS_RETENTION_DAYS"):
        _production_settings(SECURITY_EVENTS_RETENTION_DAYS=90)


async def test_sweeps_enforce_boundaries_isolation_subject_survival_and_repeat_runs(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=10)
    user = build_user(email=f"retention-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"retention-{uuid4().hex[:8]}")
    db_session.add_all([user, workspace])
    await db_session.flush()
    security_marker = f"retention-boundary-{uuid4().hex}"
    await db_session.execute(delete(SecurityEvent).where(SecurityEvent.created_at < cutoff))

    audit_rows = [
        _audit_event(workspace.id, created_at=cutoff - timedelta(microseconds=1)),
        _audit_event(workspace.id, created_at=cutoff),
        _audit_event(workspace.id, created_at=cutoff + timedelta(microseconds=1)),
    ]
    security_rows = [
        _security_event(created_at=cutoff - timedelta(microseconds=1), request_id=security_marker),
        _security_event(created_at=cutoff, request_id=security_marker),
        _security_event(created_at=cutoff + timedelta(microseconds=1), request_id=security_marker),
    ]
    db_session.add_all([*audit_rows, *security_rows])
    await db_session.flush()

    audit_result = await sweep_expired_audit_events(
        db_session,
        now=now,
        retention_days=10,
        batch_size=1,
        run_limit=10,
    )
    assert audit_result.deleted_count == 1
    assert audit_result.has_more is False
    assert set(await db_session.scalars(select(AuditEvent.id))) == {
        audit_rows[1].id,
        audit_rows[2].id,
    }
    assert set(
        await db_session.scalars(
            select(SecurityEvent.id).where(SecurityEvent.request_id == security_marker)
        )
    ) == {row.id for row in security_rows}
    assert await db_session.get(User, user.id) is not None
    assert await db_session.get(Workspace, workspace.id) is not None

    repeated_audit = await sweep_expired_audit_events(
        db_session,
        now=now,
        retention_days=10,
    )
    assert repeated_audit.deleted_count == 0
    assert repeated_audit.has_more is False

    security_result = await sweep_expired_security_events(
        db_session,
        now=now,
        retention_days=10,
        batch_size=1,
        run_limit=10,
    )
    assert security_result.deleted_count == 1
    assert security_result.has_more is False
    assert set(
        await db_session.scalars(
            select(SecurityEvent.id).where(SecurityEvent.request_id == security_marker)
        )
    ) == {
        security_rows[1].id,
        security_rows[2].id,
    }
    assert set(await db_session.scalars(select(AuditEvent.id))) == {
        audit_rows[1].id,
        audit_rows[2].id,
    }
    assert await db_session.get(User, user.id) is not None
    assert await db_session.get(Workspace, workspace.id) is not None

    repeated_security = await sweep_expired_security_events(
        db_session,
        now=now,
        retention_days=10,
    )
    assert repeated_security.deleted_count == 0
    assert repeated_security.has_more is False


async def test_security_sweep_batches_to_run_cap_and_requeues_immediately(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SECURITY_EVENTS_RETENTION_DAYS", 1)
    monkeypatch.setattr(settings, "JOBS_SWEEP_INTERVAL_SECONDS", 3600)
    monkeypatch.setattr(
        security_sweeper_module,
        "DEFAULT_SECURITY_EVENT_SWEEP_BATCH_SIZE",
        2,
    )
    monkeypatch.setattr(security_sweeper_module, "DEFAULT_SECURITY_EVENT_SWEEP_RUN_LIMIT", 3)

    old = datetime.now(UTC) - timedelta(days=2)
    cutoff = datetime.now(UTC) - timedelta(days=1)
    marker = f"retention-batching-{uuid4().hex}"
    await db_session.execute(delete(SecurityEvent).where(SecurityEvent.created_at < cutoff))
    db_session.add_all([_security_event(created_at=old, request_id=marker) for _ in range(5)])
    current = build_job(
        kind=SWEEP_EXPIRED_SECURITY_EVENTS_KIND,
        status=JOB_STATUS_RUNNING,
        content_hash=f"retention-current-{uuid4().hex}",
    )
    db_session.add(current)
    await db_session.flush()

    before_first_run = datetime.now(UTC)
    await handle_sweep_expired_security_events(db_session, current)
    assert current.payload["result"] == {"deleted_count": 3, "has_more": True}
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(SecurityEvent)
            .where(SecurityEvent.request_id == marker)
        )
        == 2
    )

    continuation = await db_session.scalar(
        select(Job).where(
            Job.kind == SWEEP_EXPIRED_SECURITY_EVENTS_KIND,
            Job.status == JOB_STATUS_PENDING,
            Job.id != current.id,
        )
    )
    assert continuation is not None
    assert continuation.run_after >= before_first_run
    assert continuation.run_after <= datetime.now(UTC)

    await handle_sweep_expired_security_events(db_session, continuation)
    assert continuation.payload["result"] == {"deleted_count": 2, "has_more": False}
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(SecurityEvent)
            .where(SecurityEvent.request_id == marker)
        )
        == 0
    )
    periodic = await db_session.scalar(
        select(Job).where(
            Job.kind == SWEEP_EXPIRED_SECURITY_EVENTS_KIND,
            Job.status == JOB_STATUS_PENDING,
            Job.id.not_in([current.id, continuation.id]),
        )
    )
    assert periodic is not None
    assert periodic.run_after > datetime.now(UTC) + timedelta(minutes=59)


async def test_event_retention_enqueuers_are_idempotent(db_session: AsyncSession) -> None:
    first_audit = await ensure_audit_event_sweep_job(db_session)
    second_audit = await ensure_audit_event_sweep_job(db_session)
    first_security = await ensure_security_event_sweep_job(db_session)
    second_security = await ensure_security_event_sweep_job(db_session)

    assert first_audit.id == second_audit.id
    assert first_audit.kind == SWEEP_EXPIRED_AUDIT_EVENTS_KIND
    assert first_audit.workspace_id is None
    assert first_audit.concurrency_user_id is None
    assert first_security.id == second_security.id
    assert first_security.kind == SWEEP_EXPIRED_SECURITY_EVENTS_KIND
    assert first_security.workspace_id is None
    assert first_security.concurrency_user_id is None


def _audit_event(workspace_id: UUID, *, created_at: datetime) -> AuditEvent:
    return AuditEvent(
        workspace_id=workspace_id,
        action="retention_test",
        resource_type="workspace",
        resource_id=str(workspace_id),
        status="success",
        summary="Retention test audit event",
        actor_type="service",
        details={},
        created_at=created_at,
        occurred_at=created_at,
    )


def _security_event(*, created_at: datetime, request_id: str | None = None) -> SecurityEvent:
    return SecurityEvent(
        event_type="retention_test",
        ip_address="192.0.2.1",
        details={},
        request_id=request_id,
        created_at=created_at,
        occurred_at=created_at,
    )
