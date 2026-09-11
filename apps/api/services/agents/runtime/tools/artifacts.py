# apps/api/services/agents/runtime/tools/artifacts.py

"""Versioned artifact runtime tools."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from core.exceptions.auth import AuthorizationError
from core.exceptions.general import AppValidationError, ConflictError, NotFoundError
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
from services.agents.runtime.untrusted import UntrustedNode
from services.artifacts import (
    create_artifact as create_artifact_service,
    get_artifact as get_artifact_service,
    get_version_content as get_version_content_service,
    list_artifacts as list_artifacts_service,
    update_artifact as update_artifact_service,
)
from services.artifacts.platform.schemas import PlatformArtifactUpdateRequest
from services.artifacts.platform.update_artifact import (
    update_artifact as update_platform_artifact,
)
from services.artifacts.schemas import (
    ArtifactListToolResult,
    ArtifactReadToolResult,
    ArtifactToolResult,
    ArtifactToolSummary,
)
from services.artifacts.utils import get_artifact_row
from utils.content import ContentScope


def _artifact_reference(
    *,
    artifact_id: UUID,
    title: str,
    artifact_type: str,
    scope: ContentScope = ContentScope.WORKSPACE,
) -> ArtifactReference:
    return ArtifactReference(
        entity_id=artifact_id,
        label=title,
        description=f"{artifact_type.title()} artifact",
        scope_label=scope.title(),
    )


@runtime_tool(
    name="list_artifacts",
    provider="core",
    label="List artifacts",
    code_eligible=False,
    description=(
        "List recent workspace and published platform-wide artifacts before creating a deliverable. "
        "Search matches artifact titles and types. Edits to platform-wide artifacts affect every workspace."
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
            scope=artifact.scope,
            current_version_id=artifact.current_version_id,
            reference=_artifact_reference(
                artifact_id=artifact.id,
                title=artifact.title,
                artifact_type=artifact.artifact_type,
                scope=artifact.scope,
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
        "Read the current workspace version or published platform-wide version of an artifact. "
        "Use the returned version_id as expected_current_version_id when updating a platform-wide "
        "artifact. Binary images return metadata only and remain viewable in the Artifacts UI."
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
    artifact_id: Annotated[
        ArtifactReference, Field(description="Artifact reference returned by list_artifacts.")
    ],
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
        scope=artifact.scope,
        version_id=artifact.current_version_id,
        reference=_artifact_reference(
            artifact_id=artifact.id,
            title=artifact.title,
            artifact_type=artifact.artifact_type,
            scope=artifact.scope,
        ),
        title=artifact.title,
        artifact_type=artifact.artifact_type,
        revision_number=revision_number,
        updated_at=artifact.updated_at,
        content=(
            UntrustedNode(
                source_kind="artifact",
                source_ref=f"artifact:{artifact.id}/version:{artifact.current_version_id}",
                content=content,
            )
            if content is not None and artifact.scope == ContentScope.PLATFORM
            else content
        ),
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
) -> dict[str, object]:
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
        "Append an immutable version to a workspace or published platform-wide artifact. Read it "
        "first. Platform updates require expected_current_version_id from that read and the "
        "requesting user's editor permission; the saved version becomes visible to every "
        "workspace immediately. Create a workspace artifact for client-specific work."
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
        approval_prompt=(
            "Review this artifact version before saving. "
            "A platform artifact becomes visible to every workspace immediately."
        ),
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
    expected_current_version_id: Annotated[
        UUID | None,
        Field(description="The version_id returned by read_artifact. Required for platform edits."),
    ] = None,
) -> dict[str, object]:
    try:
        target = await get_artifact_row(
            ctx.deps.db,
            workspace_id=ctx.deps.workspace.id,
            artifact_id=artifact_id.entity_id,
        )
        if target.scope == ContentScope.PLATFORM:
            # Concurrent withdrawal can hide this row from tenant retry recovery.
            ctx.deps.db.expunge(target)
            if expected_current_version_id is None:
                raise ModelRetry(
                    "Read the platform artifact and supply its expected_current_version_id."
                )
            artifact = await update_platform_artifact(
                ctx.deps.db,
                request=None,
                actor=ctx.deps.user,
                workspace=ctx.deps.workspace,
                artifact_id=artifact_id.entity_id,
                payload=PlatformArtifactUpdateRequest(
                    content=content,
                    title=title,
                    expected_current_version_id=expected_current_version_id,
                ),
                published_only=True,
            )
            version_id = artifact.current_version_id
        else:
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
            version_id = revision.id
    except NotFoundError as exc:
        raise ModelRetry("Unknown artifact id") from exc
    except (AppValidationError, AuthorizationError, ConflictError) as exc:
        raise ModelRetry(exc.message) from exc
    return ArtifactToolResult(
        artifact_id=str(artifact.id),
        version_id=str(version_id),
        title=artifact.title,
        artifact_type=artifact.artifact_type,
        reference=_artifact_reference(
            artifact_id=artifact.id,
            title=artifact.title,
            artifact_type=artifact.artifact_type,
            scope=artifact.scope,
        ),
    ).model_dump()
