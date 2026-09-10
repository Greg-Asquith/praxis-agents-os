# apps/api/tests/services/kb/test_platform_ingestion.py

"""Platform processing preserves withdrawal, versions, and durable provider usage."""

from pathlib import Path
from uuid import uuid4

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from sqlalchemy import delete, select

from core.database import maintenance_async_db_session
from core.exceptions.auth import AuthorizationError
from core.settings import settings
from models.ai_usage_event import AIUsageEvent
from models.jobs import Job
from models.kb import KBChunk, KBDocument
from services.kb.embed_platform_chunks import embed_platform_chunks
from services.kb.ingest_platform_document import ingest_platform_document
from services.kb.platform_job_utils import require_platform_job_actor
from tests.factories import build_user
from tests.services.kb.test_annotation import _user_prompt
from tests.support.embeddings import RecordingProvider

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def platform_job(committed_db_session_factory, monkeypatch):
    email = f"knowledge-operator-{uuid4()}@example.com"
    monkeypatch.setattr(settings, "SUPER_ADMIN_EMAILS", email)
    async with maintenance_async_db_session() as db:
        actor = build_user(email=email)
        db.add(actor)
        await db.flush()
        version = str(uuid4())
        document = KBDocument(
            scope="platform",
            workspace_id=None,
            title="Shared guide",
            source_type="manual",
            content_md="Shared operational guidance for every team.",
            content_hash="",
            annotation_enabled=False,
            created_by_user_id=actor.id,
            meta={"ingestion_version": version},
        )
        db.add(document)
        await db.flush()
        job = Job(
            kind="kb.platform_ingest_document",
            subject_type="kb_document",
            subject_id=document.id,
            concurrency_user_id=actor.id,
            initiated_by_user_id=actor.id,
            payload={"version": version},
            content_hash="test",
        )
    yield job
    async with maintenance_async_db_session() as db:
        await db.execute(delete(Job).where(Job.subject_id == job.subject_id))
        await db.execute(delete(KBDocument).where(KBDocument.id == job.subject_id))
        await db.execute(delete(AIUsageEvent).where(AIUsageEvent.user_id == actor.id))
        await db.delete(await db.get(type(actor), actor.id))


async def test_ingestion_retry_is_unpublished_and_embeddings_meter_once(platform_job):
    await ingest_platform_document(platform_job)
    await ingest_platform_document(platform_job)
    provider = RecordingProvider()
    await embed_platform_chunks(platform_job, provider=provider)
    await embed_platform_chunks(platform_job, provider=provider)
    async with maintenance_async_db_session() as db:
        document = await db.get(KBDocument, platform_job.subject_id)
        chunks = list(
            (await db.scalars(select(KBChunk).where(KBChunk.document_id == document.id))).all()
        )
        assert len(chunks) == document.chunk_count == 1
        assert document.status == "ready"
        assert not document.is_published
        assert not chunks[0].is_published
        assert chunks[0].scope == "platform" and chunks[0].workspace_id is None
        usage = list(
            (
                await db.scalars(
                    select(AIUsageEvent).where(
                        AIUsageEvent.user_id == platform_job.initiated_by_user_id
                    )
                )
            ).all()
        )
        assert len(usage) == 1
        assert usage[0].scope == "platform" and usage[0].workspace_id is None
        assert usage[0].input_tokens == 3
        assert provider.call_sizes == [1]


