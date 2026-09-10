# apps/api/tests/services/artifacts/test_platform_artifact_management.py

"""Platform Artifact publication, editor authority, and transaction boundaries."""

import importlib
from unittest.mock import AsyncMock
from uuid import uuid4, uuid5

import pytest
from sqlalchemy import select

from core.database import maintenance_async_db_session, set_session_tenant_context
from core.exceptions.auth import AuthorizationError
from core.exceptions.general import AppValidationError, ConflictError, NotFoundError
from core.settings import settings
from models.artifacts import Artifact, ArtifactRevision, ArtifactShare
from models.audit_event import AuditEvent
from models.workspace import WorkspaceMembership, WorkspaceRole
from services.artifacts import (
    create_artifact as create_workspace_artifact,
    update_artifact as update_workspace_artifact,
)
from services.artifacts.create_share import create_artifact_share
from services.artifacts.platform.create_artifact import create_artifact
from services.artifacts.platform.delete_artifact import delete_artifact
from services.artifacts.platform.list_artifacts import list_artifacts
from services.artifacts.platform.publish_artifact import publish_artifact
from services.artifacts.platform.restore_artifact_version import restore_artifact_version
from services.artifacts.platform.schemas import (
    PlatformArtifactCreateRequest,
    PlatformArtifactRestoreRequest,
    PlatformArtifactUpdateRequest,
    PlatformArtifactVersionRequest,
)
from services.artifacts.platform.update_artifact import update_artifact
from services.artifacts.platform.withdraw_artifact import withdraw_artifact
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.factory import get_storage_provider
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.support.requests import build_test_request
from tests.support.storage import reset_storage_provider_cache

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def platform_context(db_session_factory, monkeypatch, tmp_path):
    email = f"artifact-manager-{uuid4().hex}@example.com"
    monkeypatch.setattr(settings, "SUPER_ADMIN_EMAILS", email)
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "ARTIFACT_SHARING_ENABLED", True)
    reset_storage_provider_cache()
    async with maintenance_async_db_session() as db:
        actor, workspace = build_user(email=email), build_workspace(slug=f"manager-{uuid4().hex}")
        membership = build_workspace_membership(
            workspace_id=workspace.id, user_id=actor.id, role=WorkspaceRole.READ_ONLY
        )
        db.add_all([actor, workspace, membership])
    try:
        yield {"actor": actor, "workspace": workspace}
    finally:
        reset_storage_provider_cache()


async def _tenant(db, context):
    await set_session_tenant_context(
        db, workspace_id=context["workspace"].id, user_id=context["actor"].id
    )


async def _source(db, context, content="<p>Selected report</p>"):
    await _tenant(db, context)
    result = await create_workspace_artifact(
        db,
        workspace=context["workspace"],
        title="Report",
        artifact_type="html",
        content=content,
        actor_user_id=context["actor"].id,
    )
    await db.commit()
    return result


async def _create(db, context, source=None, payload=None):
    source, revision = source or await _source(db, context)
    await _tenant(db, context)
    return await create_artifact(
        db,
        **context,
        request=build_test_request(),
        artifact_id=source.id,
        payload=payload
        or PlatformArtifactCreateRequest(
            version_id=revision.id,
            expected_current_version_id=source.current_version_id,
            request_id=uuid4(),
        ),
    )


async def _editor(context, role=WorkspaceRole.MEMBER, *, same_workspace=False):
    async with maintenance_async_db_session() as db:
        actor = build_user(email=f"editor-{uuid4().hex}@example.com")
        workspace = (
            context["workspace"]
            if same_workspace
            else build_workspace(slug=f"editor-{uuid4().hex}")
        )
        membership = build_workspace_membership(
            workspace_id=workspace.id, user_id=actor.id, role=role
        )
        db.add_all([actor, membership])
        if not same_workspace:
            db.add(workspace)
    return {"actor": actor, "workspace": workspace}, membership.id


async def _edit(db, context, artifact, content="<p>Edited report</p>"):
    await _tenant(db, context)
    return await update_artifact(
        db,
        **context,
        request=build_test_request(),
        artifact_id=artifact.id,
        payload=PlatformArtifactUpdateRequest(
            expected_current_version_id=artifact.current_version_id,
            content=content,
        ),
    )


