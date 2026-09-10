# apps/api/tests/services/kb/test_platform_knowledge_management.py

"""Platform knowledge authoring authority and atomic publication lifecycle."""

import importlib
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import maintenance_async_db_session
from core.exceptions.auth import AuthorizationError
from core.exceptions.general import ConflictError, NotFoundError
from core.settings import settings
from models.audit_event import AuditEvent
from models.jobs import Job
from models.kb import KBDocument
from models.user import User
from models.workspace import WorkspaceRole
from services.kb.platform import (
    create_manual_document,
    delete_document,
    get_document,
    list_documents,
    publish_document,
    reprocess_document,
    update_document,
    withdraw_document,
)
from services.kb.schemas import (
    PlatformKBDocumentPublishRequest,
    PlatformKBDocumentUpdateRequest,
    PlatformKBFileDocumentCreateRequest,
    PlatformKBManualDocumentCreateRequest,
)
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.factories.kb import build_kb_chunk
from tests.support.requests import build_test_request
from utils.content import ContentScope

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def platform_actor(db_session_factory, monkeypatch):
    email = f"admin-{uuid4().hex}@example.com"
    monkeypatch.setattr(settings, "SUPER_ADMIN_EMAILS", email)
    async with maintenance_async_db_session() as db:
        actor, workspace = build_user(email=email), build_workspace()
        db.add_all(
            [
                actor,
                workspace,
                build_workspace_membership(
                    workspace_id=workspace.id, user_id=actor.id, role=WorkspaceRole.READ_ONLY
                ),
            ]
        )
    return actor


async def draft(db, actor):
    return await create_manual_document(
        db,
        actor=actor,
        request=build_test_request(),
        payload=PlatformKBManualDocumentCreateRequest(
            title="Policy", content_md=f"Shared policy {uuid4()}"
        ),
    )


async def ready(document_id):
    async with maintenance_async_db_session() as db:
        document = await db.get(KBDocument, document_id)
        document.status = "ready"
        document.processing_attempts = 1
        document.chunk_count = 1
        db.add(
            build_kb_chunk(
                document=document,
                scope=ContentScope.PLATFORM,
                embedding=[0.1] * 1024,
                embedding_provider="test",
                embedding_model="test",
                embedding_dims=1024,
            )
        )


async def publish(db, actor, document):
    return await publish_document(
        db,
        actor=actor,
        request=build_test_request(),
        document_id=document.id,
        payload=PlatformKBDocumentPublishRequest(
            expected_ingestion_version=document.meta["ingestion_version"]
        ),
    )


@pytest.mark.parametrize(
    "operation",
    [
        "create_manual_document",
        "create_document_from_file",
        "get_document",
        "list_documents",
        "update_document",
        "reprocess_document",
        "publish_document",
        "withdraw_document",
        "delete_document",
    ],
)
async def test_platform_knowledge_denies_non_admin_before_maintenance(monkeypatch, operation):
    monkeypatch.setattr(settings, "SUPER_ADMIN_EMAILS", "admin@example.com")
    actor = build_user(email="member@example.com")
    db = AsyncMock(spec=AsyncSession)
    utils = importlib.import_module("services.kb.platform.utils")
    maintenance, audit = Mock(), AsyncMock()
    monkeypatch.setattr(utils, "maintenance_async_db_session", maintenance)
    monkeypatch.setattr(utils, "record_platform_content_audit_event", audit)
    kwargs = {"actor": actor}
    if operation not in {"list_documents", "get_document"}:
        kwargs["request"] = build_test_request()
    if operation not in {"create_manual_document", "create_document_from_file", "list_documents"}:
        kwargs["document_id"] = uuid4()
    payloads = {
        "create_manual_document": PlatformKBManualDocumentCreateRequest(
            title="Policy", content_md="Policy"
        ),
        "create_document_from_file": PlatformKBFileDocumentCreateRequest(
            file_id=uuid4(), file_revision_id=uuid4()
        ),
        "update_document": PlatformKBDocumentUpdateRequest(title="Updated"),
        "publish_document": PlatformKBDocumentPublishRequest(
            expected_ingestion_version=str(uuid4())
        ),
    }
    if operation in payloads:
        kwargs["payload"] = payloads[operation]
    module = importlib.import_module(f"services.kb.platform.{operation}")
    with pytest.raises(AuthorizationError):
        await getattr(module, operation)(db, **kwargs)
    maintenance.assert_not_called()
    audit.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.parametrize(
    ("field", "value"),
    [("is_active", False), ("deleted", True), ("email", "former-admin@example.com")],
)
async def test_platform_knowledge_rechecks_stale_actor_authority(
    db_session, platform_actor, field, value
):
    async with maintenance_async_db_session() as db:
        live_actor = await db.get(User, platform_actor.id)
        setattr(live_actor, field, value)

    with pytest.raises(AuthorizationError):
        await list_documents(db_session, actor=platform_actor)
    with pytest.raises(AuthorizationError):
        await draft(db_session, platform_actor)

    async with maintenance_async_db_session() as db:
        assert (
            await db.scalar(
                select(KBDocument.id).where(KBDocument.created_by_user_id == platform_actor.id)
            )
            is None
        )


