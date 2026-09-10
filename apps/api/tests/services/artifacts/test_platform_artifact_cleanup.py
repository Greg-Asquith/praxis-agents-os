# apps/api/tests/services/artifacts/test_platform_artifact_cleanup.py

"""Platform Artifact retention bounds storage effects and preserves retries."""

import hashlib
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from core.database import maintenance_async_db_session
from models.artifacts import Artifact, ArtifactRevision
from models.jobs import Job
from services.jobs.handlers import sweep_platform_artifacts as module
from services.storage.domain import StorageBucket, make_storage_object_ref

pytestmark = pytest.mark.asyncio


async def _artifact(db, *, expired=True, deleted=True, versions=1):
    artifact = Artifact(
        scope="platform",
        artifact_type="html",
        title="Retained report",
        deleted=deleted,
        deleted_at=datetime.now(UTC) - timedelta(days=31 if expired else 1) if deleted else None,
    )
    db.add(artifact)
    await db.flush()
    revisions = []
    for number in range(1, versions + 1):
        revision_id = uuid4()
        revision = ArtifactRevision(
            id=revision_id,
            scope="platform",
            artifact_id=artifact.id,
            revision_number=number,
            revision_kind="restore" if revisions else "create",
            restored_from_revision_id=revisions[0].id if revisions else None,
            content_type="text/html",
            extension=".html",
            size_bytes=3,
            content_hash="abc",
            object_key=f"platform/artifacts/{artifact.id}/{revision_id}.html",
            created_by_system=True,
        )
        db.add(revision)
        await db.flush()
        revisions.append(revision)
    artifact.current_version_id = revisions[-1].id
    await db.flush()
    return artifact, revisions


async def test_platform_artifact_retention_requires_unowned_maintenance(db_session):
    with pytest.raises(RuntimeError, match="unowned maintenance"):
        await module.sweep_platform_artifacts(db_session, Job(id=uuid4()))
    async with maintenance_async_db_session() as db:
        for job in (
            Job(id=uuid4(), workspace_id=uuid4()),
            Job(id=uuid4(), concurrency_user_id=uuid4()),
        ):
            with pytest.raises(RuntimeError, match="unowned maintenance"):
                await module.sweep_platform_artifacts(db, job)


async def test_platform_artifact_retention_bounds_revisions_and_preserves_live_rows(
    db_session, monkeypatch
):
    provider = AsyncMock()
    monkeypatch.setattr(module, "get_storage_provider", lambda: provider)
    monkeypatch.setattr(module, "_SWEEP_BATCH_SIZE", 1)
    async with maintenance_async_db_session() as db:
        expired, revisions = await _artifact(db, versions=2)
        recent, _ = await _artifact(db, expired=False)
        live, _ = await _artifact(db, deleted=False)
        await module.sweep_platform_artifacts(db, Job(id=uuid4()))
        assert provider.delete_object.await_count == 2
        ref = provider.delete_object.await_args_list[0].args[0]
        assert ref.bucket == StorageBucket.PLATFORM_PRIVATE
        assert ref.key == revisions[1].object_key
        assert await db.get(ArtifactRevision, revisions[1].id) is None
        assert await db.get(ArtifactRevision, revisions[0].id) is not None
        assert await db.get(Artifact, expired.id) is not None
        await module.sweep_platform_artifacts(db, Job(id=uuid4()))
        assert provider.delete_object.await_count == 4
        assert await db.get(Artifact, expired.id) is None
        assert await db.get(Artifact, recent.id) is not None
        assert await db.get(Artifact, live.id) is not None


@pytest.mark.parametrize("failure", ["destination", "stage"])
async def test_platform_artifact_storage_failure_retains_revision_for_retry(
    db_session, monkeypatch, failure
):
    provider = AsyncMock()
    monkeypatch.setattr(module, "get_storage_provider", lambda: provider)
    async with maintenance_async_db_session() as db:
        artifact, revisions = await _artifact(db)
    provider.delete_object.side_effect = (
        OSError("storage unavailable")
        if failure == "destination"
        else [None, OSError("storage unavailable")]
    )
    with pytest.raises(OSError, match="storage unavailable"):
        async with maintenance_async_db_session() as db:
            await module.sweep_platform_artifacts(db, Job(id=uuid4()))
    async with maintenance_async_db_session() as db:
        persisted = await db.get(Artifact, artifact.id)
        assert persisted.current_version_id == revisions[0].id
        assert await db.get(ArtifactRevision, revisions[0].id) is not None
        provider.delete_object.side_effect = None
        await module.sweep_platform_artifacts(db, Job(id=uuid4()))
        assert await db.get(Artifact, artifact.id) is None


async def test_platform_artifact_retention_ensures_one_successor(db_session):
    async with maintenance_async_db_session() as db:
        await module.ensure_platform_artifacts_sweep_job(db)
        await module.ensure_platform_artifacts_sweep_job(db)
        jobs = list(
            await db.scalars(select(Job).where(Job.kind == module.SWEEP_PLATFORM_ARTIFACTS_KIND))
        )
        assert len(jobs) == 1
        assert jobs[0].workspace_id is jobs[0].concurrency_user_id is None


async def test_platform_artifact_purge_removes_orphan_copy_stage(db_session, monkeypatch):
    provider = AsyncMock()
    monkeypatch.setattr(module, "get_storage_provider", lambda: provider)
    async with maintenance_async_db_session() as db:
        artifact, revisions = await _artifact(db)
        destination = make_storage_object_ref(
            StorageBucket.PLATFORM_PRIVATE, revisions[0].object_key
        )
        stage = make_storage_object_ref(
            StorageBucket.PLATFORM_PRIVATE,
            f"platform/copy-staging/{hashlib.sha256(destination.uri.encode()).hexdigest()}",
        )
        objects = {destination.uri: b"published bytes", stage.uri: b"orphan stage"}

        async def delete_object(ref):
            objects.pop(ref.uri, None)

        provider.delete_object.side_effect = delete_object
        await module.sweep_platform_artifacts(db, Job(id=uuid4()))
        assert objects == {}
        assert await db.get(Artifact, artifact.id) is None
        assert await db.get(ArtifactRevision, revisions[0].id) is None