async def test_platform_artifact_copies_selected_bytes_without_provenance_or_shares(
    db_session,
    platform_context,
):
    source = await _source(db_session, platform_context)
    await _tenant(db_session, platform_context)
    await update_workspace_artifact(
        db_session,
        workspace=platform_context["workspace"],
        artifact_id=source[0].id,
        content="<p>Unselected version</p>",
        actor_user_id=platform_context["actor"].id,
    )
    await db_session.commit()
    result = await _create(db_session, platform_context, source)
    assert result.is_published
    assert result.current_version_id == result.published_version_id
    assert result.id != source[0].id
    assert result.workspace_id is result.agent_id is result.conversation_id is result.run_id is None
    assert len(result.versions) == 1
    async with maintenance_async_db_session() as db:
        revision = await db.get(ArtifactRevision, result.current_version_id)
        assert revision.scope == "platform" and revision.workspace_id is None
        assert revision.is_published
        assert revision.restored_from_revision_id is None
        assert str(source[0].id) not in revision.object_key
        assert (
            await get_storage_provider().get_object(
                make_storage_object_ref(StorageBucket.PLATFORM_PRIVATE, revision.object_key)
            )
            == b"<p>Selected report</p>"
        )
        assert (
            await db.scalar(select(ArtifactShare).where(ArtifactShare.artifact_id == result.id))
            is None
        )
        events = list(
            await db.scalars(select(AuditEvent).where(AuditEvent.resource_id == str(result.id)))
        )
        assert events and all(event.workspace_id is None for event in events)
        assert any(
            event.details.get("source")
            == {
                "workspace_id": str(platform_context["workspace"].id),
                "resource_id": str(source[0].id),
                "revision_id": str(source[1].id),
            }
            for event in events
        )
    assert str(source[0].id) not in result.model_dump_json()


async def test_platform_artifact_list_returns_scoped_paginated_summaries(
    db_session, platform_context
):
    published = await _create(db_session, platform_context)
    published = await _edit(db_session, platform_context, published)
    withdrawn = await _create(db_session, platform_context)
    await withdraw_artifact(
        db_session, **platform_context, request=build_test_request(), artifact_id=withdrawn.id
    )
    deleted = await _create(db_session, platform_context)
    await delete_artifact(
        db_session, **platform_context, request=build_test_request(), artifact_id=deleted.id
    )

    results = await list_artifacts(db_session, **platform_context)
    assert {artifact.id: artifact.version_count for artifact in results} == {
        published.id: 2,
        withdrawn.id: 1,
    }
    assert {artifact.id: artifact.published_version_id for artifact in results} == {
        published.id: published.current_version_id,
        withdrawn.id: withdrawn.current_version_id,
    }
    assert {artifact.id: artifact.is_published for artifact in results} == {
        published.id: True,
        withdrawn.id: False,
    }
    assert all("versions" not in artifact.model_dump() for artifact in results)
    page = await list_artifacts(db_session, **platform_context, offset=1, limit=1)
    assert page == results[1:2]


async def test_platform_artifact_rejects_stale_source_review(db_session, platform_context):
    source, first = await _source(db_session, platform_context)
    reviewed = PlatformArtifactCreateRequest(
        version_id=first.id,
        expected_current_version_id=first.id,
        request_id=uuid4(),
    )
    await _tenant(db_session, platform_context)
    await update_workspace_artifact(
        db_session,
        workspace=platform_context["workspace"],
        artifact_id=source.id,
        content="<p>Changed</p>",
        actor_user_id=platform_context["actor"].id,
    )
    await db_session.commit()
    with pytest.raises(ConflictError):
        await _create(db_session, platform_context, (source, first), reviewed)