async def test_platform_knowledge_read_only_admin_lifecycle(db_session, platform_actor):
    document = await draft(db_session, platform_actor)
    assert (
        document.scope == "platform" and document.workspace_id is None and not document.is_published
    )
    assert document.can_manage_platform
    with pytest.raises(ConflictError):
        await publish(db_session, platform_actor, document)
    await ready(document.id)
    published = await publish(db_session, platform_actor, document)
    assert published.is_published
    for operation in (update_document, reprocess_document):
        kwargs = (
            {"payload": PlatformKBDocumentUpdateRequest(title="Changed")}
            if operation == update_document
            else {}
        )
        with pytest.raises(ConflictError, match="Withdraw"):
            await operation(
                db_session,
                actor=platform_actor,
                request=build_test_request(),
                document_id=document.id,
                **kwargs,
            )
    await withdraw_document(
        db_session, actor=platform_actor, request=build_test_request(), document_id=document.id
    )
    updated = await update_document(
        db_session,
        actor=platform_actor,
        request=build_test_request(),
        document_id=document.id,
        payload=PlatformKBDocumentUpdateRequest(content_md="Updated policy"),
    )
    assert not updated.is_published and updated.status == "pending"
    assert updated.meta["ingestion_version"] != document.meta["ingestion_version"]
    with pytest.raises(ConflictError, match="changed"):
        await publish(db_session, platform_actor, document)
    result = await list_documents(db_session, actor=platform_actor)
    assert document.id in [item.id for item in result.documents]
    await delete_document(
        db_session, actor=platform_actor, request=build_test_request(), document_id=document.id
    )
    with pytest.raises(NotFoundError):
        await get_document(db_session, actor=platform_actor, document_id=document.id)
    async with maintenance_async_db_session() as db:
        jobs = list(await db.scalars(select(Job).where(Job.subject_id == document.id)))
        assert len(jobs) == 2
        assert all(
            job.workspace_id is None and job.concurrency_user_id == platform_actor.id
            for job in jobs
        )
        events = list(
            await db.scalars(
                select(AuditEvent)
                .where(AuditEvent.resource_id == str(document.id))
                .order_by(AuditEvent.created_at)
            )
        )
        assert [event.details["operation"] for event in events] == [
            "create",
            "publish",
            "withdraw",
            "update",
            "delete",
        ]
        assert all(event.workspace_id is None for event in events)


@pytest.mark.parametrize(
    ("field", "value"),
    [("content_md", None), ("content_hash", ""), ("processing_attempts", 0), ("chunk_count", 2)],
)
async def test_platform_publication_requires_complete_canonical_content(
    db_session, platform_actor, field, value
):
    document = await draft(db_session, platform_actor)
    await ready(document.id)
    async with maintenance_async_db_session() as db:
        setattr(await db.get(KBDocument, document.id), field, value)
    with pytest.raises(ConflictError, match="processing must finish"):
        await publish(db_session, platform_actor, document)
    async with maintenance_async_db_session() as db:
        assert not (await db.get(KBDocument, document.id)).is_published


@pytest.mark.parametrize(
    "operation", ["create", "publish", "withdraw", "delete", "update", "reprocess"]
)
async def test_platform_knowledge_audit_failure_rolls_back(
    db_session, platform_actor, monkeypatch, operation
):
    document = None
    if operation != "create":
        document = await draft(db_session, platform_actor)
        await ready(document.id)
        if operation in {"withdraw", "delete"}:
            await publish(db_session, platform_actor, document)
    utils = importlib.import_module("services.kb.platform.utils")
    monkeypatch.setattr(
        utils,
        "record_platform_content_audit_event",
        AsyncMock(side_effect=RuntimeError("audit failed")),
    )
    with pytest.raises(RuntimeError, match="audit failed"):
        if operation == "create":
            await draft(db_session, platform_actor)
        elif operation == "publish":
            await publish(db_session, platform_actor, document)
        else:
            function = {
                "withdraw": withdraw_document,
                "delete": delete_document,
                "update": update_document,
                "reprocess": reprocess_document,
            }[operation]
            kwargs = (
                {"payload": PlatformKBDocumentUpdateRequest(title="Changed")}
                if operation == "update"
                else {}
            )
            await function(
                db_session,
                actor=platform_actor,
                request=build_test_request(),
                document_id=document.id,
                **kwargs,
            )
    async with maintenance_async_db_session() as db:
        if document is None:
            assert (
                await db.scalar(
                    select(KBDocument.id).where(KBDocument.created_by_user_id == platform_actor.id)
                )
                is None
            )
            assert (
                await db.scalar(select(Job.id).where(Job.initiated_by_user_id == platform_actor.id))
                is None
            )
        else:
            saved = await db.get(KBDocument, document.id)
            assert not saved.deleted and saved.status == "ready" and saved.title == "Policy"
            assert saved.is_published == (operation in {"withdraw", "delete"})
            assert saved.meta["ingestion_version"] == document.meta["ingestion_version"]


