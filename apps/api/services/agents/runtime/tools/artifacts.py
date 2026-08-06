# apps/api/services/agents/runtime/tools/artifacts.py

"""Versioned artifact runtime tools."""

from typing import Literal

from pydantic_ai import ModelRetry, RunContext

from core.exceptions.general import AppValidationError, NotFoundError
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.entity_references.domain import ArtifactReference
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_EXTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_EXTERNAL_WRITE,
    TOOL_POLICY_AUTO,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.agents.runtime.tools.registry import runtime_tool
from services.artifacts import (
    create_artifact as create_artifact_service,
    update_artifact as update_artifact_service,
)
from services.artifacts.schemas import ArtifactToolResult


@runtime_tool(
    name="create_artifact",
    provider="core",
    label="Create artifact",
    description=(
        "Create a titled, versioned artifact (html, markdown, mermaid, or csv) "
        "rendered for the user to view and revise. Use for reports and documents "
        "meant to be presented to the user, not for short chat answers or "
        "stored workspace data (use write_file for those)."
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
        reference=ArtifactReference(
            entity_id=artifact.id,
            label=artifact.title,
            description=f"{artifact.artifact_type.title()} artifact",
        ),
    ).model_dump()


@runtime_tool(
    name="update_artifact",
    provider="core",
    label="Update artifact",
    description="Append a new immutable version to an existing artifact.",
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
        reference=ArtifactReference(
            entity_id=artifact.id,
            label=artifact.title,
            description=f"{artifact.artifact_type.title()} artifact",
        ),
    ).model_dump()