@pytest.mark.parametrize("role", [WorkspaceRole.OWNER, WorkspaceRole.ADMIN, WorkspaceRole.MEMBER])
@pytest.mark.parametrize("same_workspace", [True, False])
async def test_platform_artifact_editors_publish_immediately(
    db_session,
    platform_context,
    role,
    same_workspace,
):
    artifact = await _create(db_session, platform_context)
    editor, _ = await _editor(platform_context, role, same_workspace=same_workspace)
    edited = await _edit(db_session, editor, artifact)
    assert edited.current_version_id != artifact.current_version_id
    assert edited.current_version_id == edited.published_version_id
    async with maintenance_async_db_session() as db:
        revisions = list(
            await db.scalars(
                select(ArtifactRevision).where(ArtifactRevision.artifact_id == artifact.id)
            )
        )
        assert len(revisions) == 2 and all(row.is_published for row in revisions)
        event = await db.scalar(
            select(AuditEvent).where(
                AuditEvent.resource_id == str(artifact.id),
                AuditEvent.actor_user_id == editor["actor"].id,
            )
        )
        assert event.workspace_id is None
        assert event.details["operation"] == "publish_revision"
    with pytest.raises(ConflictError):
        await _edit(db_session, editor, artifact)
    restored = await restore_artifact_version(
        db_session,
        **editor,
        request=build_test_request(),
        artifact_id=artifact.id,
        payload=PlatformArtifactRestoreRequest(
            expected_current_version_id=edited.current_version_id,
            version_id=artifact.current_version_id,
        ),
    )
    assert restored.current_version_id not in {
        artifact.current_version_id,
        edited.current_version_id,
    }
    assert restored.current_version_id == restored.published_version_id


@pytest.mark.parametrize("failure", ["read_only", "removed", "withdrawn"])
async def test_platform_artifact_rechecks_editor_authority(db_session, platform_context, failure):
    artifact = await _create(db_session, platform_context)
    editor, membership_id = await _editor(
        platform_context,
        WorkspaceRole.READ_ONLY if failure == "read_only" else WorkspaceRole.MEMBER,
    )
    if failure == "removed":
        async with maintenance_async_db_session() as db:
            (await db.get(WorkspaceMembership, membership_id)).deleted = True
    if failure == "withdrawn":
        await withdraw_artifact(
            db_session, **platform_context, request=build_test_request(), artifact_id=artifact.id
        )
    with pytest.raises(AuthorizationError):
        await _edit(db_session, editor, artifact)
    async with maintenance_async_db_session() as db:
        assert (
            await db.get(Artifact, artifact.id)
        ).current_version_id == artifact.current_version_id


@pytest.mark.parametrize("operation", ["update", "restore", "withdraw", "delete"])
async def test_platform_artifact_audit_failure_rolls_back(
    db_session,
    platform_context,
    monkeypatch,
    operation,
):
    artifact = await _create(db_session, platform_context)
    module = importlib.import_module("services.artifacts.platform.utils")
    monkeypatch.setattr(
        module,
        "record_platform_content_audit_event",
        AsyncMock(side_effect=RuntimeError("audit unavailable")),
    )
    with pytest.raises(RuntimeError, match="audit unavailable"):
        if operation == "update":
            await _edit(db_session, platform_context, artifact)
        elif operation == "restore":
            await restore_artifact_version(
                db_session,
                **platform_context,
                request=build_test_request(),
                artifact_id=artifact.id,
                payload=PlatformArtifactRestoreRequest(
                    expected_current_version_id=artifact.current_version_id,
                    version_id=artifact.current_version_id,
                ),
            )
        else:
            function = withdraw_artifact if operation == "withdraw" else delete_artifact
            await function(
                db_session,
                **platform_context,
                request=build_test_request(),
                artifact_id=artifact.id,
            )
    async with maintenance_async_db_session() as db:
        row = await db.get(Artifact, artifact.id)
        assert row.current_version_id == row.published_version_id == artifact.current_version_id
        assert row.is_published and not row.deleted
        revisions = list(
            await db.scalars(
                select(ArtifactRevision).where(ArtifactRevision.artifact_id == artifact.id)
            )
        )
        assert len(revisions) == 1


async def test_platform_artifact_withdrawn_admin_edit_requires_republication(
    db_session, platform_context
):
    artifact = await _create(db_session, platform_context)
    await withdraw_artifact(
        db_session, **platform_context, request=build_test_request(), artifact_id=artifact.id
    )
    edited = await _edit(db_session, platform_context, artifact)
    assert not edited.is_published
    assert edited.published_version_id != edited.current_version_id
    published = await publish_artifact(
        db_session,
        **platform_context,
        request=build_test_request(),
        artifact_id=artifact.id,
        payload=PlatformArtifactVersionRequest(
            expected_current_version_id=edited.current_version_id
        ),
    )
    assert published.is_published and published.published_version_id == edited.current_version_id