async def test_reprocessing_attributes_both_usage_purposes_to_initiating_admin(
    platform_job, monkeypatch
):
    from models.audit_event import AuditEvent
    from models.user import User
    from services.kb.platform import reprocess_document
    from tests.support.requests import build_test_request

    await ingest_platform_document(platform_job)
    async with maintenance_async_db_session() as db:
        actor = build_user(email=f"reprocessing-admin-{uuid4()}@example.com")
        db.add(actor)
        await db.flush()
        document = await db.get(KBDocument, platform_job.subject_id)
        document.annotation_enabled = True
        creator_id = document.created_by_user_id
        creator = await db.get(User, creator_id)
        creator.is_active = False
    monkeypatch.setattr(settings, "SUPER_ADMIN_EMAILS", actor.email)

    async def respond(messages, info):
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, {"context": "Shared guidance"})]
        )

    try:
        async with maintenance_async_db_session() as db:
            reviewed = await reprocess_document(
                db,
                actor=actor,
                request=build_test_request(),
                document_id=platform_job.subject_id,
            )
        async with maintenance_async_db_session() as db:
            ingestion_job = await db.scalar(
                select(Job).where(
                    Job.subject_id == platform_job.subject_id,
                    Job.kind == "kb.platform_ingest_document",
                    Job.payload["version"].astext == reviewed.meta["ingestion_version"],
                )
            )
        assert ingestion_job.initiated_by_user_id == actor.id
        await ingest_platform_document(ingestion_job, annotation_model=FunctionModel(respond))
        async with maintenance_async_db_session() as db:
            embedding_job = await db.scalar(
                select(Job).where(
                    Job.subject_id == platform_job.subject_id,
                    Job.kind == "kb.platform_embed_chunks",
                    Job.payload["version"].astext == reviewed.meta["ingestion_version"],
                )
            )
        await embed_platform_chunks(embedding_job, provider=RecordingProvider())
        async with maintenance_async_db_session() as db:
            usage = list(
                (
                    await db.scalars(
                        select(AIUsageEvent).where(AIUsageEvent.user_id.in_([creator_id, actor.id]))
                    )
                ).all()
            )
            assert len(usage) == 2
            assert {row.purpose for row in usage} == {"kb_annotation", "embedding_kb_ingest"}
            assert all(row.user_id == actor.id for row in usage)
            assert all(row.scope == "platform" and row.workspace_id is None for row in usage)
            document = await db.get(KBDocument, platform_job.subject_id)
            assert document.created_by_user_id == creator_id
            assert document.meta["embedding_status"] == "ready"
    finally:
        async with maintenance_async_db_session() as db:
            await db.execute(delete(AIUsageEvent).where(AIUsageEvent.user_id == actor.id))
            await db.execute(delete(AuditEvent).where(AuditEvent.actor_user_id == actor.id))
            await db.execute(delete(Job).where(Job.initiated_by_user_id == actor.id))
            await db.delete(await db.get(User, actor.id))


async def test_hostile_annotation_has_no_tools_and_stale_output_retains_usage(platform_job):
    hostile = (Path(__file__).with_name("fixtures") / "hostile_annotation.md").read_text()
    async with maintenance_async_db_session() as db:
        document = await db.get(KBDocument, platform_job.subject_id)
        document.content_md = hostile
        document.annotation_enabled = True

    async def respond(messages, info):
        assert info.function_tools == []
        assert "untrusted DATA" in _user_prompt(messages)
        assert hostile in _user_prompt(messages)
        async with maintenance_async_db_session() as db:
            document = await db.get(KBDocument, platform_job.subject_id)
            document.deleted = True
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, {"context": "Reference guidance"})]
        )

    await ingest_platform_document(platform_job, annotation_model=FunctionModel(respond))
    async with maintenance_async_db_session() as db:
        document = await db.get(KBDocument, platform_job.subject_id)
        assert document.deleted and not document.is_published
        assert (
            list(
                (await db.scalars(select(KBChunk).where(KBChunk.document_id == document.id))).all()
            )
            == []
        )
        usage = list(
            (
                await db.scalars(
                    select(AIUsageEvent).where(
                        AIUsageEvent.user_id == platform_job.initiated_by_user_id
                    )
                )
            ).all()
        )
        assert usage and all(row.scope == "platform" and row.workspace_id is None for row in usage)


async def test_stale_embedding_output_is_discarded_but_usage_survives(platform_job):
    await ingest_platform_document(platform_job)

    class WithdrawingProvider(RecordingProvider):
        async def embed_texts(self, *args, **kwargs):
            result = await super().embed_texts(*args, **kwargs)
            async with maintenance_async_db_session() as db:
                document = await db.get(KBDocument, platform_job.subject_id)
                document.meta = {"ingestion_version": str(uuid4())}
                document.status = "error"
            return result

    await embed_platform_chunks(platform_job, provider=WithdrawingProvider())
    async with maintenance_async_db_session() as db:
        document = await db.get(KBDocument, platform_job.subject_id)
        chunk = await db.scalar(select(KBChunk).where(KBChunk.document_id == document.id))
        assert chunk.embedding is None
        assert document.status == "error" and not document.is_published
        usage = await db.scalar(
            select(AIUsageEvent).where(AIUsageEvent.user_id == platform_job.initiated_by_user_id)
        )
        assert usage.scope == "platform" and usage.input_tokens == 3


