# apps/api/services/kb/platform_job_utils.py

"""Authority and version checks for platform knowledge processing."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import SESSION_MAINTENANCE_KEY
from core.dependencies import require_super_admin_user
from core.exceptions.auth import AuthorizationError
from models.jobs import Job
from models.kb import KBDocument
from models.user import User


async def require_platform_job_actor(db: AsyncSession, job: Job) -> None:
    """Validates actor ownership before opening maintenance access."""
    if (
        job.workspace_id is not None
        or job.concurrency_user_id is None
        or job.concurrency_user_id != job.initiated_by_user_id
        or job.subject_type != "kb_document"
        or job.subject_id is None
        or not isinstance(job.payload, dict)
        or not isinstance(job.payload.get("version"), str)
    ):
        raise AuthorizationError("Platform knowledge requires an actor-owned versioned job")
    try:
        UUID(job.payload["version"])
    except ValueError as exc:
        raise AuthorizationError("Platform knowledge requires a valid content version") from exc
    actor = await db.get(User, job.initiated_by_user_id, populate_existing=True)
    if actor is None or actor.deleted or not actor.is_active:
        raise AuthorizationError("Platform knowledge requires an active super admin")
    require_super_admin_user(actor)


async def load_platform_job_document(db: AsyncSession, job: Job) -> KBDocument | None:
    """Locks the exact unpublished version before accepting processing output."""
    if not db.info.get(SESSION_MAINTENANCE_KEY):
        raise AuthorizationError("Platform knowledge requires a maintenance session")
    await require_platform_job_actor(db, job)
    return await db.scalar(
        select(KBDocument)
        .where(
            KBDocument.id == job.subject_id,
            KBDocument.scope == "platform",
            KBDocument.workspace_id.is_(None),
            KBDocument.deleted.is_(False),
            KBDocument.is_published.is_(False),
            KBDocument.meta["ingestion_version"].astext == job.payload["version"],
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
