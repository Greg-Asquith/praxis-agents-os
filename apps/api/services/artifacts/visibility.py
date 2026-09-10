# apps/api/services/artifacts/visibility.py

"""Read predicates for local and published platform Artifacts."""

from uuid import UUID

from sqlalchemy import and_, false, or_, select
from sqlalchemy.sql.elements import ColumnElement

from models.artifacts import Artifact, ArtifactRevision


def visible_artifact_filter(workspace_id: UUID | None) -> ColumnElement[bool]:
    """Returns visible parents, excluding drafts, withdrawals, and deletions."""
    if workspace_id is None:
        return false()
    return and_(
        Artifact.deleted.is_(False),
        or_(
            and_(Artifact.scope == "workspace", Artifact.workspace_id == workspace_id),
            and_(
                Artifact.scope == "platform",
                Artifact.workspace_id.is_(None),
                Artifact.is_published.is_(True),
            ),
        ),
    )


def visible_artifact_revision_filter(workspace_id: UUID | None) -> ColumnElement[bool]:
    """Requires a visible parent, matching ownership, and a reviewed revision."""
    return (
        select(Artifact.id)
        .where(
            Artifact.id == ArtifactRevision.artifact_id,
            visible_artifact_filter(workspace_id),
            ArtifactRevision.scope == Artifact.scope,
            ArtifactRevision.workspace_id.is_not_distinct_from(Artifact.workspace_id),
            or_(Artifact.scope == "workspace", ArtifactRevision.is_published.is_(True)),
        )
        .correlate(ArtifactRevision)
        .exists()
    )
