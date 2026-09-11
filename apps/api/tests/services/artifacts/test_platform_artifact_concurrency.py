# apps/api/tests/services/artifacts/test_platform_artifact_concurrency.py

"""Real Postgres concurrency and live authority checks for platform Artifact edits."""

import asyncio
import importlib

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core import database as database_module
from core.database import (
    SESSION_MAINTENANCE_KEY,
    maintenance_async_db_session,
)
from core.exceptions.auth import AuthorizationError
from core.exceptions.general import ConflictError
from models.artifacts import Artifact, ArtifactRevision
from models.audit_event import AuditEvent
from models.workspace import WorkspaceMembership, WorkspaceRole
from tests.support.platform_artifacts import (
    committed_artifact_context as committed_artifact_context,
    edit_platform_artifact,
)

pytestmark = pytest.mark.asyncio


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
                edit_platform_artifact(
                    committed_db_session_factory, context, artifact, f"<p>Edit {index}</p>"
                )
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
        edit_platform_artifact(
            committed_db_session_factory, context, artifact, "<p>Denied edit</p>"
        )
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