@pytest.mark.parametrize("concurrent_change", ["remove_chunk", "embed_chunk"])
async def test_embedding_rechecks_complete_batch_and_collection_after_provider_call(
    platform_job, monkeypatch, concurrent_change
):
    from services.embeddings.domain import EmbeddingConfigurationError

    monkeypatch.setattr(settings, "KB_CHUNK_TARGET_TOKENS", 40)
    monkeypatch.setattr(settings, "KB_CHUNK_MAX_TOKENS", 50)
    monkeypatch.setattr(settings, "KB_CHUNK_OVERLAP_TOKENS", 0)
    async with maintenance_async_db_session() as db:
        document = await db.get(KBDocument, platform_job.subject_id)
        document.content_md = "Shared platform guidance. " * 40
    await ingest_platform_document(platform_job)

    class ConcurrentProvider(RecordingProvider):
        async def embed_texts(self, *args, **kwargs):
            result = await super().embed_texts(*args, **kwargs)
            async with maintenance_async_db_session() as db:
                chunk = await db.scalar(
                    select(KBChunk)
                    .where(KBChunk.document_id == platform_job.subject_id)
                    .order_by(KBChunk.chunk_index.desc())
                    .limit(1)
                )
                if concurrent_change == "remove_chunk":
                    await db.delete(chunk)
                else:
                    chunk.embedding = [1.0] * result.dimensions
                    chunk.embedding_provider = result.provider
                    chunk.embedding_model = "different-model"
                    chunk.embedding_dims = result.dimensions
            return result

    provider = ConcurrentProvider()
    if concurrent_change == "embed_chunk":
        with pytest.raises(EmbeddingConfigurationError, match="does not match"):
            await embed_platform_chunks(platform_job, provider=provider)
    else:
        await embed_platform_chunks(platform_job, provider=provider)
    async with maintenance_async_db_session() as db:
        chunks = list(
            (
                await db.scalars(
                    select(KBChunk)
                    .where(KBChunk.document_id == platform_job.subject_id)
                    .order_by(KBChunk.chunk_index)
                )
            ).all()
        )
        assert len(chunks) > 1
        assert chunks[0].embedding is None
        assert all(chunk.embedding_model in {None, "different-model"} for chunk in chunks)
        usage = await db.scalar(
            select(AIUsageEvent).where(AIUsageEvent.user_id == platform_job.initiated_by_user_id)
        )
        assert usage.scope == "platform" and usage.input_tokens == provider.call_sizes[0] * 3


async def test_workspace_job_cannot_enter_platform_processing(platform_job):
    platform_job.workspace_id = uuid4()
    async with maintenance_async_db_session() as db:
        with pytest.raises(AuthorizationError, match="actor-owned"):
            await require_platform_job_actor(db, platform_job)


async def test_embedding_partial_failure_retry_keeps_chunks_and_all_usage(platform_job):
    from services.embeddings.domain import EmbeddingProviderPartialUsageError

    await ingest_platform_document(platform_job)

    class FailingProvider(RecordingProvider):
        async def embed_texts(self, *args, **kwargs):
            raise EmbeddingProviderPartialUsageError(
                "Provider interrupted", input_tokens=7, requests=1
            )

    with pytest.raises(EmbeddingProviderPartialUsageError):
        await embed_platform_chunks(platform_job, provider=FailingProvider())
    async with maintenance_async_db_session() as db:
        document = await db.get(KBDocument, platform_job.subject_id)
        assert document.status == "ready" and not document.is_published
        assert document.meta["embedding_status"] == "error"
    await embed_platform_chunks(platform_job, provider=RecordingProvider())
    async with maintenance_async_db_session() as db:
        document = await db.get(KBDocument, platform_job.subject_id)
        chunks = list(
            (await db.scalars(select(KBChunk).where(KBChunk.document_id == document.id))).all()
        )
        assert len(chunks) == document.chunk_count == 1
        assert chunks[0].embedding is not None and not chunks[0].is_published
        assert document.meta["embedding_status"] == "ready"
        rows = list(
            (
                await db.scalars(
                    select(AIUsageEvent).where(
                        AIUsageEvent.user_id == platform_job.initiated_by_user_id
                    )
                )
            ).all()
        )
        assert len(rows) == 2 and sum(row.input_tokens for row in rows) == 10


