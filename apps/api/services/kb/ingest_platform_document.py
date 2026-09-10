# apps/api/services/kb/ingest_platform_document.py

"""Materialises a reviewed platform source without publishing it."""

from uuid import uuid4

from pydantic_ai.models import Model
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import maintenance_async_db_session
from core.exceptions.general import AppValidationError
from core.settings import settings
from models.files import File, FileRevision
from models.jobs import Job
from models.kb import KBChunk
from services.files.contract import is_editable
from services.jobs.enqueue_job import enqueue_job
from services.jobs.utils import sanitize_error_message
from services.kb.annotation import annotate_chunks
from services.kb.chunking import build_kb_chunks
from services.kb.platform_job_utils import load_platform_job_document
from services.kb.utils import compute_markdown_hash
from services.kb.write_policy import enforce_platform_kb_write_policy, lock_and_find_kb_duplicate
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.factory import get_storage_provider
from utils.content import ContentScope


async def ingest_platform_document(job: Job, *, annotation_model: Model | None = None) -> None:
    """Stage annotations before atomically replacing lexical chunks."""
    try:
        async with maintenance_async_db_session() as db:
            document = await load_platform_job_document(db, job)
            if document is None:
                return
            if document.chunk_count > 0:
                document.status = "ready"
                document.processing_error = None
                await _queue_embeddings(db, job)
                return
            document.status = "processing"
            document.processing_error = None
            document.processing_attempts += 1
            object_key = None
            if document.source_type == "upload":
                revision = await db.scalar(
                    select(FileRevision)
                    .join(File, File.id == FileRevision.file_id)
                    .where(
                        FileRevision.id == document.file_revision_id,
                        FileRevision.scope == "platform",
                        File.scope == "platform",
                        File.deleted.is_(False),
                    )
                )
                if revision is None:
                    raise AppValidationError("Platform source revision is unavailable")
                object_key = revision.markdown_object_key
                if object_key is None and is_editable(revision.content_type):
                    object_key = revision.object_key
                if object_key is None:
                    raise AppValidationError("Platform source extraction is not ready")
            elif document.source_type != "manual":
                raise AppValidationError("Platform knowledge supports manual text and uploads")
            await db.flush()
            db.expunge(document)

        markdown = document.content_md or ""
        if object_key is not None:
            data = bytearray()
            source = make_storage_object_ref(StorageBucket.PLATFORM_PRIVATE, object_key)
            async for block in get_storage_provider().stream_object(source):
                if len(data) + len(block) > settings.KB_MAX_DOCUMENT_BYTES:
                    raise AppValidationError("Platform source exceeds the knowledge size limit")
                data.extend(block)
            markdown = data.decode("utf-8", errors="replace")
        document.content_md = markdown
        chunks = build_kb_chunks(document, markdown)
        if not chunks:
            raise AppValidationError("Knowledge-base document contains no readable content")
        for chunk in chunks:
            chunk.id = uuid4()
        async with maintenance_async_db_session() as db:
            enforce_platform_kb_write_policy(
                db, title=document.title, content_md=markdown, existing=document
            )
            if document.annotation_enabled:
                await annotate_chunks(
                    db,
                    document=document,
                    chunks=chunks,
                    model=annotation_model,
                    platform_user_id=job.initiated_by_user_id,
                )
        async with maintenance_async_db_session() as db:
            current = await load_platform_job_document(db, job)
            if current is None or current.chunk_count > 0:
                return
            content_hash = compute_markdown_hash(markdown)
            duplicate = await lock_and_find_kb_duplicate(
                db,
                workspace_id=None,
                scope=ContentScope.PLATFORM,
                content_hash=content_hash,
                is_private=False,
                existing_id=current.id,
            )
            enforce_platform_kb_write_policy(
                db, title=current.title, content_md=markdown, existing=current, duplicate=duplicate
            )
            await db.execute(delete(KBChunk).where(KBChunk.document_id == current.id))
            db.add_all(chunks)
            current.content_md = markdown
            current.content_hash = content_hash
            current.chunk_count = len(chunks)
            current.processing_error = None
            current.status = "ready"
            current.meta = {**current.meta, "embedding_status": "pending", "embedding_error": None}
            await _queue_embeddings(db, job)
    except Exception as exc:
        async with maintenance_async_db_session() as db:
            document = await load_platform_job_document(db, job)
            if document is not None:
                document.status = "error"
                document.processing_error = sanitize_error_message(str(exc) or type(exc).__name__)
        raise


async def _queue_embeddings(db: AsyncSession, job: Job) -> None:
    await enqueue_job(
        db,
        kind="kb.platform_embed_chunks",
        concurrency_user_id=job.concurrency_user_id,
        initiated_by_user_id=job.initiated_by_user_id,
        subject_type="kb_document",
        subject_id=job.subject_id,
        payload=job.payload,
    )