async def test_platform_artifact_restore_rejects_other_parent(db_session, platform_context):
    artifact = await _create(db_session, platform_context)
    other = await _create(db_session, platform_context)
    with pytest.raises(NotFoundError):
        await restore_artifact_version(
            db_session,
            **platform_context,
            request=build_test_request(),
            artifact_id=artifact.id,
            payload=PlatformArtifactRestoreRequest(
                expected_current_version_id=artifact.current_version_id,
                version_id=other.current_version_id,
            ),
        )


async def test_platform_artifact_share_rejected_for_super_admin(db_session, platform_context):
    artifact = await _create(db_session, platform_context)
    await _tenant(db_session, platform_context)
    with pytest.raises(AppValidationError):
        await create_artifact_share(
            db_session, **platform_context, request=build_test_request(), artifact_id=artifact.id
        )


@pytest.mark.parametrize("follow_up", ["retry", "delete"])
async def test_platform_artifact_failed_initial_audit_keeps_one_reservation(
    db_session,
    platform_context,
    monkeypatch,
    follow_up,
):
    source = await _source(db_session, platform_context)
    payload = PlatformArtifactCreateRequest(
        version_id=source[1].id,
        expected_current_version_id=source[1].id,
        request_id=uuid4(),
    )
    destination_id = uuid5(
        source[0].id,
        f"platform:{platform_context['workspace'].id}:{platform_context['actor'].id}:{payload.version_id}:{payload.expected_current_version_id}:{payload.request_id}",
    )
    module = importlib.import_module("services.artifacts.platform.utils")
    original = module.record_platform_content_audit_event

    async def fail_publication(*args, **kwargs):
        if kwargs["details"].operation == "publish":
            raise RuntimeError("audit unavailable")
        return await original(*args, **kwargs)

    monkeypatch.setattr(module, "record_platform_content_audit_event", fail_publication)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await _create(db_session, platform_context, source, payload)
    async with maintenance_async_db_session() as db:
        reserved = list(await db.scalars(select(Artifact).where(Artifact.id == destination_id)))
        assert len(reserved) == 1
        reserved_id = reserved[0].id
        assert not reserved[0].is_published and reserved[0].published_version_id is None
        revision = await db.get(ArtifactRevision, reserved[0].current_version_id)
        assert not revision.is_published
        events = list(
            await db.scalars(select(AuditEvent).where(AuditEvent.resource_id == str(reserved_id)))
        )
        assert [event.details["operation"] for event in events] == ["create"]
    monkeypatch.setattr(module, "record_platform_content_audit_event", original)
    if follow_up == "delete":
        with pytest.raises(AppValidationError, match="Delete it to cancel publication"):
            await withdraw_artifact(
                db_session,
                **platform_context,
                request=build_test_request(),
                artifact_id=reserved_id,
            )
        await delete_artifact(
            db_session,
            **platform_context,
            request=build_test_request(),
            artifact_id=reserved_id,
        )
        with pytest.raises(ConflictError, match="publication was deleted"):
            await _create(db_session, platform_context, source, payload)
        return
    result = await _create(db_session, platform_context, source, payload)
    assert result.id == reserved_id and result.is_published
    repeated = await _create(db_session, platform_context, source, payload)
    assert repeated.id == result.id and len(repeated.versions) == 1
    async with maintenance_async_db_session() as db:
        assert (
            len(list(await db.scalars(select(Artifact).where(Artifact.id == destination_id)))) == 1
        )


async def test_platform_artifact_draft_share_rejected_in_maintenance(db_session, platform_context):
    artifact = await _create(db_session, platform_context)
    await withdraw_artifact(
        db_session, **platform_context, request=build_test_request(), artifact_id=artifact.id
    )
    async with maintenance_async_db_session() as db:
        with pytest.raises(AppValidationError, match="anonymous shares"):
            await create_artifact_share(
                db, **platform_context, request=build_test_request(), artifact_id=artifact.id
            )


