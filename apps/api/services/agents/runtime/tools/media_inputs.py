# apps/api/services/agents/runtime/tools/media_inputs.py

"""Governed workspace media loading shared by runtime tools."""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.exceptions import ToolFailed
from pydantic_ai.messages import BinaryContent, UploadedFile, VideoUrl

from core.settings import settings
from models.files import FileRevision
from services.agents.models.domain import PROVIDER_GOOGLE
from services.agents.models.utils import is_provider_configured
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.entity_references.domain import FileReference, internal_entity_id
from services.agents.runtime.tools.files.utils import current_file_revision
from services.audit_events import AuditAction, AuditActorType, AuditResourceType
from services.audit_events.operations import safe_record_operation_audit_event
from services.files.contract import FileCategory
from services.files.utils import private_ref_from_key
from services.gemini_files import (
    GEMINI_FILES_MAX_BYTES,
    GeminiFile,
    GeminiFileError,
    delete_gemini_file,
    upload_gemini_file,
)
from services.storage.domain import StorageObjectRef
from services.storage.factory import get_storage_provider
from services.storage.workspace_buckets import workspace_id_for_ref

VIDEO_MEDIA_TYPES = frozenset({"video/mp4", "video/quicktime", "video/webm"})
# A cached upload must outlive the longest tool call that reads it.
_GEMINI_FILE_REUSE_MARGIN = timedelta(hours=1)

VideoResolution = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class WorkspaceMediaInput:
    """One governed current file revision prepared as model input."""

    content: BinaryContent
    file_id: UUID
    revision_id: UUID
    name: str


@dataclass(frozen=True)
class VideoInputOptions:
    """Server-chosen sampling for one video part; Gemini's defaults apply when unset."""

    fps: float | None = None
    start_seconds: float | None = None
    end_seconds: float | None = None
    resolution: VideoResolution | None = None

    def vendor_metadata(self) -> dict[str, Any] | None:
        """Returns Gemini's `video_metadata` fields plus the per-part media resolution."""
        metadata: dict[str, Any] = {}
        if self.fps is not None:
            metadata["fps"] = self.fps
        if self.start_seconds is not None:
            metadata["start_offset"] = f"{self.start_seconds:.3f}s"
        if self.end_seconds is not None:
            metadata["end_offset"] = f"{self.end_seconds:.3f}s"
        if self.resolution is not None:
            metadata["media_resolution"] = {"level": f"MEDIA_RESOLUTION_{self.resolution.upper()}"}
        return metadata or None


@dataclass(frozen=True)
class WorkspaceVideoInput:
    """One governed current video revision prepared as Google model input."""

    content: BinaryContent | VideoUrl | UploadedFile
    file_id: UUID
    revision_id: UUID
    name: str


@dataclass(frozen=True)
class _ResolvedWorkspaceMediaInput:
    """Validated revision metadata retained before object bytes are loaded."""

    file_id: UUID
    revision_id: UUID
    name: str
    object_key: str
    media_type: str
    size_bytes: int
    revision: FileRevision


async def load_workspace_media_input(
    ctx: RunContext[RuntimeDeps],
    file_reference: FileReference,
    *,
    category: FileCategory,
    allowed_media_types: Collection[str],
    tool_name: str,
    kind_label: str,
    max_bytes: int | None = None,
) -> WorkspaceMediaInput:
    """Load and validate one current workspace file revision as model media."""
    resolved = await _resolve_workspace_media_input(
        ctx,
        file_reference,
        category=category,
        allowed_media_types=allowed_media_types,
        tool_name=tool_name,
        kind_label=kind_label,
        max_bytes=max_bytes,
    )
    return await _load_workspace_media_input(
        resolved,
        tool_name=tool_name,
        kind_label=kind_label,
        max_bytes=max_bytes,
    )


async def _resolve_workspace_media_input(
    ctx: RunContext[RuntimeDeps],
    file_reference: FileReference,
    *,
    category: FileCategory,
    allowed_media_types: Collection[str],
    tool_name: str,
    kind_label: str,
    max_bytes: int | None,
) -> _ResolvedWorkspaceMediaInput:
    file, revision = await current_file_revision(ctx, internal_entity_id(file_reference))
    if file.category != category.value:
        article = "an" if kind_label[:1].lower() in "aeiou" else "a"
        raise ModelRetry(f"{tool_name} requires {article} {kind_label} file from workspace Files.")

    media_type = revision.content_type.split(";", 1)[0].strip().lower()
    if media_type not in allowed_media_types:
        raise ModelRetry(f"This {kind_label} format is not supported by {tool_name}.")
    if max_bytes is not None and revision.size_bytes > max_bytes:
        raise ModelRetry(
            f"This {kind_label} is too large for {tool_name}. Choose a {kind_label} smaller "
            f"than {max_bytes:,} bytes."
        )

    return _ResolvedWorkspaceMediaInput(
        file_id=file.id,
        revision_id=revision.id,
        name=file.name,
        object_key=revision.object_key,
        media_type=media_type,
        size_bytes=revision.size_bytes,
        revision=revision,
    )


