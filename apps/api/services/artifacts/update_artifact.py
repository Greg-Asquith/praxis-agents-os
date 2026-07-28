# apps/api/services/artifacts/update_artifact.py

"""Append a new artifact revision."""

from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import Agent
from models.agent_run import AgentRun
from models.artifacts import Artifact, ArtifactRevision
from models.conversation import Conversation
from models.workspace import Workspace
from services.artifacts.domain import ARTIFACT_STORAGE_CONTENT_TYPES
from services.artifacts.utils import (
    ArtifactRevisionActor,
    artifact_content_hash,
    artifact_revision_object_key,
    artifact_revision_ref,
    get_artifact_revision,
    get_artifact_row,
    validate_artifact_content,
)
from services.storage.factory import get_storage_provider
from services.storage.utils import put_new_object_with_cleanup


async def update_artifact(
    db: AsyncSession,
    *,
    workspace: Workspace,
    artifact_id: UUID,
    content: str,
    title: str | None = None,
    agent: Agent | None = None,
    conversation: Conversation | None = None,
    run: AgentRun | None = None,
    actor_user_id: UUID | None = None,
) -> tuple[Artifact, ArtifactRevision]:
    artifact = await get_artifact_row(
        db,
        workspace_id=workspace.id,
        artifact_id=artifact_id,
        for_update=True,
    )
    resolved_title = title if title is not None else artifact.title
    data = validate_artifact_content(
        artifact_type=artifact.artifact_type,
        title=resolved_title,
        content=content,
    )
    actor_columns = ArtifactRevisionActor(
        user_id=actor_user_id,
        agent_id=agent.id if agent is not None else None,
    ).columns()
    if artifact.current_version_id is None:
        raise RuntimeError("Artifact has no current revision")
    current = await get_artifact_revision(
        db,
        artifact=artifact,
        version_id=artifact.current_version_id,
    )
    revision_id = uuid4()
    object_key = artifact_revision_object_key(
        workspace.id,
        artifact.id,
        revision_id,
        current.extension,
    )
    revision = ArtifactRevision(
        id=revision_id,
        artifact_id=artifact.id,
        workspace_id=workspace.id,
        revision_number=current.revision_number + 1,
        revision_kind="edit",
        content_type=ARTIFACT_STORAGE_CONTENT_TYPES[artifact.artifact_type],
        extension=current.extension,
        size_bytes=len(data),
        content_hash=artifact_content_hash(data),
        object_key=object_key,
        **actor_columns,
    )
    db.add(revision)
    await db.flush()
    artifact.current_version_id = revision.id
    artifact.title = resolved_title.strip()
    artifact.agent_id = agent.id if agent is not None else artifact.agent_id
    artifact.conversation_id = (
        conversation.id if conversation is not None else artifact.conversation_id
    )
    artifact.run_id = run.id if run is not None else artifact.run_id
    await db.flush()
    await db.refresh(artifact)
    await put_new_object_with_cleanup(
        get_storage_provider(),
        artifact_revision_ref(object_key),
        data,
        content_type=ARTIFACT_STORAGE_CONTENT_TYPES[artifact.artifact_type],
    )
    return artifact, revision