@pytest.mark.parametrize("committed", [True, False])
async def test_platform_artifact_cleanup_preserves_only_committed_bytes(
    db_session,
    platform_context,
    committed,
):
    from models.jobs import Job
    from services.jobs.handlers.cleanup_platform_artifact_object import (
        cleanup_platform_artifact_object,
    )

    artifact = await _create(db_session, platform_context)
    if committed:
        edited = await _edit(db_session, platform_context, artifact)
        async with maintenance_async_db_session() as db:
            job = await db.scalar(
                select(Job).where(
                    Job.subject_id == artifact.id, Job.kind == "platform.artifacts.cleanup_object"
                )
            )
            revision = await db.get(ArtifactRevision, edited.current_version_id)
            ref = make_storage_object_ref(StorageBucket.PLATFORM_PRIVATE, revision.object_key)
            assert job.payload["revision_id"] == str(revision.id)
            assert job.workspace_id is job.concurrency_user_id is None
            assert (job.run_after - job.created_at).total_seconds() >= 290
    else:
        revision_id = uuid4()
        ref = make_storage_object_ref(
            StorageBucket.PLATFORM_PRIVATE, f"platform/artifacts/{artifact.id}/{revision_id}.html"
        )
        await get_storage_provider().put_object(ref, b"orphan", content_type="text/html")
        job = Job(
            kind="platform.artifacts.cleanup_object",
            subject_type="artifact",
            subject_id=artifact.id,
            workspace_id=None,
            concurrency_user_id=None,
            payload={"revision_id": str(revision_id), "extension": ".html"},
        )
    async with maintenance_async_db_session() as db:
        await cleanup_platform_artifact_object(db, job)
    assert (await get_storage_provider().stat_object(ref) is not None) == committed


@pytest.mark.parametrize("owner", ["workspace_id", "concurrency_user_id"])
async def test_platform_artifact_cleanup_rejects_owned_job_before_storage(
    db_session,
    platform_context,
    monkeypatch,
    owner,
):
    from models.jobs import Job
    from services.jobs.handlers.cleanup_platform_artifact_object import (
        cleanup_platform_artifact_object,
    )

    module = importlib.import_module("services.jobs.handlers.cleanup_platform_artifact_object")
    storage = AsyncMock(side_effect=AssertionError("storage must remain untouched"))
    monkeypatch.setattr(module, "get_storage_provider", storage)
    job = Job(
        kind="platform.artifacts.cleanup_object",
        subject_type="artifact",
        subject_id=uuid4(),
        workspace_id=None,
        concurrency_user_id=None,
        payload={"revision_id": str(uuid4()), "extension": ".html"},
    )
    setattr(job, owner, uuid4())
    async with maintenance_async_db_session() as db:
        with pytest.raises(RuntimeError, match="unowned maintenance"):
            await cleanup_platform_artifact_object(db, job)
    storage.assert_not_called()


