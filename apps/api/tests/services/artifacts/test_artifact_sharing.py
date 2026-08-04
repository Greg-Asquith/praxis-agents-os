# apps/api/tests/services/artifacts/test_artifact_sharing.py

"""Artifact-sharing settings and retention tests."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import Settings, settings
from models.artifacts import ArtifactShare
from models.jobs import Job
from services.artifacts import create_artifact
from services.jobs.handlers.sweep_expired_artifact_shares import (
    SWEEP_EXPIRED_ARTIFACT_SHARES_KIND,
    ensure_artifact_shares_sweep_job,
    sweep_expired_artifact_shares,
)
from tests.factories import build_user, build_workspace
from tests.support.storage import reset_storage_provider_cache


@pytest.fixture
def local_storage_settings(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    reset_storage_provider_cache()
    try:
        yield
    finally:
        reset_storage_provider_cache()


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
        "APP_BASE_URL": "https://api.example.com",
        "FRONTEND_URL": "https://app.example.com",
        "ARTIFACT_SHARING_ENABLED": True,
        "RATE_LIMIT_ENABLED": True,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.mark.parametrize(
    "origin",
    [
        "",
        "https://app.example.com",
        "https://artifacts.app.example.com",
        "https://artifacts.example.com",
    ],
)
def test_production_sharing_requires_a_distinct_origin(origin: str) -> None:
    with pytest.raises(ValidationError, match="ARTIFACT_ORIGIN"):
        _production_settings(ARTIFACT_ORIGIN=origin)


def test_production_sharing_accepts_a_separate_origin() -> None:
    resolved = _production_settings(ARTIFACT_ORIGIN="https://praxis-artifacts.example.net")
    assert resolved.ARTIFACT_ORIGIN == "https://praxis-artifacts.example.net"


def test_production_sharing_requires_https_and_rate_limiting() -> None:
    with pytest.raises(ValidationError, match="HTTPS"):
        _production_settings(ARTIFACT_ORIGIN="http://praxis-artifacts.example.net")
    with pytest.raises(ValidationError, match="RATE_LIMIT_ENABLED"):
        _production_settings(
            ARTIFACT_ORIGIN="https://praxis-artifacts.example.net",
            RATE_LIMIT_ENABLED=False,
        )


def test_production_sharing_rejects_cookie_domain_coverage() -> None:
    with pytest.raises(ValidationError, match="COOKIE_DOMAIN"):
        _production_settings(
            ARTIFACT_ORIGIN="https://artifacts.example.net",
            COOKIE_DOMAIN=".example.net",
        )


def test_artifact_share_ttl_is_hard_capped_at_thirty_days() -> None:
    with pytest.raises(ValidationError, match="ARTIFACT_SHARE_MAX_TTL_DAYS"):
        Settings(_env_file=None, ARTIFACT_SHARE_MAX_TTL_DAYS=31)
    with pytest.raises(ValidationError, match="ARTIFACT_SHARE_DEFAULT_TTL_DAYS"):
        Settings(
            _env_file=None,
            ARTIFACT_SHARE_DEFAULT_TTL_DAYS=8,
            ARTIFACT_SHARE_MAX_TTL_DAYS=7,
        )


async def test_expired_share_sweep_deletes_expired_and_reschedules(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    user = build_user(email=f"share-sweep-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"share-sweep-{uuid4().hex[:8]}")
    db_session.add_all([user, workspace])
    await db_session.flush()
    artifact, revision = await create_artifact(
        db_session,
        workspace=workspace,
        title="Sweep fixture",
        artifact_type="markdown",
        content="# Fixture",
        actor_user_id=user.id,
    )
    now = datetime.now(UTC)
    expired = ArtifactShare(
        workspace_id=workspace.id,
        artifact_id=artifact.id,
        version_id=revision.id,
        token_hash="a" * 64,
        token_prefix="expired",  # noqa: S106 - non-secret display prefix fixture
        expires_at=now - timedelta(seconds=1),
        created_by_user_id=user.id,
    )
    live = ArtifactShare(
        workspace_id=workspace.id,
        artifact_id=artifact.id,
        version_id=revision.id,
        token_hash="b" * 64,
        token_prefix="live----",  # noqa: S106 - non-secret display prefix fixture
        expires_at=now + timedelta(days=1),
        created_by_user_id=user.id,
    )
    expired_revoked = ArtifactShare(
        workspace_id=workspace.id,
        artifact_id=artifact.id,
        version_id=revision.id,
        token_hash="c" * 64,
        token_prefix="revoked-",  # noqa: S106 - non-secret display prefix fixture
        expires_at=now - timedelta(seconds=1),
        revoked_at=now - timedelta(minutes=1),
        created_by_user_id=user.id,
        revoked_by_user_id=user.id,
    )
    db_session.add_all([expired, live, expired_revoked])
    await db_session.flush()
    existing_job_ids = set(
        (
            await db_session.scalars(
                select(Job.id).where(Job.kind == SWEEP_EXPIRED_ARTIFACT_SHARES_KIND)
            )
        ).all()
    )

    ensured = await ensure_artifact_shares_sweep_job(db_session)
    ensured_again = await ensure_artifact_shares_sweep_job(db_session)
    assert ensured_again.id == ensured.id
    await sweep_expired_artifact_shares(
        db_session,
        Job(id=uuid4(), kind=SWEEP_EXPIRED_ARTIFACT_SHARES_KIND),
    )
    assert await db_session.get(ArtifactShare, expired.id) is None
    assert await db_session.get(ArtifactShare, expired_revoked.id) is None
    assert await db_session.get(ArtifactShare, live.id) is not None
    jobs = (
        await db_session.scalars(select(Job).where(Job.kind == SWEEP_EXPIRED_ARTIFACT_SHARES_KIND))
    ).all()
    new_job_ids = {job.id for job in jobs if job.id not in existing_job_ids}
    expected_new_count = 1 + int(ensured.id not in existing_job_ids)
    assert len(new_job_ids) == expected_new_count
    assert any(job.id != ensured.id for job in jobs)
