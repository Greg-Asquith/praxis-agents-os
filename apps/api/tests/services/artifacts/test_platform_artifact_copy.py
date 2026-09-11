# apps/api/tests/services/artifacts/test_platform_artifact_copy.py

"""Workspace copies preserve authority, exact version pins, and durable cleanup."""

import asyncio
import importlib
from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import uuid4, uuid5

import pytest
from sqlalchemy import func, select

from core.database import (
    SESSION_WORKSPACE_ID_KEY,
    maintenance_async_db_session,
    set_session_tenant_context,
)
from core.exceptions.auth import AuthorizationError
from core.exceptions.general import AppValidationError, ConflictError, NotFoundError
from core.settings import settings
from models.artifacts import Artifact, ArtifactRevision, ArtifactShare
from models.audit_event import AuditEvent
from models.jobs import Job
from models.user import User
from models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from services.artifacts.copy_artifact import copy_artifact
from services.artifacts.domain import CLEANUP_ARTIFACT_COPY_KIND
from services.artifacts.utils import artifact_revision_object_key
from services.jobs.claim_jobs import claim_jobs
from services.jobs.handlers.cleanup_artifact_copy import cleanup_artifact_copy
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.factory import get_storage_provider
from services.storage.utils import copy_staging_ref
from tests.factories.artifacts import build_artifact_revision
from tests.support.platform_artifacts import (
    committed_artifact_context as committed_artifact_context,
    platform_copy_context as platform_copy_context,
)
from tests.support.requests import build_test_request


async def _copy(factory, context, artifact, payload, *, before_commit=None):
    async with factory() as db:
        await set_session_tenant_context(
            db, workspace_id=context["workspace"].id, user_id=context["actor"].id
        )
        if before_commit is not None:
            original_commit = db.commit
            commits = 0

            async def intercepted_commit():
                nonlocal commits
                commits += 1
                if commits == 2:
                    await before_commit()
                await original_commit()

            db.commit = intercepted_commit
        return await copy_artifact(
            db,
            **context,
            artifact_id=artifact.id,
            payload=payload,
            request=build_test_request(),
        )


def _destination(context, artifact, payload):
    artifact_id = uuid5(
        context["workspace"].id,
        f"artifact-copy:{context['actor'].id}:{artifact.id}:{payload.version_id}:{payload.request_id}",
    )
    revision_id = uuid5(artifact_id, "revision")
    return (
        artifact_id,
        revision_id,
        make_storage_object_ref(
            StorageBucket.PRIVATE,
            artifact_revision_object_key(
                context["workspace"].id, artifact_id, revision_id, ".html"
            ),
        ),
    )


async def test_platform_copy_pins_old_published_version_without_history_or_provenance(
    committed_db_session_factory,
    platform_copy_context,
):
    context, _membership_id, source, payload = platform_copy_context
    async with maintenance_async_db_session() as db:
        artifact = await db.get(Artifact, source.id)
        later = build_artifact_revision(
            artifact=artifact,
            scope="platform",
            is_published=True,
            revision_number=2,
            revision_kind="edit",
            object_key=f"platform/artifacts/{artifact.id}/{uuid4()}.html",
        )
        db.add(later)
        await db.flush()
        artifact.current_version_id = artifact.published_version_id = later.id

    result = await _copy(committed_db_session_factory, context, source, payload)
    retry = await _copy(committed_db_session_factory, context, source, payload)
    destination_id, version_id, destination = _destination(context, source, payload)
    assert result.id == retry.id == destination_id
    assert result.current_version_id == version_id != payload.version_id
    assert result.scope == "workspace" and result.workspace_id == context["workspace"].id
    assert result.can_edit and not result.is_published and not result.can_manage_platform
    assert result.agent_id is result.conversation_id is result.run_id is None
    assert len(result.versions) == 1
    assert result.versions[0].revision_number == 1
    assert result.versions[0].revision_kind == "create"
    assert result.versions[0].created_by_user_id == context["actor"].id
    assert result.versions[0].restored_from_revision_id is None
    assert await get_storage_provider().get_object(destination) == b"<p>Reviewed version</p>"
    async with maintenance_async_db_session() as db:
        revisions = list(
            await db.scalars(
                select(ArtifactRevision).where(ArtifactRevision.artifact_id == result.id)
            )
        )
        assert len(revisions) == 1 and not revisions[0].is_published
        assert (
            await db.scalar(select(ArtifactShare.id).where(ArtifactShare.artifact_id == result.id))
            is None
        )
        events = list(
            await db.scalars(select(AuditEvent).where(AuditEvent.resource_id == str(result.id)))
        )
        assert len(events) == 1
        assert events[0].workspace_id == context["workspace"].id
        assert events[0].details == {
            "operation": "copy",
            "source_platform_artifact_id": str(source.id),
            "source_version_id": str(payload.version_id),
        }
    async with committed_db_session_factory() as db:
        await set_session_tenant_context(db, workspace_id=uuid4(), user_id=context["actor"].id)
        assert await db.get(Artifact, result.id) is None
        assert await db.get(ArtifactRevision, version_id) is None


