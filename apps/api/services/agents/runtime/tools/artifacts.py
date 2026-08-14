# apps/api/services/agents/runtime/tools/artifacts.py

"""Versioned artifact runtime tools."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from core.exceptions.general import AppValidationError, NotFoundError
from core.settings import settings
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.entity_references.domain import ArtifactReference
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    TOOL_EFFECT_SCOPE_EXTERNAL,
    TOOL_EFFECT_SCOPE_INTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_EXTERNAL_WRITE,
    TOOL_EGRESS_NONE,
    TOOL_POLICY_AUTO,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.agents.runtime.tools.registry import runtime_tool
from services.artifacts import (
    create_artifact as create_artifact_service,
    get_artifact as get_artifact_service,
    get_version_content as get_version_content_service,
    list_artifacts as list_artifacts_service,
    update_artifact as update_artifact_service,
)
from services.artifacts.schemas import (
    ArtifactListToolResult,
    ArtifactReadToolResult,
    ArtifactToolResult,
    ArtifactToolSummary,
)


def _artifact_reference(*, artifact_id: UUID, title: str, artifact_type: str) -> ArtifactReference:
    return ArtifactReference(
        entity_id=artifact_id,
        label=title,
        description=f"{artifact_type.title()} artifact",
    )


@runtime_tool(
    name="list_artifacts",
    provider="core",
    label="List artifacts",
    code_eligible=False,
    description=(
        "List recent workspace artifacts so you can find an existing deliverable before "
        "creating or updating one. Search matches artifact titles and types."
    ),
    effect=TOOL_EFFECT_READ,
    effect_scope=TOOL_EFFECT_SCOPE_INTERNAL,
    egress=TOOL_EGRESS_NONE,
    default_policy=TOOL_POLICY_AUTO,
    supports_auto=True,
    takes_ctx=True,
    timeout=15,
    output_model=ArtifactListToolResult,
    configurable=False,
    auto_mount=True,
    presentation=ToolPresentation(
        icon="files",
        running_label="Listing artifacts",
        completed_label="Artifacts listed",
        failed_label="Couldn't list artifacts",
        arg_fields=(ToolFieldPresentation(key="search", label="Search"),),
        result_fields=(ToolFieldPresentation(key="items", label="Artifacts", format="list"),),
    ),
)
async def list_artifacts(
    ctx: RunContext[RuntimeDeps],
    search: str | None = None,
    limit: Annotated[int, Field(ge=1, le=50)] = 20,
) -> dict[str, object]:
    result = await list_artifacts_service(
        ctx.deps.db,
        workspace_id=ctx.deps.workspace.id,
        search=search,
        limit=limit,
        offset=0,
        sort_by="updated_at",
        sort_direction="desc",
    )
    items = [
        ArtifactToolSummary(
            id=str(artifact.id),
            reference=_artifact_reference(
                artifact_id=artifact.id,
                title=artifact.title,
                artifact_type=artifact.artifact_type,
            ),
            title=artifact.title,
            artifact_type=artifact.artifact_type,
            version_count=artifact.version_count,
            updated_at=artifact.updated_at,
            conversation_id=artifact.conversation_id,
        )
        for artifact in result.items
    ]
    return ArtifactListToolResult(
        items=items,
        total=result.total,
        returned=len(items),
    ).model_dump(mode="json")


@runtime_tool(
    name="read_artifact",
    provider="core",
    label="Read artifact",
    code_eligible=False,
    description=(
        "Read the current version of a workspace artifact before revising it. Binary image "
        "artifacts return metadata only and remain viewable in the Artifacts UI."
    ),
    effect=TOOL_EFFECT_READ,
    effect_scope=TOOL_EFFECT_SCOPE_INTERNAL,
    egress=TOOL_EGRESS_NONE,
    default_policy=TOOL_POLICY_AUTO,
    supports_auto=True,
    takes_ctx=True,
    timeout=30,
    output_model=ArtifactReadToolResult,
    configurable=False,
    auto_mount=True,
    presentation=ToolPresentation(
        icon="file",
        running_label="Reading artifact",
        completed_label="Artifact read",
        failed_label="Couldn't read artifact",
        arg_fields=(
            ToolFieldPresentation(
                key="artifact_id",
                label="Artifact",
                format="entity",
                entity_kind="artifact",
            ),
        ),
    ),
)
async def read_artifact(
    ctx: RunContext[RuntimeDeps],
    artifact_id: ArtifactReference,
) -> dict[str, object]:
    try:
        artifact = await get_artifact_service(
            ctx.deps.db,
            workspace_id=ctx.deps.workspace.id,
            artifact_id=artifact_id.entity_id,
        )
        version = await get_version_content_service(
            ctx.deps.db,
            artifact=artifact,
            version_id=artifact.current_version_id,
        )
    except NotFoundError as exc:
        raise ModelRetry("Unknown artifact id") from exc

    revision_number = next(
        revision.revision_number
        for revision in artifact.versions
        if revision.id == artifact.current_version_id
    )
    content = version.content
    truncated = content is not None and len(content) > settings.ARTIFACT_READ_TOOL_MAX_CHARS
    if truncated:
        content = content[: settings.ARTIFACT_READ_TOOL_MAX_CHARS]
    return ArtifactReadToolResult(
        id=str(artifact.id),
        reference=_artifact_reference(
            artifact_id=artifact.id,
            title=artifact.title,
            artifact_type=artifact.artifact_type,
        ),
        title=artifact.title,
        artifact_type=artifact.artifact_type,
        revision_number=revision_number,
        updated_at=artifact.updated_at,
        content=content,
        truncated=truncated,
        size_bytes=version.size_bytes,
        content_type=version.content_type,
        note=(
            "Binary artifacts are viewable only in the Artifacts UI."
            if artifact.artifact_type == "image-ref"
            else None
        ),
    ).model_dump(mode="json")


@runtime_tool(
    name="create_artifact",
    provider="core",
    label="Create artifact",
    code_eligible=False,
    description=(
        "Create a titled, versioned artifact (html, markdown, mermaid, or csv) "
        "rendered for the user to view and revise. Use for reports and documents "
        "meant to be presented to the user, not for short chat answers or "
        "stored workspace data (use write_file for those). Check list_artifacts for "
        "an existing artifact covering this deliverable first; prefer update_artifact "
        "over creating a near-duplicate."
    ),
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_AUTO,
    supports_auto=True,
    takes_ctx=True,
    timeout=30,
    output_model=ArtifactToolResult,
    configurable=False,
    auto_mount=True,
    presentation=ToolPresentation(
        icon="file-plus",
        running_label="Creating artifact",
        completed_label="Artifact created",
        failed_label="Artifact creation failed",
        approval_title="Create artifact?",
        approval_prompt="Review this artifact before it is created.",
        approve_label="Create Artifact",
        arg_fields=(
            ToolFieldPresentation(key="title", label="Title", editable=True),
            ToolFieldPresentation(key="artifact_type", label="Type"),
            ToolFieldPresentation(
                key="content",
                label="Content",
                format="multiline",
                editable=True,
            ),
        ),
    ),
)
async def create_artifact(
    ctx: RunContext[RuntimeDeps],
    title: str,
    artifact_type: Literal["html", "markdown", "mermaid", "csv"],
    content: str,
) -> dict[str, str]:
    try:
        artifact, revision = await create_artifact_service(
            ctx.deps.db,
            workspace=ctx.deps.workspace,
            title=title,
            artifact_type=artifact_type,
            content=content,
            agent=ctx.deps.agent,
            conversation=ctx.deps.conversation,
            run=ctx.deps.run,
        )
    except AppValidationError as exc:
        raise ModelRetry(exc.message) from exc
    return ArtifactToolResult(
        artifact_id=str(artifact.id),
        version_id=str(revision.id),
        title=artifact.title,
        artifact_type=artifact.artifact_type,
        reference=_artifact_reference(
            artifact_id=artifact.id,
            title=artifact.title,
            artifact_type=artifact.artifact_type,
        ),
    ).model_dump()


@runtime_tool(
    name="update_artifact",
    provider="core",
    label="Update artifact",
    code_eligible=False,
    description=(
        "Append a new immutable version to any workspace artifact, including artifacts "
        "created in other conversations. Read its current version before replacing it."
    ),
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_AUTO,
    supports_auto=True,
    takes_ctx=True,
    timeout=30,
    output_model=ArtifactToolResult,
    configurable=False,
    auto_mount=True,
    presentation=ToolPresentation(
        icon="file",
        running_label="Updating artifact",
        completed_label="Artifact updated",
        failed_label="Artifact update failed",
        approval_title="Update artifact?",
        approval_prompt="Review this new artifact version before it is saved.",
        approve_label="Update Artifact",
        arg_fields=(
            ToolFieldPresentation(
                key="artifact_id",
                label="Artifact",
                format="entity",
                editable=True,
                entity_kind="artifact",
            ),
            ToolFieldPresentation(key="title", label="Title", editable=True),
            ToolFieldPresentation(
                key="content",
                label="Content",
                format="multiline",
                editable=True,
            ),
        ),
    ),
)
async def update_artifact(
    ctx: RunContext[RuntimeDeps],
    artifact_id: ArtifactReference,
    content: str,
    title: str | None = None,
) -> dict[str, str]:
    try:
        artifact, revision = await update_artifact_service(
            ctx.deps.db,
            workspace=ctx.deps.workspace,
            artifact_id=artifact_id.entity_id,
            content=content,
            title=title,
            agent=ctx.deps.agent,
            conversation=ctx.deps.conversation,
            run=ctx.deps.run,
        )
    except NotFoundError as exc:
        raise ModelRetry("Unknown artifact id") from exc
    except AppValidationError as exc:
        raise ModelRetry(exc.message) from exc
    return ArtifactToolResult(
        artifact_id=str(artifact.id),
        version_id=str(revision.id),
        title=artifact.title,
        artifact_type=artifact.artifact_type,
        reference=_artifact_reference(
            artifact_id=artifact.id,
            title=artifact.title,
            artifact_type=artifact.artifact_type,
        ),
    ).model_dump()
