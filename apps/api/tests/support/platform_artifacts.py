# apps/api/tests/support/platform_artifacts.py

"""Seeds private platform Artifact bytes and immutable versions for boundary tests."""

from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from core.database import maintenance_async_db_session, set_session_tenant_context
from core.settings import settings
from models.artifacts import Artifact, ArtifactRevision
from models.audit_event import AuditEvent
from models.jobs import Job
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.artifacts.domain import ARTIFACT_EXTENSIONS, ARTIFACT_STORAGE_CONTENT_TYPES
from services.artifacts.platform.schemas import PlatformArtifactUpdateRequest
from services.artifacts.platform.update_artifact import update_artifact
from services.artifacts.schemas import ArtifactCopyRequest
from services.artifacts.utils import artifact_content_hash, artifact_revision_ref
from services.storage.factory import get_storage_provider
from tests.factories import (
    build_artifact,
    build_artifact_revision,
    build_user,
    build_workspace,
    build_workspace_membership,
)
from tests.support.requests import build_test_request
from tests.support.storage import reset_storage_provider_cache


async def add_platform_artifact_revision(
    db,
    artifact: Artifact,
    *,
    content: str,
    revision_number: int,
    published: bool = True,
    restored_from: ArtifactRevision | None = None,
) -> ArtifactRevision:
    revision_id = uuid4()
    extension = ARTIFACT_EXTENSIONS[artifact.artifact_type]
    data = content.encode()
    revision = build_artifact_revision(
        artifact=artifact,
        revision_id=revision_id,
        scope="platform",
        is_published=published,
        revision_number=revision_number,
        revision_kind="restore" if restored_from else "create" if revision_number == 1 else "edit",
        restored_from_revision_id=restored_from.id if restored_from else None,
        object_key=f"platform/artifacts/{artifact.id}/{revision_id}{extension}",
        content_type=ARTIFACT_STORAGE_CONTENT_TYPES[artifact.artifact_type],
        size_bytes=len(data),
        content_hash=artifact_content_hash(data),
    )
    db.add(revision)
    await db.flush()
    artifact.current_version_id = revision.id
    if published:
        artifact.published_version_id = revision.id
        artifact.is_published = True
    await db.flush()
    await get_storage_provider().put_object(
        artifact_revision_ref(revision.object_key, scope="platform"),
        data,
        content_type=revision.content_type,
        overwrite=False,
    )
    return revision


async def seed_published_artifact(
    db,
    *,
    workspace: Workspace,
    content: str = "Published report",
    title: str = "Platform report",
    artifact_type: str = "markdown",
) -> tuple[Artifact, ArtifactRevision]:
    artifact = build_artifact(
        workspace=workspace,
        scope="platform",
        workspace_id=None,
        artifact_type=artifact_type,
        title=title,
    )
    db.add(artifact)
    await db.flush()
    revision = await add_platform_artifact_revision(
        db, artifact, content=content, revision_number=1
    )
    return artifact, revision


@pytest.fixture
async def committed_artifact_context(committed_db_session_factory, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    reset_storage_provider_cache()
    async with maintenance_async_db_session() as db:
        actor = build_user(email=f"artifact-concurrency-{uuid4().hex}@example.com")
        workspace = build_workspace(slug=f"artifact-concurrency-{uuid4().hex}")
        membership = build_workspace_membership(workspace_id=workspace.id, user_id=actor.id)
        db.add_all([actor, workspace, membership])
        await db.flush()
        artifact, _revision = await seed_published_artifact(
            db, workspace=workspace, artifact_type="html", content="<p>Reviewed version</p>"
        )
    try:
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


@pytest.fixture
async def platform_copy_context(committed_artifact_context):
    context, membership_id, artifact = committed_artifact_context
    payload = ArtifactCopyRequest(version_id=artifact.current_version_id, request_id=uuid4())
    try:
        yield context, membership_id, artifact, payload
    finally:
        async with maintenance_async_db_session() as db:
            workspace_id = context["workspace"].id
            await db.execute(delete(Job).where(Job.workspace_id == workspace_id))
            await db.execute(delete(AuditEvent).where(AuditEvent.workspace_id == workspace_id))
            artifacts = list(
                await db.scalars(select(Artifact).where(Artifact.workspace_id == workspace_id))
            )
            for local in artifacts:
                local.current_version_id = None
                await db.flush()
                await db.execute(
                    delete(ArtifactRevision).where(ArtifactRevision.artifact_id == local.id)
                )
                await db.delete(local)


async def edit_platform_artifact(factory, context, artifact, content):
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