async def test_annotation_failure_retry_keeps_durable_usage_and_atomic_chunks(
    platform_job, monkeypatch
):
    monkeypatch.setattr(settings, "KB_CHUNK_TARGET_TOKENS", 40)
    monkeypatch.setattr(settings, "KB_CHUNK_MAX_TOKENS", 50)
    monkeypatch.setattr(settings, "KB_CHUNK_OVERLAP_TOKENS", 0)
    async with maintenance_async_db_session() as db:
        document = await db.get(KBDocument, platform_job.subject_id)
        document.annotation_enabled = True
        document.content_md = "Shared platform guidance. " * 40

    calls = 0

    async def fail(messages, info):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("Annotation interrupted")
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, {"context": "Shared guidance"})]
        )

    with pytest.raises(RuntimeError, match="Annotation interrupted"):
        await ingest_platform_document(platform_job, annotation_model=FunctionModel(fail))
    async with maintenance_async_db_session() as db:
        document = await db.get(KBDocument, platform_job.subject_id)
        assert document.status == "error" and not document.is_published
        assert document.chunk_count == 0

    async def respond(messages, info):
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, {"context": "Shared guidance"})]
        )

    await ingest_platform_document(platform_job, annotation_model=FunctionModel(respond))
    async with maintenance_async_db_session() as db:
        document = await db.get(KBDocument, platform_job.subject_id)
        chunks = list(
            (await db.scalars(select(KBChunk).where(KBChunk.document_id == document.id))).all()
        )
        assert len(chunks) == document.chunk_count and len(chunks) > 1
        assert document.status == "ready" and not document.is_published
        rows = list(
            (
                await db.scalars(
                    select(AIUsageEvent).where(
                        AIUsageEvent.user_id == platform_job.initiated_by_user_id
                    )
                )
            ).all()
        )
        assert len(rows) == len(chunks) + 1 and all(row.scope == "platform" for row in rows)


async def test_upload_ingestion_reads_pinned_platform_storage(platform_job, monkeypatch, tmp_path):
    from models.files import File
    from services.storage.domain import StorageBucket, make_storage_object_ref
    from services.storage.factory import get_storage_provider
    from tests.factories import build_file, build_file_revision, build_workspace
    from tests.support.storage import reset_storage_provider_cache

    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    reset_storage_provider_cache()
    async with maintenance_async_db_session() as db:
        file = build_file(
            workspace=build_workspace(),
            scope="platform",
            workspace_id=None,
            name="guide.txt",
            content_type="text/plain",
            extension=".txt",
        )
        revision = build_file_revision(file)
        db.add(file)
        await db.flush()
        db.add(revision)
        await db.flush()
        document = await db.get(KBDocument, platform_job.subject_id)
        document.source_type = "upload"
        document.file_revision_id = revision.id
        document.content_md = None
    try:
        await get_storage_provider().put_object(
            make_storage_object_ref(StorageBucket.PLATFORM_PRIVATE, revision.object_key),
            b"Pinned platform upload guidance",
            content_type="text/plain",
        )
        await ingest_platform_document(platform_job)
        async with maintenance_async_db_session() as db:
            document = await db.get(KBDocument, platform_job.subject_id)
            assert document.content_md == "Pinned platform upload guidance"
            assert document.file_revision_id == revision.id
            assert document.status == "ready" and not document.is_published
    finally:
        async with maintenance_async_db_session() as db:
            document = await db.get(KBDocument, platform_job.subject_id)
            document.file_revision_id = None
            await db.flush()
            await db.execute(delete(File).where(File.id == file.id))
        reset_storage_provider_cache()
