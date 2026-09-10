# apps/api/tests/services/artifacts/test_platform_artifact_concurrency.py

"""Real Postgres concurrency and live authority checks for platform Artifact edits."""

import asyncio
import hashlib
import importlib
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core import database as database_module
from core.database import (
    SESSION_MAINTENANCE_KEY,
    maintenance_async_db_session,
    set_session_tenant_context,
)
from core.exceptions.auth import AuthorizationError
from core.exceptions.general import ConflictError
from core.settings import settings
from models.artifacts import Artifact, ArtifactRevision
from models.audit_event import AuditEvent
from models.jobs import Job
from models.user import User
from models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from services.artifacts.platform.schemas import PlatformArtifactUpdateRequest
from services.artifacts.platform.update_artifact import update_artifact
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.factory import get_storage_provider
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.factories.artifacts import build_artifact, build_artifact_revision
from tests.support.requests import build_test_request
from tests.support.storage import reset_storage_provider_cache

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def committed_artifact_context(committed_db_session_factory, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    reset_storage_provider_cache()
    content = b"<p>Reviewed version</p>"
    async with maintenance_async_db_session() as db:
        actor = build_user(email=f"artifact-concurrency-{uuid4().hex}@example.com")
        workspace = build_workspace(slug=f"artifact-concurrency-{uuid4().hex}")
        membership = build_workspace_membership(workspace_id=workspace.id, user_id=actor.id)
        db.add_all([actor, workspace, membership])
        artifact = build_artifact(workspace=workspace, workspace_id=None, scope="platform")
        db.add(artifact)
        await db.flush()
        revision = build_artifact_revision(
            artifact=artifact,
            scope="platform",
            is_published=True,
            size_bytes=len(content),
            content_hash=hashlib.sha256(content).hexdigest(),
            object_key=f"platform/artifacts/{artifact.id}/{uuid4()}.html",
        )
        db.add(revision)
        await db.flush()
        artifact.current_version_id = artifact.published_version_id = revision.id
        artifact.is_published = True
    try:
        await get_storage_provider().put_object(
            make_storage_object_ref(StorageBucket.PLATFORM_PRIVATE, revision.object_key),
            content,
            content_type=revision.content_type,
        )
        yield {"actor": actor, "workspace": workspace}, membership.id, artifact
    finally:
        try:
            async with maintenance_async_db_session() as db:
                persisted = await db.get(Artifact, artifact.id)
                if persisted is not None:
                    persisted.is_published = False
                    persisted.current_version_id = persisted.published_version_id = None
                    await db.flush()
                    revisions = list(
                        await db.scalars(
                            select(ArtifactRevision)
                            .where(ArtifactRevision.artifact_id == artifact.id)
                            .order_by(ArtifactRevision.revision_number.desc())
                        )
                    )
                    for revision in revisions:
                        await db.delete(revision)
                        await db.flush()
                    await db.delete(persisted)
                await db.execute(
                    delete(Job).where(Job.subject_type == "artifact", Job.subject_id == artifact.id)
                )
                await db.execute(
                    delete(AuditEvent).where(
                        AuditEvent.resource_type == "artifact",
                        AuditEvent.resource_id == str(artifact.id),
                    )
                )
                await db.execute(
                    delete(WorkspaceMembership).where(WorkspaceMembership.id == membership.id)
                )
                await db.execute(delete(Workspace).where(Workspace.id == workspace.id))
                await db.execute(delete(User).where(User.id == actor.id))
        finally:
            reset_storage_provider_cache()


async def _edit(factory, context, artifact, content):
    async with factory() as db:
        await set_session_tenant_context(
            db, workspace_id=context["workspace"].id, user_id=context["actor"].id
        )
        return await update_artifact(
            db,
            **context,
            artifact_id=artifact.id,
            request=build_test_request(),
            payload=PlatformArtifactUpdateRequest(
                expected_current_version_id=artifact.current_version_id, content=content
            ),
        )


@pytest.fixture
async def bounded_maintenance_pool(
    committed_db_session_factory, committed_artifact_context, monkeypatch, save_count
):
    engine = create_async_engine(
        committed_db_session_factory.kw["bind"].url,
        pool_size=min(save_count, 3),
        max_overflow=max(save_count - 3, 0),
        pool_timeout=1,
    )
    factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        info={SESSION_MAINTENANCE_KEY: True},
    )
    try:
        with monkeypatch.context() as patch:
            patch.setattr(database_module, "_maintenance_async_engine", engine)
            patch.setattr(database_module, "_maintenance_async_session_factory", factory)
            yield engine.pool
    finally:
        await engine.dispose()