@pytest.mark.parametrize("change", ["read_only", "removed", "inactive_user", "inactive_workspace"])
async def test_platform_copy_requires_live_workspace_editor(
    committed_db_session_factory,
    platform_copy_context,
    monkeypatch,
    change,
):
    context, membership_id, artifact, payload = platform_copy_context
    async with maintenance_async_db_session() as db:
        membership = await db.get(WorkspaceMembership, membership_id)
        if change == "read_only":
            membership.role = WorkspaceRole.READ_ONLY
        elif change == "removed":
            membership.deleted = True
        elif change == "inactive_user":
            (await db.get(User, context["actor"].id)).is_active = False
        else:
            (await db.get(Workspace, context["workspace"].id)).deleted = True
    copy = AsyncMock(side_effect=AssertionError("Denied copies cannot write bytes"))
    monkeypatch.setattr(
        importlib.import_module("services.artifacts.copy_artifact"), "copy_object", copy
    )
    with pytest.raises(AuthorizationError):
        await _copy(committed_db_session_factory, context, artifact, payload)
    copy.assert_not_awaited()
    async with maintenance_async_db_session() as db:
        assert (
            await db.scalar(select(Job.id).where(Job.workspace_id == context["workspace"].id))
            is None
        )


@pytest.mark.parametrize("change", ["withdrawn", "deleted", "unpublished_version", "wrong_version"])
async def test_platform_copy_hides_unavailable_parents_and_unmarked_versions(
    committed_db_session_factory,
    platform_copy_context,
    change,
):
    context, _membership_id, artifact, payload = platform_copy_context
    async with maintenance_async_db_session() as db:
        persisted = await db.get(Artifact, artifact.id)
        if change == "withdrawn":
            persisted.is_published = False
        elif change == "deleted":
            persisted.deleted = True
        elif change == "unpublished_version":
            revision = build_artifact_revision(
                artifact=persisted,
                scope="platform",
                is_published=False,
                revision_number=2,
                revision_kind="edit",
                object_key=f"platform/artifacts/{artifact.id}/{uuid4()}.html",
            )
            db.add(revision)
            await db.flush()
            payload.version_id = revision.id
        else:
            payload.version_id = uuid4()
    with pytest.raises(NotFoundError):
        await _copy(committed_db_session_factory, context, artifact, payload)


@pytest.mark.parametrize("invalid", ["extension", "content_type", "size_bytes"])
async def test_platform_copy_rejects_unsupported_or_oversized_revisions(
    committed_db_session_factory,
    platform_copy_context,
    invalid,
):
    context, _membership_id, artifact, payload = platform_copy_context
    async with maintenance_async_db_session() as db:
        persisted = await db.get(Artifact, artifact.id)
        revision = build_artifact_revision(
            artifact=persisted,
            scope="platform",
            is_published=True,
            revision_number=2,
            revision_kind="edit",
            object_key=f"platform/artifacts/{artifact.id}/{uuid4()}.html",
            **{
                invalid: {
                    "extension": ".png",
                    "content_type": "image/png",
                    "size_bytes": settings.ARTIFACT_MAX_CONTENT_BYTES + 1,
                }[invalid]
            },
        )
        db.add(revision)
        await db.flush()
        payload.version_id = revision.id
    with pytest.raises(AppValidationError):
        await _copy(committed_db_session_factory, context, artifact, payload)
    async with maintenance_async_db_session() as db:
        assert (
            await db.scalar(select(Job.id).where(Job.workspace_id == context["workspace"].id))
            is None
        )


