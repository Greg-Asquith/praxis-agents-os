"""Committed cleanup ownership and worker races for platform Artifact saves."""

import asyncio
import importlib
from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from sqlalchemy import func, select

from core.database import maintenance_async_db_session
from core.exceptions.auth import AuthorizationError
from core.exceptions.general import ConflictError
from models.artifacts import Artifact, ArtifactRevision
from models.audit_event import AuditEvent
from models.jobs import Job
from models.workspace import WorkspaceMembership, WorkspaceRole
from services.artifacts.domain import CLEANUP_PLATFORM_ARTIFACT_OBJECT_KIND
from services.jobs.claim_jobs import claim_jobs
from services.jobs.domain import JOB_STATUS_PENDING, JOB_STATUS_RUNNING, JOB_STATUS_SUCCEEDED
from services.jobs.handlers.cleanup_platform_artifact_object import (
    cleanup_platform_artifact_object,
)
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.factory import get_storage_provider
from tests.services.artifacts.test_platform_artifact_concurrency import (
    _edit,
    committed_artifact_context as committed_artifact_context,
)


@pytest.mark.parametrize("failure", ["storage", "audit"])
async def test_failed_save_retains_committed_cleanup_for_written_bytes(
    committed_db_session_factory, committed_artifact_context, monkeypatch, failure
):
    context, _membership_id, artifact = committed_artifact_context
    provider = get_storage_provider()
    original_put = provider.put_object

    async def write_then_lose_response(*args, **kwargs):
        await original_put(*args, **kwargs)
        raise OSError("Storage response lost")

    if failure == "storage":
        monkeypatch.setattr(provider, "put_object", write_then_lose_response)
    else:
        module = importlib.import_module("services.artifacts.platform.utils")
        monkeypatch.setattr(
            module,
            "record_platform_content_audit_event",
            AsyncMock(side_effect=OSError("Audit unavailable")),
        )

    with pytest.raises(OSError):
        await _edit(committed_db_session_factory, context, artifact, "<p>Failed save</p>")

    async with maintenance_async_db_session() as db:
        job = (
            await db.scalars(
                select(Job).where(
                    Job.subject_id == artifact.id,
                    Job.kind == CLEANUP_PLATFORM_ARTIFACT_OBJECT_KIND,
                )
            )
        ).one()
        assert job.status == JOB_STATUS_PENDING and job.attempts == 0
        assert job.workspace_id is job.concurrency_user_id is None
        assert await db.get(ArtifactRevision, UUID(job.payload["revision_id"])) is None
        persisted = await db.get(Artifact, artifact.id)
        assert persisted.current_version_id == artifact.current_version_id
        assert persisted.published_version_id == artifact.published_version_id
        assert (
            await db.scalar(select(AuditEvent.id).where(AuditEvent.resource_id == str(artifact.id)))
            is None
        )
        source = await db.get(ArtifactRevision, artifact.current_version_id)

    ref = make_storage_object_ref(
        StorageBucket.PLATFORM_PRIVATE,
        f"platform/artifacts/{artifact.id}/{job.payload['revision_id']}{job.payload['extension']}",
    )
    assert await provider.stat_object(ref) is not None
    async with maintenance_async_db_session() as db:
        await cleanup_platform_artifact_object(db, await db.get(Job, job.id))
    assert await provider.stat_object(ref) is None
    assert (
        await provider.stat_object(
            make_storage_object_ref(StorageBucket.PLATFORM_PRIVATE, source.object_key)
        )
        is not None
    )


@pytest.mark.parametrize(
    "cleanup_status", [JOB_STATUS_RUNNING, JOB_STATUS_SUCCEEDED, JOB_STATUS_PENDING]
)
async def test_save_rejects_a_reservation_claimed_before_its_write_transaction(
    committed_db_session_factory, committed_artifact_context, monkeypatch, cleanup_status
):
    context, _membership_id, artifact = committed_artifact_context
    module = importlib.import_module("services.artifacts.platform.update_artifact")
    original_reserve = module.reserve_revision

    async def claim_before_save(*args, **kwargs):
        reservation = await original_reserve(*args, **kwargs)
        async with maintenance_async_db_session() as db:
            job = await db.get(Job, reservation.id)
            # Select only this reservation without changing unrelated queued work.
            job.priority = -(2**31)
        async with maintenance_async_db_session() as db:
            claimed = await claim_jobs(
                db,
                owner_instance_id="artifact-cleanup-test",
                now=reservation.run_after + timedelta(seconds=1),
                batch_size=1,
            )
            assert [job.id for job in claimed] == [reservation.id]
            job = claimed[0]
            assert job.attempts == 1
            job.status = cleanup_status
            if cleanup_status != JOB_STATUS_RUNNING:
                await cleanup_platform_artifact_object(db, job)
        return reservation

    monkeypatch.setattr(module, "reserve_revision", claim_before_save)
    put = AsyncMock(side_effect=AssertionError("An expired save must not write bytes"))
    monkeypatch.setattr(get_storage_provider(), "put_object", put)

    with pytest.raises(ConflictError, match="save expired"):
        await _edit(committed_db_session_factory, context, artifact, "<p>Expired save</p>")

    put.assert_not_awaited()
    async with maintenance_async_db_session() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(ArtifactRevision)
                .where(ArtifactRevision.artifact_id == artifact.id)
            )
            == 1
        )
        persisted = await db.get(Artifact, artifact.id)
        assert persisted.current_version_id == artifact.current_version_id