async def test_platform_artifact_lost_commit_response_preserves_revision_and_bytes(
    committed_db_session_factory,
    monkeypatch,
    tmp_path,
):
    from sqlalchemy import delete, update
    from sqlalchemy.ext.asyncio import AsyncSession

    from core.database import SESSION_MAINTENANCE_KEY
    from models.jobs import Job
    from models.user import User
    from models.workspace import Workspace

    email = f"artifact-commit-{uuid4().hex}@example.com"
    monkeypatch.setattr(settings, "SUPER_ADMIN_EMAILS", email)
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    reset_storage_provider_cache()
    async with maintenance_async_db_session() as db:
        actor, workspace = (
            build_user(email=email),
            build_workspace(slug=f"artifact-commit-{uuid4().hex}"),
        )
        db.add_all(
            [
                actor,
                workspace,
                build_workspace_membership(workspace_id=workspace.id, user_id=actor.id),
            ]
        )
    context = {"actor": actor, "workspace": workspace}
    artifact_ids = []
    original_commit = AsyncSession.commit
    try:
        async with committed_db_session_factory() as db:
            source = await _source(db, context)
            payload = PlatformArtifactCreateRequest(
                version_id=source[1].id,
                expected_current_version_id=source[1].id,
                request_id=uuid4(),
            )
            destination_id = uuid5(
                source[0].id,
                f"platform:{workspace.id}:{actor.id}:{payload.version_id}:{payload.expected_current_version_id}:{payload.request_id}",
            )
            artifact_ids.extend([source[0].id, destination_id])
            artifact = await _create(db, context, source, payload)
        failed = False

        async def lose_commit_response(db):
            nonlocal failed
            fail = False
            if db.info.get(SESSION_MAINTENANCE_KEY) and not failed:
                current_id = await db.scalar(
                    select(Artifact.current_version_id).where(Artifact.id == artifact.id)
                )
                fail = current_id != artifact.current_version_id
            await original_commit(db)
            if fail:
                failed = True
                raise RuntimeError("commit response lost")

        monkeypatch.setattr(AsyncSession, "commit", lose_commit_response)
        async with committed_db_session_factory() as db:
            with pytest.raises(RuntimeError, match="commit response lost"):
                await _edit(db, context, artifact)
        assert failed
        async with maintenance_async_db_session() as db:
            saved = await db.get(Artifact, artifact.id)
            assert saved.current_version_id != artifact.current_version_id
            assert saved.current_version_id == saved.published_version_id
            revision = await db.get(ArtifactRevision, saved.current_version_id)
            assert (
                await get_storage_provider().get_object(
                    make_storage_object_ref(StorageBucket.PLATFORM_PRIVATE, revision.object_key)
                )
                == b"<p>Edited report</p>"
            )
    finally:
        monkeypatch.setattr(AsyncSession, "commit", original_commit)
        async with maintenance_async_db_session() as db:
            await db.execute(
                delete(Job).where(Job.subject_type == "artifact", Job.subject_id.in_(artifact_ids))
            )
            await db.execute(delete(AuditEvent).where(AuditEvent.actor_user_id == actor.id))
            await db.execute(
                update(Artifact)
                .where(Artifact.id.in_(artifact_ids))
                .values(is_published=False, current_version_id=None, published_version_id=None)
            )
            await db.execute(
                delete(ArtifactRevision).where(ArtifactRevision.artifact_id.in_(artifact_ids))
            )
            await db.execute(delete(Artifact).where(Artifact.id.in_(artifact_ids)))
            await db.execute(
                delete(WorkspaceMembership).where(
                    WorkspaceMembership.user_id == actor.id,
                    WorkspaceMembership.workspace_id == workspace.id,
                )
            )
            await db.execute(delete(Workspace).where(Workspace.id == workspace.id))
            await db.execute(delete(User).where(User.id == actor.id))
        reset_storage_provider_cache()


@pytest.mark.parametrize(
    "operation",
    [
        "create_artifact",
        "publish_artifact",
        "withdraw_artifact",
        "delete_artifact",
        "get_artifact",
        "list_artifacts",
        "get_version_content",
    ],
)
async def test_platform_artifact_management_denies_editors_before_maintenance(
    db_session,
    platform_context,
    monkeypatch,
    operation,
):
    from unittest.mock import Mock

    editor, _membership_id = await _editor(platform_context)
    await _tenant(db_session, editor)
    module = importlib.import_module("services.artifacts.platform.utils")
    maintenance = Mock(side_effect=AssertionError("maintenance must remain closed"))
    monkeypatch.setattr(module, "maintenance_async_db_session", maintenance)
    operation_module = importlib.import_module(f"services.artifacts.platform.{operation}")
    kwargs = dict(editor)
    if operation != "list_artifacts":
        kwargs["artifact_id"] = uuid4()
    if operation in {"create_artifact", "publish_artifact", "withdraw_artifact", "delete_artifact"}:
        kwargs["request"] = build_test_request()
    if operation == "create_artifact":
        kwargs["payload"] = PlatformArtifactCreateRequest(
            version_id=uuid4(), expected_current_version_id=uuid4(), request_id=uuid4()
        )
    if operation == "publish_artifact":
        kwargs["payload"] = PlatformArtifactVersionRequest(expected_current_version_id=uuid4())
    with pytest.raises(AuthorizationError):
        await getattr(operation_module, operation)(db_session, **kwargs)
    maintenance.assert_not_called()