@pytest.mark.parametrize("invalid", ["workspace", "kind", "revision", "extension"])
async def test_platform_copy_cleanup_rejects_wrong_context_or_reservation(monkeypatch, invalid):
    workspace_id, artifact_id = uuid4(), uuid4()
    job = Job(
        id=uuid4(),
        kind=CLEANUP_ARTIFACT_COPY_KIND,
        workspace_id=workspace_id,
        subject_type="artifact",
        subject_id=artifact_id,
        payload={"revision_id": str(uuid5(artifact_id, "revision")), "extension": ".html"},
    )
    db = AsyncMock()
    db.info = {SESSION_WORKSPACE_ID_KEY: workspace_id}
    if invalid == "workspace":
        db.info = {SESSION_WORKSPACE_ID_KEY: uuid4()}
    elif invalid == "kind":
        job.kind = "platform.artifacts.cleanup_object"
    elif invalid == "revision":
        job.payload["revision_id"] = str(uuid4())
    else:
        job.payload["extension"] = "/other.html"
    provider = AsyncMock()
    module = importlib.import_module("services.jobs.handlers.cleanup_artifact_copy")
    monkeypatch.setattr(module, "get_storage_provider", lambda: provider)
    with pytest.raises((RuntimeError, ValueError)):
        await cleanup_artifact_copy(db, job)
    provider.delete_object.assert_not_awaited()


@pytest.mark.parametrize("failure", ["audit", "commit", "storage", "cancelled"])
async def test_platform_copy_failure_keeps_cleanup_and_retry_commits_once(
    committed_db_session_factory,
    platform_copy_context,
    monkeypatch,
    failure,
):
    context, _membership_id, artifact, payload = platform_copy_context
    module = importlib.import_module("services.artifacts.copy_artifact")
    provider = get_storage_provider()
    original_copy = module.copy_object

    async def write_then_fail(*args, **kwargs):
        await original_copy(*args, **kwargs)
        raise OSError("Copy response lost")

    async def fail_commit():
        if failure == "cancelled":
            raise asyncio.CancelledError
        raise OSError("Commit unavailable")

    with monkeypatch.context() as patch:
        if failure == "audit":
            patch.setattr(
                module,
                "record_operation_audit_event",
                AsyncMock(side_effect=OSError("Audit unavailable")),
            )
        elif failure == "storage":
            patch.setattr(module, "copy_object", write_then_fail)
        with pytest.raises(asyncio.CancelledError if failure == "cancelled" else OSError):
            await _copy(
                committed_db_session_factory,
                context,
                artifact,
                payload,
                before_commit=fail_commit if failure in {"commit", "cancelled"} else None,
            )
    destination_id, version_id, destination = _destination(context, artifact, payload)
    assert await provider.stat_object(destination) is not None
    async with maintenance_async_db_session() as db:
        assert await db.get(Artifact, destination_id) is None
        assert await db.get(ArtifactRevision, version_id) is None
        jobs = list(await db.scalars(select(Job).where(Job.subject_id == destination_id)))
        assert len(jobs) == 1 and jobs[0].status == "pending" and jobs[0].attempts == 0
        assert (
            await db.scalar(
                select(AuditEvent.id).where(AuditEvent.resource_id == str(destination_id))
            )
            is None
        )

    result = await _copy(committed_db_session_factory, context, artifact, payload)
    assert result.id == destination_id
    async with maintenance_async_db_session() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.resource_id == str(destination_id))
            )
            == 1
        )
    async with committed_db_session_factory() as db:
        await set_session_tenant_context(
            db, workspace_id=context["workspace"].id, user_id=context["actor"].id
        )
        await cleanup_artifact_copy(db, await db.get(Job, jobs[0].id))
    assert await provider.stat_object(destination) is not None


@pytest.mark.parametrize("cleanup_status", ["running", "succeeded", "pending"])
async def test_platform_copy_rejects_claimed_reservations(
    committed_db_session_factory,
    platform_copy_context,
    monkeypatch,
    cleanup_status,
):
    context, _membership_id, artifact, payload = platform_copy_context
    module = importlib.import_module("services.artifacts.copy_artifact")
    original = module.reserve_copy

    async def claimed_before_copy(*args, **kwargs):
        reservation = await original(*args, **kwargs)
        async with maintenance_async_db_session() as db:
            job = await db.get(Job, reservation.id)
            job.status = cleanup_status
            job.attempts = 1
        return reservation

    monkeypatch.setattr(module, "reserve_copy", claimed_before_copy)
    copy = AsyncMock(side_effect=AssertionError("Expired requests cannot write bytes"))
    monkeypatch.setattr(module, "copy_object", copy)
    with pytest.raises(ConflictError, match="expired"):
        await _copy(committed_db_session_factory, context, artifact, payload)
    copy.assert_not_awaited()