@pytest.mark.parametrize("change", ["removed", "demoted"])
async def test_authority_is_rechecked_after_cleanup_reservation_commits(
    committed_db_session_factory, committed_artifact_context, monkeypatch, change
):
    context, membership_id, artifact = committed_artifact_context
    module = importlib.import_module("services.artifacts.platform.update_artifact")
    original_reserve = module.reserve_revision

    async def revoke_after_reservation(*args, **kwargs):
        reservation = await original_reserve(*args, **kwargs)
        async with maintenance_async_db_session() as db:
            membership = await db.get(WorkspaceMembership, membership_id)
            if change == "removed":
                membership.deleted = True
            else:
                membership.role = WorkspaceRole.READ_ONLY
        return reservation

    monkeypatch.setattr(module, "reserve_revision", revoke_after_reservation)
    put = AsyncMock(side_effect=AssertionError("A revoked editor must not write bytes"))
    monkeypatch.setattr(get_storage_provider(), "put_object", put)
    with pytest.raises(AuthorizationError):
        await _edit(committed_db_session_factory, context, artifact, "<p>Denied save</p>")
    put.assert_not_awaited()
    async with maintenance_async_db_session() as db:
        persisted = await db.get(Artifact, artifact.id)
        assert persisted.current_version_id == artifact.current_version_id
        assert (
            await db.scalar(
                select(func.count())
                .select_from(Job)
                .where(
                    Job.subject_id == artifact.id,
                    Job.kind == CLEANUP_PLATFORM_ARTIFACT_OBJECT_KIND,
                )
            )
            == 1
        )


async def test_worker_skips_cleanup_while_save_holds_reservation_lock(
    committed_db_session_factory, committed_artifact_context, monkeypatch
):
    context, _membership_id, artifact = committed_artifact_context
    provider = get_storage_provider()
    original_put = provider.put_object
    write_started = asyncio.Event()
    resume = asyncio.Event()

    async def pause_write(*args, **kwargs):
        write_started.set()
        await resume.wait()
        return await original_put(*args, **kwargs)

    monkeypatch.setattr(provider, "put_object", pause_write)
    task = asyncio.create_task(
        _edit(committed_db_session_factory, context, artifact, "<p>Saved version</p>")
    )
    try:
        async with asyncio.timeout(10):
            await write_started.wait()
            async with maintenance_async_db_session() as db:
                job = await db.scalar(
                    select(Job).where(
                        Job.subject_id == artifact.id,
                        Job.kind == CLEANUP_PLATFORM_ARTIFACT_OBJECT_KIND,
                    )
                )
                job_id = job.id
                claim_time = job.run_after + timedelta(seconds=1)
                total = await db.scalar(select(func.count()).select_from(Job))
                claimed = await claim_jobs(
                    db, owner_instance_id="artifact-cleanup-test", now=claim_time, batch_size=total
                )
                assert job_id not in {item.id for item in claimed}
                await db.rollback()
            resume.set()
            saved = await task
    finally:
        resume.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async with maintenance_async_db_session() as db:
        claimed = await claim_jobs(
            db, owner_instance_id="artifact-cleanup-test", now=claim_time, batch_size=total
        )
        job = next(item for item in claimed if item.id == job_id)
        await cleanup_platform_artifact_object(db, job)
        revision = await db.get(ArtifactRevision, saved.current_version_id)
        ref = make_storage_object_ref(StorageBucket.PLATFORM_PRIVATE, revision.object_key)
        await db.rollback()
    assert await provider.stat_object(ref) is not None
