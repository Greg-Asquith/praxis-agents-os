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


@pytest.mark.parametrize("concurrent_change", ["embed_chunk"])
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