@pytest.mark.parametrize("change", ["removed", "read_only", "withdrawn"])
async def test_platform_copy_rechecks_authority_and_source_after_reservation(
    committed_db_session_factory,
    platform_copy_context,
    monkeypatch,
    change,
):
    context, membership_id, artifact, payload = platform_copy_context
    module = importlib.import_module("services.artifacts.copy_artifact")
    original = module.reserve_copy

    async def revoke_after_reservation(*args, **kwargs):
        reservation = await original(*args, **kwargs)
        async with maintenance_async_db_session() as db:
            if change == "withdrawn":
                (await db.get(Artifact, artifact.id)).is_published = False
            else:
                membership = await db.get(WorkspaceMembership, membership_id)
                if change == "removed":
                    membership.deleted = True
                else:
                    membership.role = WorkspaceRole.READ_ONLY
        return reservation

    monkeypatch.setattr(module, "reserve_copy", revoke_after_reservation)
    with pytest.raises(NotFoundError if change == "withdrawn" else AuthorizationError):
        await _copy(committed_db_session_factory, context, artifact, payload)
    _, _, destination = _destination(context, artifact, payload)
    assert await get_storage_provider().stat_object(destination) is None


async def test_platform_copy_cleanup_removes_orphans_and_retains_failed_work(
    committed_db_session_factory,
    platform_copy_context,
    monkeypatch,
):
    context, _membership_id, artifact, payload = platform_copy_context
    module = importlib.import_module("services.artifacts.copy_artifact")
    provider = get_storage_provider()
    with monkeypatch.context() as patch:
        patch.setattr(
            module,
            "record_operation_audit_event",
            AsyncMock(side_effect=OSError("Audit unavailable")),
        )
        with pytest.raises(OSError):
            await _copy(committed_db_session_factory, context, artifact, payload)
    destination_id, _, destination = _destination(context, artifact, payload)
    stage = copy_staging_ref(destination)
    await provider.put_object(stage, b"orphan stage", content_type="text/html")
    async with committed_db_session_factory() as db:
        await set_session_tenant_context(
            db, workspace_id=context["workspace"].id, user_id=context["actor"].id
        )
        job = await db.scalar(select(Job).where(Job.subject_id == destination_id))
        with monkeypatch.context() as patch:
            patch.setattr(
                provider, "delete_object", AsyncMock(side_effect=OSError("Storage unavailable"))
            )
            with pytest.raises(OSError):
                await cleanup_artifact_copy(db, job)
        assert await db.get(Job, job.id) is not None
        await cleanup_artifact_copy(db, job)
    assert await provider.stat_object(destination) is None
    assert await provider.stat_object(stage) is None


async def test_platform_copy_serialises_duplicate_requests(
    committed_db_session_factory,
    platform_copy_context,
):
    context, _membership_id, artifact, payload = platform_copy_context
    async with asyncio.timeout(10):
        results = await asyncio.gather(
            *(_copy(committed_db_session_factory, context, artifact, payload) for _ in range(3))
        )
    assert len({result.id for result in results}) == 1
    async with maintenance_async_db_session() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.resource_id == str(results[0].id))
            )
            == 1
        )


async def test_platform_copy_locks_source_until_destination_commit_and_skips_cleanup_claim(
    committed_db_session_factory,
    platform_copy_context,
):
    context, _membership_id, artifact, payload = platform_copy_context
    committing, resume, withdrawing = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def pause_commit():
        committing.set()
        await resume.wait()

    async def withdraw():
        async with maintenance_async_db_session() as db:
            withdrawing.set()
            parent = await db.scalar(
                select(Artifact).where(Artifact.id == artifact.id).with_for_update()
            )
            parent.is_published = False

    copy_task = asyncio.create_task(
        _copy(committed_db_session_factory, context, artifact, payload, before_commit=pause_commit)
    )
    withdrawal_task = None
    try:
        async with asyncio.timeout(10):
            await committing.wait()
            withdrawal_task = asyncio.create_task(withdraw())
            await withdrawing.wait()
            async with maintenance_async_db_session() as db:
                destination_id, _, _ = _destination(context, artifact, payload)
                job = await db.scalar(select(Job).where(Job.subject_id == destination_id))
                total = await db.scalar(select(func.count()).select_from(Job))
                claimed = await claim_jobs(
                    db,
                    owner_instance_id="artifact-copy-test",
                    now=job.run_after + timedelta(seconds=1),
                    batch_size=total,
                )
                assert job.id not in {item.id for item in claimed}
                await db.rollback()
            assert not withdrawal_task.done()
            resume.set()
            result = await copy_task
            await withdrawal_task
    finally:
        resume.set()
        tasks = [copy_task, *([withdrawal_task] if withdrawal_task else [])]
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    async with maintenance_async_db_session() as db:
        assert (await db.get(Artifact, artifact.id)).is_published is False
        assert (await db.get(Artifact, result.id)).current_version_id == result.current_version_id
