# apps/api/services/artifacts/create_artifact.py

"""Create an artifact and its first immutable revision."""

from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import Agent
from models.agent_run import AgentRun
from models.artifacts import Artifact, ArtifactRevision
from models.conversation import Conversation
from models.workspace import Workspace
from services.artifacts.domain import ARTIFACT_EXTENSIONS, ARTIFACT_STORAGE_CONTENT_TYPES
from services.artifacts.utils import (
    ArtifactRevisionActor,
    artifact_content_hash,
    artifact_revision_object_key,
    artifact_revision_ref,
    validate_artifact_content,
)
from services.storage.factory import get_storage_provider
from services.storage.utils import put_new_object_with_cleanup


async def create_artifact(
    db: AsyncSession,
    *,
    workspace: Workspace,
    title: str,
    artifact_type: str,
    content: str,
    agent: Agent | None = None,
    conversation: Conversation | None = None,
    run: AgentRun | None = None,
    actor_user_id: UUID | None = None,
) -> tuple[Artifact, ArtifactRevision]:
    data = validate_artifact_content(
        artifact_type=artifact_type,
        title=title,
        content=content,
    )
    actor = ArtifactRevisionActor(
        user_id=actor_user_id,
        agent_id=agent.id if agent is not None else None,
    )
    actor_columns = actor.columns()
    artifact_id = uuid4()
    extension = ARTIFACT_EXTENSIONS[artifact_type]
    artifact = Artifact(
        id=artifact_id,
        workspace_id=workspace.id,
        agent_id=agent.id if agent is not None else None,
        conversation_id=conversation.id if conversation is not None else None,
        run_id=run.id if run is not None else None,
        current_version_id=None,
        artifact_type=artifact_type,
        title=title.strip(),
    )
    db.add(artifact)
    await db.flush()

    revision_id = uuid4()
    object_key = artifact_revision_object_key(
        workspace.id,
        artifact.id,
        revision_id,
        extension,
    )
    revision = ArtifactRevision(
        id=revision_id,
        artifact_id=artifact.id,
        workspace_id=workspace.id,
        revision_number=1,
        revision_kind="create",
        content_type=ARTIFACT_STORAGE_CONTENT_TYPES[artifact_type],
        extension=extension,
        size_bytes=len(data),
        content_hash=artifact_content_hash(data),
        object_key=object_key,
        **actor_columns,
    )
    db.add(revision)
    await db.flush()
    artifact.current_version_id = revision.id
    await db.flush()
    await db.refresh(artifact)
    await put_new_object_with_cleanup(
        get_storage_provider(),
        artifact_revision_ref(object_key),
        data,
        content_type=ARTIFACT_STORAGE_CONTENT_TYPES[artifact_type],
    )
    return artifact, revision
