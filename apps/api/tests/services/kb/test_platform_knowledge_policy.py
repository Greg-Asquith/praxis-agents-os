# apps/api/tests/services/kb/test_platform_knowledge_policy.py

"""Platform knowledge keeps tenant content private and validates provider authority."""

import importlib
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from core.database import maintenance_async_db_session
from core.exceptions.auth import AuthorizationError
from core.exceptions.general import AppValidationError, ConflictError
from core.settings import settings
from models.jobs import Job
from models.kb import KBDocument
from services.kb.platform import create_manual_document
from services.kb.schemas import PlatformKBManualDocumentCreateRequest
from services.kb.utils import compute_markdown_hash
from tests.factories import build_user, build_workspace
from tests.support.requests import build_test_request

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def policy_actor(db_session_factory, monkeypatch):
    actor = build_user(email=f"policy-admin-{uuid4()}@example.com")
    monkeypatch.setattr(settings, "SUPER_ADMIN_EMAILS", actor.email)
    async with maintenance_async_db_session() as db:
        db.add(actor)
    return actor


async def test_platform_deduplication_ignores_tenant_private_content(
    db_session_factory, policy_actor
):
    content = f"Shared guidance {uuid4()}"
    async with maintenance_async_db_session() as db:
        workspace = build_workspace()
        db.add(workspace)
        await db.flush()
        private = KBDocument(
            workspace_id=workspace.id,
            title="Private tenant guidance",
            source_type="manual",
            content_md=content,
            content_hash=compute_markdown_hash(content),
            is_private=True,
            annotation_enabled=False,
        )
        db.add(private)
        await db.flush()
        private_id = private.id
    payload = PlatformKBManualDocumentCreateRequest(title="Shared guidance", content_md=content)
    async with db_session_factory() as db:
        created = await create_manual_document(
            db, actor=policy_actor, request=build_test_request(), payload=payload
        )
    assert created.id != private_id and created.scope == "platform"
    async with db_session_factory() as db:
        with pytest.raises(ConflictError) as rejected:
            await create_manual_document(
                db, actor=policy_actor, request=build_test_request(), payload=payload
            )
    assert rejected.value.details["document_id"] == str(created.id)
    assert str(private_id) not in str(rejected.value.details)
    async with maintenance_async_db_session() as db:
        documents = list(
            (
                await db.scalars(
                    select(KBDocument).where(
                        KBDocument.content_hash == compute_markdown_hash(content)
                    )
                )
            ).all()
        )
        assert {document.id for document in documents} == {private_id, created.id}


@pytest.mark.parametrize(
    "content,limit,error",
    [("-----BEGIN PRIVATE KEY-----", 1_024, "private key"), ("é" * 6, 10, "size limit")],
)
async def test_platform_manual_creation_enforces_shared_content_policy(
    db_session_factory, policy_actor, monkeypatch, content, limit, error
):
    monkeypatch.setattr(settings, "KB_MAX_DOCUMENT_BYTES", limit)
    async with db_session_factory() as db:
        with pytest.raises(AppValidationError, match=error):
            await create_manual_document(
                db,
                actor=policy_actor,
                request=build_test_request(),
                payload=PlatformKBManualDocumentCreateRequest(title="Guidance", content_md=content),
            )
    async with maintenance_async_db_session() as db:
        assert (
            await db.scalar(
                select(KBDocument.id).where(
                    KBDocument.scope == "platform",
                    KBDocument.created_by_user_id == policy_actor.id,
                )
            )
            is None
        )


@pytest.mark.parametrize(
    "invalid", ["malformed_version", "non_text_version", "workspace", "revoked"]
)
@pytest.mark.parametrize("pipeline", ["ingest_platform_document", "embed_platform_chunks"])
async def test_invalid_platform_job_is_rejected_before_provider_io(
    policy_actor, monkeypatch, invalid, pipeline
):
    job = Job(
        kind=f"kb.{pipeline}",
        subject_type="kb_document",
        subject_id=uuid4(),
        concurrency_user_id=policy_actor.id,
        initiated_by_user_id=policy_actor.id,
        payload={"version": str(uuid4())},
    )
    if invalid == "malformed_version":
        job.payload = {"version": "not-a-version"}
    elif invalid == "non_text_version":
        job.payload = {"version": {"unexpected": "object"}}
    elif invalid == "workspace":
        job.workspace_id = uuid4()
    else:
        monkeypatch.setattr(settings, "SUPER_ADMIN_EMAILS", "another-admin@example.com")
    module = importlib.import_module(f"services.kb.{pipeline}")
    provider_call = AsyncMock()
    monkeypatch.setattr(
        module,
        "annotate_chunks" if pipeline == "ingest_platform_document" else "embed_chunk_batch",
        provider_call,
    )
    with pytest.raises(AuthorizationError):
        await getattr(module, pipeline)(job)
    provider_call.assert_not_awaited()