async def test_platform_artifact_linked_private_asset_rejected_before_reservation(
    db_session,
    platform_context,
    monkeypatch,
):
    source = await _source(db_session, platform_context, '<img src="/files/private.png">')
    payload = PlatformArtifactCreateRequest(
        version_id=source[1].id, expected_current_version_id=source[1].id, request_id=uuid4()
    )
    destination_id = uuid5(
        source[0].id,
        f"platform:{platform_context['workspace'].id}:{platform_context['actor'].id}:{payload.version_id}:{payload.expected_current_version_id}:{payload.request_id}",
    )
    module = importlib.import_module("services.artifacts.platform.create_artifact")
    copy = AsyncMock(side_effect=AssertionError("copy must remain untouched"))
    monkeypatch.setattr(module, "copy_object", copy)
    with pytest.raises(AppValidationError, match="must contain their assets"):
        await _create(db_session, platform_context, source, payload)
    copy.assert_not_awaited()
    async with maintenance_async_db_session() as db:
        assert await db.get(Artifact, destination_id) is None
        assert (
            await db.scalar(
                select(ArtifactRevision).where(ArtifactRevision.artifact_id == destination_id)
            )
            is None
        )


async def test_platform_artifact_publication_hides_other_workspace_source(
    db_session,
    platform_context,
    monkeypatch,
):
    source = await _source(db_session, platform_context)
    async with maintenance_async_db_session() as db:
        other_workspace = build_workspace(slug=f"artifact-source-other-{uuid4().hex}")
        db.add_all(
            [
                other_workspace,
                build_workspace_membership(
                    workspace_id=other_workspace.id, user_id=platform_context["actor"].id
                ),
            ]
        )
    other_context = {"actor": platform_context["actor"], "workspace": other_workspace}
    module = importlib.import_module("services.artifacts.platform.create_artifact")
    copy = AsyncMock(side_effect=AssertionError("copy must remain untouched"))
    monkeypatch.setattr(module, "copy_object", copy)
    with pytest.raises(NotFoundError):
        await _create(db_session, other_context, source)
    copy.assert_not_awaited()


async def test_platform_artifact_editor_history_excludes_unpublished_drafts(
    db_session,
    platform_context,
    monkeypatch,
):
    artifact = await _create(db_session, platform_context)
    await withdraw_artifact(
        db_session,
        **platform_context,
        request=build_test_request(),
        artifact_id=artifact.id,
    )
    first_draft = await _edit(db_session, platform_context, artifact, "<p>Private draft</p>")
    reviewed_draft = await restore_artifact_version(
        db_session,
        **platform_context,
        request=build_test_request(),
        artifact_id=artifact.id,
        payload=PlatformArtifactRestoreRequest(
            expected_current_version_id=first_draft.current_version_id,
            version_id=first_draft.current_version_id,
        ),
    )
    published = await publish_artifact(
        db_session,
        **platform_context,
        request=build_test_request(),
        artifact_id=artifact.id,
        payload=PlatformArtifactVersionRequest(
            expected_current_version_id=reviewed_draft.current_version_id
        ),
    )
    editor, _membership_id = await _editor(platform_context)
    edited = await _edit(db_session, editor, published)
    assert {version.id for version in edited.versions} == {
        artifact.current_version_id,
        reviewed_draft.current_version_id,
        edited.current_version_id,
    }
    assert first_draft.current_version_id not in {version.id for version in edited.versions}
    restored = next(
        version for version in edited.versions if version.id == reviewed_draft.current_version_id
    )
    assert restored.restored_from_revision_id is None
    module = importlib.import_module("services.artifacts.platform.restore_artifact_version")
    content = AsyncMock(side_effect=AssertionError("private draft must not be read"))
    monkeypatch.setattr(module, "read_content", content)
    with pytest.raises(NotFoundError):
        await restore_artifact_version(
            db_session,
            **editor,
            request=build_test_request(),
            artifact_id=artifact.id,
            payload=PlatformArtifactRestoreRequest(
                expected_current_version_id=edited.current_version_id,
                version_id=first_draft.current_version_id,
            ),
        )
    content.assert_not_awaited()
    async with maintenance_async_db_session() as db:
        row = await db.get(Artifact, artifact.id)
        assert row.current_version_id == row.published_version_id == edited.current_version_id
