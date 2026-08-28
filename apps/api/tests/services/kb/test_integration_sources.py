"""Knowledge Base integration import and refresh service tests."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from pydantic_ai import ModelRetry
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import (
    SESSION_USER_ID_KEY,
    configure_async_db_session,
    get_async_db_session_factory,
    set_session_tenant_context,
)
from core.exceptions.auth import AuthorizationError
from core.exceptions.general import AppValidationError, ConflictError, NotFoundError
from core.exceptions.integration import IntegrationRateLimitError, IntegrationTimeoutError
from models.audit_event import AuditEvent
from models.integrations import IntegrationConnection, IntegrationResource
from models.jobs import Job
from models.kb import KBChunk, KBDocument
from models.workspace import WorkspaceMembership, WorkspaceRole
from services.agents.runtime.tools.kb import read_document
from services.integrations.plugin import (
    PROVIDER_PLUGINS,
    KnowledgeSourceAccessLostError,
    KnowledgeSourceDocument,
    KnowledgeSourcePreview,
)
from services.jobs.domain import JOB_STATUS_RUNNING, JOB_STATUS_SUCCEEDED
from services.jobs.finalize_job import finalize_job_success
from services.jobs.handlers.ingest_kb_document import handle_ingest_kb_document
from services.kb.documents import reprocess_document
from services.kb.get_document import get_kb_document
from services.kb.ingest_document import ingest_kb_document
from services.kb.integration_sources import import_integration_document
from services.kb.schemas import KBIntegrationDocumentCreateRequest
from tests.factories import (
    build_external_credential,
    build_integration_connection,
    build_integration_resource,
    build_user,
    build_workspace_membership,
)
from tests.services.kb.conftest import KBActors

pytestmark = pytest.mark.asyncio

PAGE_ID = "01234567-89ab-cdef-0123-456789abcdef"
PAGE_URL = "https://www.notion.so/Guide-0123456789abcdef0123456789abcdef"


@dataclass
class SourceState:
    markdown: str = "# Guide\n\nImported knowledge."
    title: str = "Provider guide"
    source_updated_at: datetime = datetime(2026, 8, 27, tzinfo=UTC)
    fetch_error: Exception | None = None
    preview_in_transaction: bool | None = None
    fetch_in_transaction: bool | None = None
    after_preview: Callable[[AsyncSession], Awaitable[None]] | None = None
    after_fetch: Callable[[AsyncSession], Awaitable[None]] | None = None


@dataclass(frozen=True)
class IntegrationScenario:
    membership: WorkspaceMembership
    connection: IntegrationConnection
    resource: IntegrationResource
    state: SourceState


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/kb/documents/from-integration",
            "headers": [],
        }
    )


async def _scenario(
    db: AsyncSession,
    actors: KBActors,
    monkeypatch: pytest.MonkeyPatch,
) -> IntegrationScenario:
    membership = build_workspace_membership(
        workspace_id=actors.workspace.id,
        user_id=actors.user.id,
        role=WorkspaceRole.MEMBER,
    )
    credential = build_external_credential(provider_key="notion")
    connection = build_integration_connection(
        credential=credential,
        user=actors.user,
        owner_user_id=actors.user.id,
        status="active",
    )
    resource = build_integration_resource(
        connection=connection,
        resource_type="notion_workspace",
        external_id="workspace-id",
        display_name="Example workspace",
        availability="available",
    )
    db.add_all([membership, credential, connection, resource])
    await db.flush()

    state = SourceState()

    async def preview_source(db, connection, resource, reference):
        del connection, resource
        state.preview_in_transaction = db.in_transaction()
        if state.after_preview is not None:
            await state.after_preview(db)
        return KnowledgeSourcePreview(
            reference=dict(reference),
            external_id=PAGE_ID,
            title=state.title,
            url=PAGE_URL,
            source_updated_at=state.source_updated_at,
            markdown_excerpt=state.markdown,
        )

    async def fetch_source(db, connection, resource, external_id):
        del connection, resource
        assert external_id == PAGE_ID
        state.fetch_in_transaction = db.in_transaction()
        if state.fetch_error is not None:
            raise state.fetch_error
        if state.after_fetch is not None:
            await state.after_fetch(db)
        return KnowledgeSourceDocument(
            external_id=PAGE_ID,
            title=state.title,
            url=PAGE_URL,
            source_updated_at=state.source_updated_at,
            markdown=state.markdown,
        )

    original = PROVIDER_PLUGINS["notion"]
    assert original.knowledge_source is not None
    monkeypatch.setitem(
        PROVIDER_PLUGINS,
        "notion",
        replace(
            original,
            knowledge_source=replace(
                original.knowledge_source,
                preview=preview_source,
                fetch=fetch_source,
            ),
        ),
    )
    return IntegrationScenario(
        membership=membership,
        connection=connection,
        resource=resource,
        state=state,
    )


async def _import(
    db: AsyncSession,
    actors: KBActors,
    scenario: IntegrationScenario,
    *,
    title: str | None = None,
    is_private: bool = True,
):
    return await import_integration_document(
        db,
        request=_request(),
        actor=actors.user,
        workspace=actors.workspace,
        membership=scenario.membership,
        payload=KBIntegrationDocumentCreateRequest(
            integration_resource_id=scenario.resource.id,
            source=PAGE_URL,
            title=title,
            is_private=is_private,
        ),
    )


async def _ingest(db: AsyncSession, actors: KBActors, document_id: UUID) -> None:
    await ingest_kb_document(
        db,
        document_id=document_id,
        workspace_id=actors.workspace.id,
        initiated_by_user_id=actors.user.id,
    )


async def test_import_is_private_by_default_and_records_safe_provenance(
    db_session: AsyncSession,
    kb_actors: KBActors,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = await _scenario(db_session, kb_actors, monkeypatch)

    imported = await _import(db_session, kb_actors, scenario)

    document = await db_session.get(KBDocument, imported.id)
    assert document is not None
    assert document.title == "Provider guide"
    assert document.is_private is True
    assert document.source_type == "integration"
    assert document.integration_resource_id == scenario.resource.id
    assert document.external_id == PAGE_ID
    assert document.external_url == PAGE_URL
    assert document.source_sync_status == "pending"
    assert document.meta == {
        "provider_key": "notion",
        "source_title": "Provider guide",
    }
    assert scenario.state.preview_in_transaction is False

    job = await db_session.scalar(
        select(Job).where(Job.kind == "kb.ingest_document", Job.subject_id == document.id)
    )
    assert job is not None
    assert job.payload == {}
    audit = await db_session.scalar(
        select(AuditEvent).where(AuditEvent.resource_id == str(document.id))
    )
    assert audit is not None
    assert audit.details == {
        "source_type": "integration",
        "is_private": True,
        "provider_key": "notion",
    }


async def test_import_hides_an_unknown_personal_resource(
    db_session: AsyncSession,
    kb_actors: KBActors,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = await _scenario(db_session, kb_actors, monkeypatch)

    with pytest.raises(NotFoundError, match="Integration resource not found"):
        await import_integration_document(
            db_session,
            request=_request(),
            actor=kb_actors.user,
            workspace=kb_actors.workspace,
            membership=scenario.membership,
            payload=KBIntegrationDocumentCreateRequest(
                integration_resource_id=uuid4(),
                source=PAGE_URL,
            ),
        )


@pytest.mark.parametrize(
    "denial",
    [
        "another_user",
        "workspace_connection",
        "resource_deleted",
        "resource_unavailable",
        "connection_deleted",
        "connection_revoked",
        "unsupported_resource_type",
        "unsupported_contribution",
        "workspace_deleted",
    ],
)
async def test_import_hides_every_unusable_integration_resource(
    db_session: AsyncSession,
    kb_actors: KBActors,
    monkeypatch: pytest.MonkeyPatch,
    denial: str,
) -> None:
    scenario = await _scenario(db_session, kb_actors, monkeypatch)
    actor = kb_actors.user
    membership = scenario.membership
    resource = scenario.resource

    if denial == "another_user":
        actor = build_user(email=f"other-{uuid4().hex}@example.com")
        membership = build_workspace_membership(
            workspace_id=kb_actors.workspace.id,
            user_id=actor.id,
            role=WorkspaceRole.MEMBER,
        )
        db_session.add_all([actor, membership])
    elif denial == "workspace_connection":
        credential = build_external_credential(provider_key="notion")
        connection = build_integration_connection(
            credential=credential,
            user=kb_actors.user,
            workspace=kb_actors.workspace,
            status="active",
        )
        resource = build_integration_resource(
            connection=connection,
            resource_type="notion_workspace",
            external_id="workspace-owned",
            availability="available",
        )
        db_session.add_all([credential, connection, resource])
    elif denial == "resource_deleted":
        scenario.resource.soft_delete(cascade=False)
    elif denial == "resource_unavailable":
        scenario.resource.availability = "unavailable"
    elif denial == "connection_deleted":
        scenario.connection.soft_delete(cascade=False)
    elif denial == "connection_revoked":
        scenario.connection.status = "revoked"
    elif denial == "workspace_deleted":
        kb_actors.workspace.soft_delete(cascade=False)
    elif denial == "unsupported_contribution":
        plugin = PROVIDER_PLUGINS[scenario.connection.provider_key]
        monkeypatch.setitem(
            PROVIDER_PLUGINS,
            scenario.connection.provider_key,
            replace(plugin, knowledge_source=None),
        )
    else:
        scenario.resource.resource_type = "notion_data_source"
    await db_session.flush()

    with pytest.raises(NotFoundError, match="Integration resource not found"):
        await import_integration_document(
            db_session,
            request=_request(),
            actor=actor,
            workspace=kb_actors.workspace,
            membership=membership,
            payload=KBIntegrationDocumentCreateRequest(
                integration_resource_id=resource.id,
                source=PAGE_URL,
            ),
        )


@pytest.mark.parametrize("revocation", ["membership", "connection", "resource"])
async def test_import_rechecks_source_access_after_provider_preview(
    db_session: AsyncSession,
    kb_actors: KBActors,
    monkeypatch: pytest.MonkeyPatch,
    revocation: str,
) -> None:
    scenario = await _scenario(db_session, kb_actors, monkeypatch)

    async def revoke_after_preview(db: AsyncSession) -> None:
        if revocation == "membership":
            statement = (
                update(WorkspaceMembership)
                .where(WorkspaceMembership.id == scenario.membership.id)
                .values(role=WorkspaceRole.READ_ONLY.value)
            )
        elif revocation == "connection":
            statement = (
                update(IntegrationConnection)
                .where(IntegrationConnection.id == scenario.connection.id)
                .values(status="revoked")
            )
        else:
            statement = (
                update(IntegrationResource)
                .where(IntegrationResource.id == scenario.resource.id)
                .values(availability="unavailable")
            )
        await db.execute(statement)
        await db.commit()

    scenario.state.after_preview = revoke_after_preview
    expected_error = AuthorizationError if revocation == "membership" else NotFoundError

    with pytest.raises(expected_error):
        await _import(db_session, kb_actors, scenario)

    assert (
        await db_session.scalar(
            select(func.count(KBDocument.id)).where(
                KBDocument.workspace_id == kb_actors.workspace.id,
                KBDocument.source_type == "integration",
            )
        )
        == 0
    )


async def test_import_honors_explicit_title_and_workspace_sharing(
    db_session: AsyncSession,
    kb_actors: KBActors,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = await _scenario(db_session, kb_actors, monkeypatch)

    imported = await _import(
        db_session,
        kb_actors,
        scenario,
        title="Workspace handbook",
        is_private=False,
    )

    document = await db_session.get(KBDocument, imported.id)
    assert document is not None
    assert document.title == "Workspace handbook"
    assert document.is_private is False


async def test_ingest_uses_dedicated_creator_context_without_provider_transaction(
    db_session: AsyncSession,
    kb_actors: KBActors,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = await _scenario(db_session, kb_actors, monkeypatch)
    imported = await _import(db_session, kb_actors, scenario)
    await db_session.commit()

    session_factory = get_async_db_session_factory()
    async with session_factory() as job_db:
        await configure_async_db_session(job_db)
        await set_session_tenant_context(job_db, workspace_id=kb_actors.workspace.id)
        assert SESSION_USER_ID_KEY not in job_db.info
        await _ingest(job_db, kb_actors, imported.id)
        await job_db.commit()
        assert SESSION_USER_ID_KEY not in job_db.info

    document = await db_session.get(KBDocument, imported.id)
    assert document is not None
    await db_session.refresh(document)
    assert scenario.state.fetch_in_transaction is False
    assert document.status == "ready"
    assert document.source_sync_status == "ready"
    assert document.source_updated_at == scenario.state.source_updated_at
    assert document.source_synced_at is not None
    assert document.content_md == scenario.state.markdown
    assert document.meta == {
        "provider_key": "notion",
        "source_title": "Provider guide",
        "last_source_updated_at": scenario.state.source_updated_at.isoformat(),
    }


@pytest.mark.parametrize("revocation", ["membership", "connection", "resource"])
async def test_ingest_rechecks_source_access_after_provider_fetch(
    db_session: AsyncSession,
    kb_actors: KBActors,
    monkeypatch: pytest.MonkeyPatch,
    revocation: str,
) -> None:
    scenario = await _scenario(db_session, kb_actors, monkeypatch)
    imported = await _import(db_session, kb_actors, scenario)

    async def revoke_after_fetch(db: AsyncSession) -> None:
        if revocation == "membership":
            statement = (
                update(WorkspaceMembership)
                .where(WorkspaceMembership.id == scenario.membership.id)
                .values(deleted=True, deleted_at=datetime.now(UTC))
            )
        elif revocation == "connection":
            statement = (
                update(IntegrationConnection)
                .where(IntegrationConnection.id == scenario.connection.id)
                .values(status="revoked")
            )
        else:
            statement = (
                update(IntegrationResource)
                .where(IntegrationResource.id == scenario.resource.id)
                .values(availability="unavailable")
            )
        await db.execute(statement)
        await db.commit()

    scenario.state.after_fetch = revoke_after_fetch

    await _ingest(db_session, kb_actors, imported.id)

    document = await db_session.get(KBDocument, imported.id)
    assert document is not None
    await db_session.refresh(document)
    assert scenario.state.fetch_in_transaction is False
    assert document.status == "error"
    assert document.source_sync_status == "disconnected"
    assert document.content_md is None


async def test_duplicate_delivery_preserves_chunks_but_refreshes_source_metadata(
    db_session: AsyncSession,
    kb_actors: KBActors,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = await _scenario(db_session, kb_actors, monkeypatch)
    imported = await _import(db_session, kb_actors, scenario)
    await _ingest(db_session, kb_actors, imported.id)
    first_chunk_ids = tuple(
        await db_session.scalars(
            select(KBChunk.id)
            .where(KBChunk.document_id == imported.id)
            .order_by(KBChunk.chunk_index)
        )
    )
    document = await db_session.get(KBDocument, imported.id)
    assert document is not None
    first_synced_at = document.source_synced_at
    scenario.state.title = "Renamed provider guide"
    scenario.state.source_updated_at += timedelta(minutes=5)

    await _ingest(db_session, kb_actors, imported.id)

    second_chunk_ids = tuple(
        await db_session.scalars(
            select(KBChunk.id)
            .where(KBChunk.document_id == imported.id)
            .order_by(KBChunk.chunk_index)
        )
    )
    await db_session.refresh(document)
    assert second_chunk_ids == first_chunk_ids
    assert document.source_synced_at is not None
    assert document.source_synced_at >= first_synced_at
    assert document.source_updated_at == scenario.state.source_updated_at
    assert document.meta["source_title"] == "Renamed provider guide"
    assert (
        await db_session.scalar(
            select(func.count(Job.id)).where(
                Job.kind == "kb.embed_chunks",
                Job.subject_id == imported.id,
            )
        )
        == 1
    )


async def test_manual_refresh_resets_sync_state_and_rejects_concurrent_refresh(
    db_session: AsyncSession,
    kb_actors: KBActors,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = await _scenario(db_session, kb_actors, monkeypatch)
    imported = await _import(db_session, kb_actors, scenario)
    await _ingest(db_session, kb_actors, imported.id)

    refreshed = await reprocess_document(
        db_session,
        request=_request(),
        actor=kb_actors.user,
        workspace=kb_actors.workspace,
        membership=scenario.membership,
        document_id=imported.id,
    )
    assert refreshed.status == "pending"
    document = await db_session.get(KBDocument, imported.id)
    assert document is not None
    assert document.source_sync_status == "pending"

    with pytest.raises(ConflictError, match="already in progress"):
        await reprocess_document(
            db_session,
            request=_request(),
            actor=kb_actors.user,
            workspace=kb_actors.workspace,
            membership=scenario.membership,
            document_id=imported.id,
        )


@pytest.mark.parametrize("disconnect", ["revoked", "membership", "binding"])
async def test_refresh_rejects_disconnected_creator_grants(
    db_session: AsyncSession,
    kb_actors: KBActors,
    monkeypatch: pytest.MonkeyPatch,
    disconnect: str,
) -> None:
    scenario = await _scenario(db_session, kb_actors, monkeypatch)
    imported = await _import(db_session, kb_actors, scenario)
    document = await db_session.get(KBDocument, imported.id)
    assert document is not None
    if disconnect == "revoked":
        scenario.connection.status = "revoked"
    elif disconnect == "membership":
        scenario.membership.soft_delete(cascade=False)
    else:
        await db_session.delete(scenario.resource)
    await db_session.commit()
    if disconnect == "binding":
        await db_session.refresh(document)
        assert document.integration_resource_id is None

    await _ingest(db_session, kb_actors, imported.id)

    await db_session.refresh(document)
    assert document.status == "error"
    assert document.source_sync_status == "disconnected"
    assert document.content_md is None


@pytest.mark.parametrize("failure", ["secret", "timeout"])
async def test_provider_failures_do_not_publish_new_content(
    db_session: AsyncSession,
    kb_actors: KBActors,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    scenario = await _scenario(db_session, kb_actors, monkeypatch)
    imported = await _import(db_session, kb_actors, scenario)
    if failure == "secret":
        scenario.state.markdown = "Do not store AKIA1234567890ABCDEF."
        expected_error = AppValidationError
    else:
        scenario.state.fetch_error = IntegrationTimeoutError(
            "Notion did not respond before the timeout",
            provider_key="notion",
            operation="fetch_knowledge_source",
        )
        expected_error = IntegrationTimeoutError

    with pytest.raises(expected_error):
        await _ingest(db_session, kb_actors, imported.id)

    document = await db_session.get(KBDocument, imported.id)
    assert document is not None
    await db_session.refresh(document)
    assert document.status == "error"
    assert document.source_sync_status == "error"
    assert document.content_md is None
    assert document.content_hash == ""
    assert document.meta["last_error_code"] == (
        "timeout" if failure == "timeout" else "refresh_failed"
    )


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        (
            IntegrationTimeoutError(
                "Notion did not respond before the timeout",
                provider_key="notion",
                operation="fetch_knowledge_source",
            ),
            "timeout",
        ),
        (
            IntegrationRateLimitError(
                "Notion request limit reached",
                provider_key="notion",
                operation="fetch_knowledge_source",
            ),
            "rate_limited",
        ),
    ],
)
async def test_transient_refresh_failure_retains_last_ready_content(
    db_session: AsyncSession,
    kb_actors: KBActors,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    expected_code: str,
) -> None:
    scenario = await _scenario(db_session, kb_actors, monkeypatch)
    imported = await _import(db_session, kb_actors, scenario)
    await _ingest(db_session, kb_actors, imported.id)
    document = await db_session.get(KBDocument, imported.id)
    assert document is not None
    original_content = document.content_md
    original_hash = document.content_hash
    original_synced_at = document.source_synced_at
    original_chunk_ids = tuple(
        await db_session.scalars(
            select(KBChunk.id)
            .where(KBChunk.document_id == imported.id)
            .order_by(KBChunk.chunk_index)
        )
    )
    scenario.state.fetch_error = failure

    with pytest.raises(type(failure)):
        await _ingest(db_session, kb_actors, imported.id)

    await db_session.refresh(document)
    retained_chunk_ids = tuple(
        await db_session.scalars(
            select(KBChunk.id)
            .where(KBChunk.document_id == imported.id)
            .order_by(KBChunk.chunk_index)
        )
    )
    assert document.status == "error"
    assert document.source_sync_status == "error"
    assert document.source_synced_at is not None
    assert original_synced_at is not None
    assert document.source_synced_at > original_synced_at
    assert document.content_md == original_content
    assert document.content_hash == original_hash
    assert retained_chunk_ids == original_chunk_ids
    assert document.meta["last_error_code"] == expected_code


async def test_access_loss_clears_every_content_read_and_restores_after_refresh(
    db_session: AsyncSession,
    kb_actors: KBActors,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = await _scenario(db_session, kb_actors, monkeypatch)
    imported = await _import(db_session, kb_actors, scenario)
    await _ingest(db_session, kb_actors, imported.id)
    document = await db_session.get(KBDocument, imported.id)
    assert document is not None
    original_synced_at = document.source_synced_at
    document.summary = "Cached summary"
    await db_session.flush()
    scenario.state.fetch_error = KnowledgeSourceAccessLostError(
        "Notion no longer exposes this page",
        provider_key="notion",
        operation="fetch_knowledge_source",
    )

    await _ingest(db_session, kb_actors, imported.id)

    await db_session.refresh(document)
    assert document.status == "error"
    assert document.source_sync_status == "unavailable"
    assert document.source_synced_at is not None
    assert original_synced_at is not None
    assert document.source_synced_at > original_synced_at
    assert document.processing_error == (
        "This page is no longer accessible through the connected Notion account."
    )
    assert document.content_md is None
    assert document.summary is None
    assert document.content_hash == ""
    assert document.chunk_count == 0
    assert document.meta["last_error_code"] == "access_lost"
    assert (
        await db_session.scalar(
            select(func.count(KBChunk.id)).where(KBChunk.document_id == imported.id)
        )
        == 0
    )
    direct_read = await get_kb_document(
        db_session,
        workspace_id=kb_actors.workspace.id,
        user_id=kb_actors.user.id,
        document_id=imported.id,
    )
    assert direct_read.content_md is None
    other_user = build_user(email=f"kb-access-loss-{uuid4().hex}@example.com")
    db_session.add(other_user)
    await db_session.flush()
    with pytest.raises(NotFoundError):
        await get_kb_document(
            db_session,
            workspace_id=kb_actors.workspace.id,
            user_id=other_user.id,
            document_id=imported.id,
        )
    context = SimpleNamespace(
        deps=SimpleNamespace(
            db=db_session,
            workspace=kb_actors.workspace,
            user=kb_actors.user,
        )
    )
    with pytest.raises(ModelRetry, match="no readable content"):
        await read_document(context, imported.id)

    scenario.state.fetch_error = None
    scenario.state.markdown = "# Guide\n\nRestored knowledge."
    await reprocess_document(
        db_session,
        request=_request(),
        actor=kb_actors.user,
        workspace=kb_actors.workspace,
        membership=scenario.membership,
        document_id=imported.id,
    )
    await _ingest(db_session, kb_actors, imported.id)

    await db_session.refresh(document)
    assert document.status == "ready"
    assert document.source_sync_status == "ready"
    assert document.content_md == scenario.state.markdown
    assert document.chunk_count > 0
    assert "last_error_code" not in document.meta


async def test_definitive_access_loss_finishes_the_ingestion_job_successfully(
    db_session: AsyncSession,
    kb_actors: KBActors,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = await _scenario(db_session, kb_actors, monkeypatch)
    imported = await _import(db_session, kb_actors, scenario)
    scenario.state.fetch_error = KnowledgeSourceAccessLostError(
        "Notion no longer exposes this page",
        provider_key="notion",
        operation="fetch_knowledge_source",
    )
    job = await db_session.scalar(
        select(Job).where(Job.kind == "kb.ingest_document", Job.subject_id == imported.id)
    )
    assert job is not None
    owner_id = f"kb-access-loss-{uuid4().hex}"
    job.status = JOB_STATUS_RUNNING
    job.attempts = 1
    job.locked_by = owner_id
    job.locked_at = datetime.now(UTC)
    job.lock_expires_at = datetime.now(UTC) + timedelta(minutes=5)

    await handle_ingest_kb_document(db_session, job)
    finalized = await finalize_job_success(
        db_session,
        job,
        owner_instance_id=owner_id,
    )

    document = await db_session.get(KBDocument, imported.id)
    assert document is not None
    await db_session.refresh(document)
    assert finalized is True
    assert job.status == JOB_STATUS_SUCCEEDED
    assert job.last_error_code is None
    assert document.source_sync_status == "unavailable"
