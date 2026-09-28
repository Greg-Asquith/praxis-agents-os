"""Committed cleanup ownership and worker races for platform Artifact saves."""

from uuid import UUID

import pytest
from sqlalchemy import select

from core.database import maintenance_async_db_session
from models.artifacts import Artifact, ArtifactRevision
from models.audit_event import AuditEvent
from models.jobs import Job
from services.artifacts.domain import CLEANUP_PLATFORM_ARTIFACT_OBJECT_KIND
from services.jobs.domain import JOB_STATUS_PENDING
from services.jobs.handlers.cleanup_platform_artifact_object import (
    cleanup_platform_artifact_object,
)
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.factory import get_storage_provider
from tests.support.platform_artifacts import (
    committed_artifact_context as committed_artifact_context,
    edit_platform_artifact,
)


async def test_failed_save_retains_committed_cleanup_for_written_bytes(
    committed_db_session_factory, committed_artifact_context, monkeypatch
):
    context, _membership_id, artifact = committed_artifact_context
    provider = get_storage_provider()
    original_put = provider.put_object

    async def write_then_lose_response(*args, **kwargs):
        await original_put(*args, **kwargs)
        raise OSError("Storage response lost")

    monkeypatch.setattr(provider, "put_object", write_then_lose_response)

    with pytest.raises(OSError):
        await edit_platform_artifact(
            committed_db_session_factory, context, artifact, "<p>Failed save</p>"
        )

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