async def ingestion_job(document_id, version):
    async with maintenance_async_db_session() as db:
        return await db.scalar(
            select(Job).where(
                Job.subject_id == document_id,
                Job.kind == "kb.platform_ingest_document",
                Job.payload["version"].astext == version,
            )
        )


async def test_platform_knowledge_actual_ingestion_replaces_chunks_and_needs_republication(
    db_session, platform_actor
):
    from models.kb import KBChunk
    from services.kb.ingest_platform_document import ingest_platform_document

    document = await draft(db_session, platform_actor)
    first_job = await ingestion_job(document.id, document.meta["ingestion_version"])
    await ingest_platform_document(first_job)
    document = await get_document(db_session, actor=platform_actor, document_id=document.id)
    assert document.status == "ready" and document.meta["embedding_status"] == "pending"
    await publish(db_session, platform_actor, document)
    await withdraw_document(
        db_session, actor=platform_actor, request=build_test_request(), document_id=document.id
    )
    changed = await update_document(
        db_session,
        actor=platform_actor,
        request=build_test_request(),
        document_id=document.id,
        payload=PlatformKBDocumentUpdateRequest(
            content_md="The revised policy requires two reviewers."
        ),
    )
    async with maintenance_async_db_session() as db:
        assert await db.scalar(select(KBChunk.id).where(KBChunk.document_id == document.id)) is None
    await ingest_platform_document(first_job)
    assert (
        await get_document(db_session, actor=platform_actor, document_id=document.id)
    ).status == "pending"
    job = await ingestion_job(changed.id, changed.meta["ingestion_version"])
    await ingest_platform_document(job)
    await ingest_platform_document(job)
    saved = await get_document(db_session, actor=platform_actor, document_id=document.id)
    assert saved.status == "ready" and not saved.is_published
    async with maintenance_async_db_session() as db:
        chunks = list(await db.scalars(select(KBChunk).where(KBChunk.document_id == document.id)))
        assert len(chunks) == saved.chunk_count == 1
        assert chunks[0].content == changed.content_md
    assert (await publish(db_session, platform_actor, saved)).is_published


async def test_platform_knowledge_withdraw_cancels_processing_and_allows_reprocess(
    db_session, platform_actor
):
    from services.kb.ingest_platform_document import ingest_platform_document

    document = await draft(db_session, platform_actor)
    job = await ingestion_job(document.id, document.meta["ingestion_version"])
    withdrawn = await withdraw_document(
        db_session, actor=platform_actor, request=build_test_request(), document_id=document.id
    )
    assert withdrawn.status == "error"
    await ingest_platform_document(job)
    saved = await get_document(db_session, actor=platform_actor, document_id=document.id)
    assert saved.status == "error" and not saved.is_published
    retried = await reprocess_document(
        db_session, actor=platform_actor, request=build_test_request(), document_id=document.id
    )
    async with maintenance_async_db_session() as db:
        event = await db.scalar(
            select(AuditEvent).where(
                AuditEvent.resource_id == str(document.id),
                AuditEvent.details["operation"].astext == "update",
            )
        )
        assert event.details["changed_fields"] == ["status"]
    await ingest_platform_document(
        await ingestion_job(document.id, retried.meta["ingestion_version"])
    )
    saved = await get_document(db_session, actor=platform_actor, document_id=document.id)
    assert saved.status == "ready" and not saved.is_published


async def test_platform_knowledge_upload_pins_exact_parent_revision(db_session, platform_actor):
    from services.kb.platform import create_document_from_file
    from tests.factories import build_file, build_file_revision

    workspace = build_workspace(slug=f"upload-{uuid4().hex}")
    async with maintenance_async_db_session() as db:
        db.add(workspace)
        file = build_file(
            workspace=workspace,
            scope=ContentScope.PLATFORM,
            workspace_id=None,
            content_type="text/plain",
            extension=".txt",
        )
        other = build_file(workspace=workspace, scope=ContentScope.PLATFORM, workspace_id=None)
        db.add_all([file, other])
        await db.flush()
        revision = build_file_revision(file)
        other_revision = build_file_revision(other)
        db.add_all([revision, other_revision])
    with pytest.raises(NotFoundError):
        await create_document_from_file(
            db_session,
            actor=platform_actor,
            request=build_test_request(),
            payload=PlatformKBFileDocumentCreateRequest(
                file_id=file.id, file_revision_id=other_revision.id
            ),
        )
    document = await create_document_from_file(
        db_session,
        actor=platform_actor,
        request=build_test_request(),
        payload=PlatformKBFileDocumentCreateRequest(file_id=file.id, file_revision_id=revision.id),
    )
    async with maintenance_async_db_session() as db:
        saved = await db.get(KBDocument, document.id)
        assert saved.file_revision_id == revision.id
        assert not saved.is_published
