# apps/api/tests/services/artifacts/test_create_update_artifact.py

"""Artifact creation and immutable revision tests."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError, NotFoundError
from core.settings import settings
from models.artifacts import ArtifactRevision
from models.files import File
from services.artifacts import create_artifact, update_artifact
from services.artifacts.utils import artifact_revision_ref
from services.storage.factory import get_storage_provider
from tests.factories import build_user, build_workspace
from tests.support.storage import reset_storage_provider_cache

pytestmark = pytest.mark.asyncio


@pytest.fixture
def local_storage_settings(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    reset_storage_provider_cache()
    try:
        yield
    finally:
        reset_storage_provider_cache()


async def test_create_and_update_use_one_immutable_artifact_chain(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    actor = build_user(email=f"artifact-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"artifact-{uuid4().hex[:8]}")
    db_session.add_all([actor, workspace])
    await db_session.flush()
    file_count_before = await db_session.scalar(select(func.count()).select_from(File))

    artifact, first = await create_artifact(
        db_session,
        workspace=workspace,
        title="Quarterly report",
        artifact_type="mermaid",
        content="graph TD; A-->B",
        actor_user_id=actor.id,
    )
    assert first.extension == ".mmd"
    assert "/artifacts/" in first.object_key
    assert await db_session.scalar(select(func.count()).select_from(File)) == file_count_before
    first_bytes = await get_storage_provider().get_object(artifact_revision_ref(first.object_key))

    updated, second = await update_artifact(
        db_session,
        workspace=workspace,
        artifact_id=artifact.id,
        content="graph TD; A-->C",
        title="Updated report",
        actor_user_id=actor.id,
    )
    revisions = list(
        (
            await db_session.scalars(
                select(ArtifactRevision)
                .where(ArtifactRevision.artifact_id == artifact.id)
                .order_by(ArtifactRevision.revision_number)
            )
        ).all()
    )
    assert [revision.id for revision in revisions] == [first.id, second.id]
    assert updated.current_version_id == second.id
    assert updated.title == "Updated report"
    assert (
        await get_storage_provider().get_object(artifact_revision_ref(first.object_key))
        == first_bytes
    )


async def test_artifact_validation_and_workspace_isolation(
    db_session: AsyncSession,
    local_storage_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor = build_user(email=f"artifact-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"artifact-{uuid4().hex[:8]}")
    other_workspace = build_workspace(slug=f"artifact-other-{uuid4().hex[:8]}")
    db_session.add_all([actor, workspace, other_workspace])
    await db_session.flush()
    artifact, _revision = await create_artifact(
        db_session,
        workspace=workspace,
        title="Report",
        artifact_type="html",
        content="<p>safe</p>",
        actor_user_id=actor.id,
    )
    with pytest.raises(NotFoundError):
        await update_artifact(
            db_session,
            workspace=other_workspace,
            artifact_id=artifact.id,
            content="<p>cross tenant</p>",
            actor_user_id=actor.id,
        )
    with pytest.raises(AppValidationError):
        await create_artifact(
            db_session,
            workspace=workspace,
            title="Image",
            artifact_type="image-ref",
            content="not allowed",
            actor_user_id=actor.id,
        )
    monkeypatch.setattr(settings, "ARTIFACT_MAX_CONTENT_BYTES", 3)
    with pytest.raises(AppValidationError):
        await create_artifact(
            db_session,
            workspace=workspace,
            title="Large",
            artifact_type="markdown",
            content="four",
            actor_user_id=actor.id,
        )