async def _load_workspace_media_input(
    resolved: _ResolvedWorkspaceMediaInput,
    *,
    tool_name: str,
    kind_label: str,
    max_bytes: int | None,
) -> WorkspaceMediaInput:
    data = await get_storage_provider().get_object(private_ref_from_key(resolved.object_key))
    if max_bytes is not None and len(data) > max_bytes:
        raise ModelRetry(
            f"This {kind_label} is too large for {tool_name}. Choose a {kind_label} smaller "
            f"than {max_bytes:,} bytes."
        )
    return WorkspaceMediaInput(
        content=BinaryContent(
            data=data,
            media_type=resolved.media_type,
            identifier=str(resolved.file_id),
        ),
        file_id=resolved.file_id,
        revision_id=resolved.revision_id,
        name=resolved.name,
    )


async def load_workspace_media_inputs(
    ctx: RunContext[RuntimeDeps],
    file_references: Sequence[FileReference],
    *,
    category: FileCategory,
    allowed_media_types: Collection[str],
    tool_name: str,
    kind_label: str,
    max_bytes: int | None = None,
    max_total_bytes: int | None = None,
) -> tuple[WorkspaceMediaInput, ...]:
    """Validate aggregate size, then load workspace media in reference order."""
    resolved = tuple(
        [
            await _resolve_workspace_media_input(
                ctx,
                file_reference,
                category=category,
                allowed_media_types=allowed_media_types,
                tool_name=tool_name,
                kind_label=kind_label,
                max_bytes=max_bytes,
            )
            for file_reference in file_references
        ]
    )
    _validate_aggregate_size(
        sum(item.size_bytes for item in resolved),
        max_total_bytes=max_total_bytes,
        tool_name=tool_name,
        kind_label=kind_label,
    )

    loaded: list[WorkspaceMediaInput] = []
    loaded_bytes = 0
    for item in resolved:
        media_input = await _load_workspace_media_input(
            item,
            tool_name=tool_name,
            kind_label=kind_label,
            max_bytes=max_bytes,
        )
        loaded_bytes += len(media_input.content.data)
        _validate_aggregate_size(
            loaded_bytes,
            max_total_bytes=max_total_bytes,
            tool_name=tool_name,
            kind_label=kind_label,
        )
        loaded.append(media_input)
    return tuple(loaded)


def _validate_aggregate_size(
    size_bytes: int,
    *,
    max_total_bytes: int | None,
    tool_name: str,
    kind_label: str,
) -> None:
    if max_total_bytes is None or size_bytes <= max_total_bytes:
        return
    raise ModelRetry(
        f"The selected {kind_label} files are too large for {tool_name} together. Choose fewer "
        f"or smaller {kind_label} files totaling at most {max_total_bytes:,} bytes."
    )


def long_video_input_available() -> bool:
    """Checks Google can read workspace video past the inline bound on this deployment."""
    if not is_provider_configured(PROVIDER_GOOGLE):
        return False
    return not settings.GOOGLE_VERTEX_AI or settings.STORAGE_PROVIDER == "gcs"


