# apps/api/tests/services/artifacts/test_platform_artifact_reads.py

"""Platform Artifact reads keep publication history and tenant ownership separate."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from core.database import maintenance_async_db_session, set_session_tenant_context
from core.exceptions.general import NotFoundError
from core.settings import settings
from models.artifacts import Artifact
from services.agents.runtime.entity_references.internal import _resolve_artifacts, _search_artifacts
from services.artifacts import get_artifact, get_version_content, list_artifacts
from services.artifacts.restore_artifact_version import restore_artifact_version
from services.artifacts.update_artifact import update_artifact
from services.artifacts.utils import get_artifact_revision
from tests.factories import build_artifact, build_artifact_revision, build_user, build_workspace
from tests.support.platform_artifacts import add_platform_artifact_revision, seed_published_artifact
from tests.support.storage import reset_storage_provider_cache


@pytest.fixture
async def platform_reads(db_session_factory, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    reset_storage_provider_cache()
    async with maintenance_async_db_session() as db:
        actor = build_user()
        workspaces = [build_workspace(slug=f"artifact-read-{uuid4().hex}") for _ in range(2)]
        db.add_all([actor, *workspaces])
        await db.flush()
        published, historical = await seed_published_artifact(db, workspace=workspaces[0])
        draft = await add_platform_artifact_revision(
            db, published, content="Private draft", revision_number=2, published=False
        )
        current = await add_platform_artifact_revision(
            db, published, content="Reviewed report", revision_number=3, restored_from=draft
        )
        hidden_current = await add_platform_artifact_revision(
            db, published, content="Unpublished current", revision_number=4, published=False
        )
        hidden = []
        for state in ("draft", "withdrawn", "deleted"):
            row, _revision = await seed_published_artifact(
                db, workspace=workspaces[0], title=f"Platform {state}"
            )
            if state != "deleted":
                row.is_published = False
            if state == "draft":
                row.published_version_id = None
            if state == "deleted":
                row.deleted = True
            hidden.append(row)
        local = []
        for workspace in workspaces:
            row = build_artifact(workspace=workspace, title="Local report")
            db.add(row)
            await db.flush()
            revision = build_artifact_revision(artifact=row)
            db.add(revision)
            await db.flush()
            row.current_version_id = revision.id
            local.append(row)
        await db.flush()
    try:
        yield SimpleNamespace(
            actor=actor,
            workspaces=workspaces,
            published=published,
            historical=historical,
            current=current,
            draft=draft,
            hidden_current=hidden_current,
            hidden=hidden,
            local=local,
        )
    finally:
        reset_storage_provider_cache()


@pytest.mark.parametrize("workspace_index", [0, 1])
async def test_platform_artifact_reads_use_published_pointer_and_history(
    db_session, platform_reads, workspace_index
):
    rows = platform_reads
    workspace = rows.workspaces[workspace_index]
    await set_session_tenant_context(db_session, workspace_id=workspace.id, user_id=rows.actor.id)
    detail = await get_artifact(
        db_session, workspace_id=workspace.id, artifact_id=rows.published.id
    )
    assert detail.scope == "platform"
    assert detail.current_version_id == rows.current.id
    assert detail.workspace_id is detail.agent_id is detail.run_id is detail.conversation_id is None
    assert [version.id for version in detail.versions] == [rows.current.id, rows.historical.id]
    assert all(version.restored_from_revision_id is None for version in detail.versions)
    for revision, content in (
        (rows.current, "Reviewed report"),
        (rows.historical, "Published report"),
    ):
        result = await get_version_content(db_session, artifact=detail, version_id=revision.id)
        assert result.content == content
    for revision in (rows.draft, rows.hidden_current):
        with pytest.raises(NotFoundError):
            await get_version_content(db_session, artifact=detail, version_id=revision.id)
    with pytest.raises(NotFoundError):
        await get_artifact_revision(
            db_session, artifact=detail, version_id=rows.local[workspace_index].current_version_id
        )
    for hidden in [*rows.hidden, rows.local[1 - workspace_index]]:
        with pytest.raises(NotFoundError):
            await get_artifact(db_session, workspace_id=workspace.id, artifact_id=hidden.id)


async def test_platform_artifact_lists_and_pickers_filter_before_limits(db_session, platform_reads):
    rows = platform_reads
    workspace = rows.workspaces[0]
    await set_session_tenant_context(db_session, workspace_id=workspace.id, user_id=rows.actor.id)
    listed = await list_artifacts(db_session, workspace_id=workspace.id, limit=1, offset=0)
    assert listed.total == 2
    platform = await list_artifacts(
        db_session, workspace_id=workspace.id, limit=1, offset=0, scope="platform"
    )
    [summary] = platform.items
    assert platform.total == 1
    assert summary.id == rows.published.id
    assert summary.current_version_id == rows.current.id
    assert summary.version_count == 2
    local = await list_artifacts(
        db_session, workspace_id=workspace.id, limit=1, offset=0, scope="workspace"
    )
    assert [row.id for row in local.items] == [rows.local[0].id]
    context = SimpleNamespace(db=db_session, workspace=workspace)
    first = await _search_artifacts(context, "", {}, 1, None)
    second = await _search_artifacts(context, "", {}, 1, first.next_cursor)
    assert second.next_cursor is None
    choices = [*first.choices, *second.choices]
    assert {choice.value["entity_id"] for choice in choices} == {
        str(rows.published.id),
        str(rows.local[0].id),
    }
    [platform_choice] = [choice for choice in choices if choice.scope_label == "Platform"]
    assert platform_choice.value["entity_id"] == str(rows.published.id)
    resolved = await _resolve_artifacts(
        context,
        [rows.published.id, *(row.id for row in rows.hidden), *(row.id for row in rows.local)],
        {},
    )
    assert {choice.identity for choice in resolved} == {choice.identity for choice in choices}


async def test_platform_artifact_withdrawal_invalidates_previously_loaded_detail(
    db_session, platform_reads
):
    rows = platform_reads
    workspace = rows.workspaces[0]
    await set_session_tenant_context(db_session, workspace_id=workspace.id, user_id=rows.actor.id)
    detail = await get_artifact(
        db_session, workspace_id=workspace.id, artifact_id=rows.published.id
    )
    await db_session.commit()
    async with maintenance_async_db_session() as db:
        artifact = await db.get(Artifact, detail.id)
        artifact.is_published = False
    with pytest.raises(NotFoundError):
        await get_version_content(db_session, artifact=detail, version_id=rows.historical.id)
    context = SimpleNamespace(db=db_session, workspace=workspace)
    assert await _resolve_artifacts(context, [detail.id], {}) == ()


async def test_platform_artifact_history_filters_drafts_before_its_limit(
    db_session, platform_reads
):
    rows = platform_reads
    workspace = rows.workspaces[0]
    async with maintenance_async_db_session() as db:
        artifact = await db.get(Artifact, rows.published.id)
        revisions = [
            build_artifact_revision(
                artifact=artifact,
                scope="platform",
                revision_number=number,
                is_published=number <= 105,
                object_key=f"platform/artifacts/{artifact.id}/{uuid4()}.html",
            )
            for number in range(5, 207)
        ]
        db.add_all(revisions)
        await db.flush()
        published = revisions[100]
        artifact.published_version_id = published.id
        artifact.current_version_id = revisions[-1].id

    await set_session_tenant_context(db_session, workspace_id=workspace.id, user_id=rows.actor.id)
    detail = await get_artifact(db_session, workspace_id=workspace.id, artifact_id=artifact.id)
    assert detail.current_version_id == published.id
    assert [revision.revision_number for revision in detail.versions] == list(range(105, 5, -1))
    listed = await list_artifacts(
        db_session, workspace_id=workspace.id, limit=1, offset=0, scope="platform"
    )
    assert listed.items[0].version_count == 103


@pytest.mark.parametrize("operation", ["update", "restore"])
async def test_platform_artifact_ordinary_mutations_remain_workspace_only(
    db_session, platform_reads, operation
):
    rows = platform_reads
    workspace = rows.workspaces[0]
    await set_session_tenant_context(db_session, workspace_id=workspace.id, user_id=rows.actor.id)
    with pytest.raises(NotFoundError):
        if operation == "update":
            await update_artifact(
                db_session,
                workspace=workspace,
                artifact_id=rows.published.id,
                content="Attempted write",
                actor_user_id=rows.actor.id,
            )
        else:
            await restore_artifact_version(
                db_session,
                workspace=workspace,
                artifact_id=rows.published.id,
                version_id=rows.historical.id,
                actor=rows.actor,
            )
