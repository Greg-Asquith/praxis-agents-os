# apps/api/tests/factories/artifacts.py

"""Artifact model factories for tests."""

from uuid import UUID, uuid4

from models.artifacts import Artifact, ArtifactRevision
from models.workspace import Workspace
from services.artifacts.utils import artifact_revision_object_key


def build_artifact(
    *,
    workspace: Workspace,
    artifact_id: UUID | None = None,
    current_version_id: UUID | None = None,
    **overrides,
) -> Artifact:
    selected_artifact_id = artifact_id or uuid4()
    defaults = {
        "id": selected_artifact_id,
        "workspace_id": workspace.id,
        "current_version_id": current_version_id,
        "artifact_type": "html",
        "title": "Test artifact",
    }
    defaults.update(overrides)
    return Artifact(**defaults)


def build_artifact_revision(
    *,
    artifact: Artifact,
    revision_id: UUID | None = None,
    revision_number: int = 1,
    revision_kind: str = "create",
    created_by_user_id: UUID | None = None,
    created_by_agent_id: UUID | None = None,
    created_by_system: bool | None = None,
    **overrides,
) -> ArtifactRevision:
    selected_revision_id = revision_id or uuid4()
    extension = {
        "html": ".html",
        "markdown": ".md",
        "mermaid": ".mmd",
        "csv": ".csv",
        "image-ref": ".png",
    }[artifact.artifact_type]
    defaults = {
        "id": selected_revision_id,
        "artifact_id": artifact.id,
        "workspace_id": artifact.workspace_id,
        "revision_number": revision_number,
        "revision_kind": revision_kind,
        "content_type": "text/html",
        "extension": extension,
        "size_bytes": 12,
        "content_hash": "a" * 64,
        "object_key": artifact_revision_object_key(
            artifact.workspace_id,
            artifact.id,
            selected_revision_id,
            extension,
        ),
        "created_by_user_id": created_by_user_id,
        "created_by_agent_id": created_by_agent_id,
        "created_by_system": bool(created_by_system),
    }
    if created_by_user_id is None and created_by_agent_id is None and created_by_system is None:
        defaults["created_by_system"] = True
    defaults.update(overrides)
    return ArtifactRevision(**defaults)