async def load_workspace_video_input(
    ctx: RunContext[RuntimeDeps],
    file_reference: FileReference,
    *,
    tool_name: str,
    inline_max_bytes: int,
    options: VideoInputOptions | None = None,
) -> WorkspaceVideoInput:
    """Prepares a current workspace video for Google without trusting any model-supplied location.

    Vertex with GCS storage reads the revision by `gs://` URI. The Gemini API
    reads videos over `inline_max_bytes` through a cached Files API upload.
    Everything else is sent inline, up to `inline_max_bytes`.
    """
    resolved = await _resolve_workspace_media_input(
        ctx,
        file_reference,
        category=FileCategory.VIDEO,
        allowed_media_types=VIDEO_MEDIA_TYPES,
        tool_name=tool_name,
        kind_label="video",
        max_bytes=None,
    )
    metadata = (options or VideoInputOptions()).vendor_metadata()
    ref = _workspace_object_ref(ctx, resolved)
    content: BinaryContent | VideoUrl | UploadedFile | None = None
    if settings.GOOGLE_VERTEX_AI:
        uri = get_storage_provider().model_input_uri(ref) if ref is not None else None
        if uri is not None:
            content = VideoUrl(
                url=uri,
                media_type=resolved.media_type,
                vendor_metadata=metadata,
                identifier=str(resolved.file_id),
            )
    elif ref is not None and resolved.size_bytes > inline_max_bytes:
        content = UploadedFile(
            file_id=await _gemini_file_uri(ctx, resolved, ref, tool_name=tool_name),
            provider_name=PROVIDER_GOOGLE,
            media_type=resolved.media_type,
            vendor_metadata=metadata,
            identifier=str(resolved.file_id),
        )
    if content is None:
        loaded = await _load_workspace_media_input(
            resolved, tool_name=tool_name, kind_label="video", max_bytes=inline_max_bytes
        )
        content = BinaryContent(
            data=loaded.content.data,
            media_type=resolved.media_type,
            vendor_metadata=metadata,
            identifier=str(resolved.file_id),
        )
    return WorkspaceVideoInput(
        content=content,
        file_id=resolved.file_id,
        revision_id=resolved.revision_id,
        name=resolved.name,
    )


def _workspace_object_ref(
    ctx: RunContext[RuntimeDeps], resolved: _ResolvedWorkspaceMediaInput
) -> StorageObjectRef | None:
    """Returns the caller's own workspace object, or None for shared platform files."""
    if resolved.revision.workspace_id != ctx.deps.workspace.id:
        return None
    ref = private_ref_from_key(resolved.object_key)
    # The object key, not the row, decides which bucket a URI or upload reads.
    if workspace_id_for_ref(ref) != ctx.deps.workspace.id:
        raise ToolFailed("This video's storage doesn't belong to this workspace.")
    return ref


async def _gemini_file_uri(
    ctx: RunContext[RuntimeDeps],
    resolved: _ResolvedWorkspaceMediaInput,
    ref: StorageObjectRef,
    *,
    tool_name: str,
) -> str:
    revision = resolved.revision
    cached_until = revision.gemini_file_expires_at
    if cached_until is not None and cached_until > datetime.now(UTC) + _GEMINI_FILE_REUSE_MARGIN:
        return revision.gemini_file_uri
    if resolved.size_bytes > GEMINI_FILES_MAX_BYTES:
        raise ModelRetry(
            f"This video is larger than the 2 GB {tool_name} can send to Google. "
            "Cut a shorter range first."
        )
    stale_name = revision.gemini_file_name
    try:
        uploaded = await upload_gemini_file(
            ref,
            size_bytes=resolved.size_bytes,
            media_type=resolved.media_type,
            display_name=str(resolved.revision_id),
        )
    except GeminiFileError as exc:
        raise ToolFailed(str(exc)) from exc
    revision.gemini_file_name = uploaded.name
    revision.gemini_file_uri = uploaded.uri
    revision.gemini_file_expires_at = uploaded.expires_at
    await _record_gemini_upload(ctx, resolved, uploaded, tool_name=tool_name)
    # Workspace bytes now sit with Google, so the record must survive a failed provider call.
    await ctx.deps.db.commit()
    if stale_name is not None:
        await delete_gemini_file(stale_name)
    return uploaded.uri


async def _record_gemini_upload(
    ctx: RunContext[RuntimeDeps],
    resolved: _ResolvedWorkspaceMediaInput,
    uploaded: GeminiFile,
    *,
    tool_name: str,
) -> None:
    await safe_record_operation_audit_event(
        ctx.deps.db,
        workspace_id=ctx.deps.workspace.id,
        action=AuditAction.READ,
        resource_type=AuditResourceType.FILE,
        resource_id=resolved.file_id,
        actor_type=AuditActorType.AGENT,
        actor_id=ctx.deps.agent.id,
        actor_display=ctx.deps.agent.name,
        requested_by_user_id=ctx.deps.user.id,
        details={
            "operation": "gemini_files_upload",
            "tool_name": tool_name,
            "run_id": str(ctx.deps.run.id),
            "revision_id": str(resolved.revision_id),
            "size_bytes": resolved.size_bytes,
            "gemini_file_name": uploaded.name,
            "expires_at": uploaded.expires_at.isoformat(),
        },
    )