@pytest.mark.parametrize("save_count", [1, 6])
async def test_concurrent_platform_edits_commit_exactly_one_reviewed_version(
    committed_db_session_factory,
    committed_artifact_context,
    bounded_maintenance_pool,
    monkeypatch,
    save_count,
):
    context, _membership_id, artifact = committed_artifact_context
    module = importlib.import_module("services.artifacts.platform.update_artifact")
    original = module.platform_artifact
    barrier = asyncio.Barrier(save_count)

    async def meet_before_parent_lock(*args, **kwargs):
        await barrier.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(module, "platform_artifact", meet_before_parent_lock)
    async with asyncio.timeout(10):
        results = await asyncio.gather(
            *(
                _edit(committed_db_session_factory, context, artifact, f"<p>Edit {index}</p>")
                for index in range(save_count)
            ),
            return_exceptions=True,
        )
    conflicts = [result for result in results if isinstance(result, ConflictError)]
    successes = [result for result in results if not isinstance(result, BaseException)]
    assert len(successes) == 1, results
    assert len(conflicts) == save_count - 1, results
    assert bounded_maintenance_pool.checkedout() == 0
    winner = successes[0]
    async with maintenance_async_db_session() as db:
        persisted = await db.get(Artifact, artifact.id)
        assert (
            persisted.current_version_id
            == persisted.published_version_id
            == winner.current_version_id
        )
        revisions = list(
            await db.scalars(
                select(ArtifactRevision).where(ArtifactRevision.artifact_id == artifact.id)
            )
        )
        assert len(revisions) == 2
        assert all(revision.is_published for revision in revisions)
        events = list(
            await db.scalars(select(AuditEvent).where(AuditEvent.resource_id == str(artifact.id)))
        )
        assert len(events) == 1
        assert events[0].details["operation"] == "publish_revision"


@pytest.mark.parametrize("change", ["removed", "demoted"])
async def test_membership_revocation_after_preflight_blocks_platform_edit(
    committed_db_session_factory, committed_artifact_context, monkeypatch, change
):
    context, membership_id, artifact = committed_artifact_context
    module = importlib.import_module("services.artifacts.platform.utils")
    original = module.live_authority
    preflight_complete = asyncio.Event()
    resume = asyncio.Event()

    async def pause_before_locked_authority(db, **kwargs):
        if kwargs["lock"]:
            preflight_complete.set()
            await resume.wait()
        return await original(db, **kwargs)

    monkeypatch.setattr(module, "live_authority", pause_before_locked_authority)
    task = asyncio.create_task(
        _edit(committed_db_session_factory, context, artifact, "<p>Denied edit</p>")
    )
    try:
        async with asyncio.timeout(10):
            await preflight_complete.wait()
            async with maintenance_async_db_session() as db:
                membership = await db.get(WorkspaceMembership, membership_id)
                if change == "removed":
                    membership.deleted = True
                else:
                    membership.role = WorkspaceRole.READ_ONLY
            resume.set()
            with pytest.raises(AuthorizationError):
                await task
    finally:
        resume.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    async with maintenance_async_db_session() as db:
        persisted = await db.get(Artifact, artifact.id)
        assert persisted.current_version_id == artifact.current_version_id
        assert persisted.published_version_id == artifact.current_version_id
        revisions = list(
            await db.scalars(
                select(ArtifactRevision).where(ArtifactRevision.artifact_id == artifact.id)
            )
        )
        assert len(revisions) == 1
        assert (
            await db.scalar(select(AuditEvent).where(AuditEvent.resource_id == str(artifact.id)))
            is None
        )
