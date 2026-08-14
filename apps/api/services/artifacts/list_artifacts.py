# apps/api/services/artifacts/list_artifacts.py

"""List workspace artifacts."""

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from models.artifacts import Artifact, ArtifactRevision
from services.artifacts.schemas import ArtifactListResponse
from services.artifacts.utils import artifact_to_summary


async def list_artifacts(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    limit: int,
    offset: int,
    conversation_id: UUID | None = None,
    search: str | None = None,
    sort_by: str = "updated_at",
    sort_direction: str = "desc",
) -> ArtifactListResponse:
    filters = [
        Artifact.workspace_id == workspace_id,
        Artifact.deleted.is_(False),
    ]
    if conversation_id is not None:
        filters.append(Artifact.conversation_id == conversation_id)
    if search:
        escaped = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        filters.append(
            or_(
                Artifact.title.ilike(pattern, escape="\\"),
                Artifact.artifact_type.ilike(pattern, escape="\\"),
            )
        )

    revision_counts = (
        select(
            ArtifactRevision.artifact_id.label("artifact_id"),
            func.count(ArtifactRevision.id).label("version_count"),
        )
        .where(ArtifactRevision.workspace_id == workspace_id)
        .group_by(ArtifactRevision.artifact_id)
        .subquery()
    )
    version_count = func.coalesce(revision_counts.c.version_count, 0)
    sort_columns = {
        "artifact_type": Artifact.artifact_type,
        "title": Artifact.title,
        "updated_at": Artifact.updated_at,
        "version_count": version_count,
    }
    sort_column = sort_columns.get(sort_by)
    if sort_column is None:
        raise AppValidationError("Unknown artifact sort field", field="sort_by")
    if sort_direction not in {"asc", "desc"}:
        raise AppValidationError("Unknown artifact sort direction", field="sort_direction")

    total = int(await db.scalar(select(func.count()).select_from(Artifact).where(*filters)) or 0)
    order = sort_column.asc() if sort_direction == "asc" else sort_column.desc()
    id_order = Artifact.id.asc() if sort_direction == "asc" else Artifact.id.desc()
    rows = (
        await db.execute(
            select(Artifact, version_count)
            .outerjoin(revision_counts, revision_counts.c.artifact_id == Artifact.id)
            .where(*filters)
            .order_by(order, id_order)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return ArtifactListResponse(
        items=[
            artifact_to_summary(artifact, version_count=int(revision_count))
            for artifact, revision_count in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
