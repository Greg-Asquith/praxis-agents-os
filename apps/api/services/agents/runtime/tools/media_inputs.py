# apps/api/services/agents/runtime/tools/media_inputs.py

"""Governed workspace media loading shared by runtime tools."""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.messages import BinaryContent

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.entity_references.domain import FileReference, internal_entity_id
from services.agents.runtime.tools.files.utils import current_file_revision
from services.files.contract import FileCategory
from services.files.utils import private_ref_from_key
from services.storage.factory import get_storage_provider


@dataclass(frozen=True)
class WorkspaceMediaInput:
    """One governed current file revision prepared as model input."""

    content: BinaryContent
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


async def load_workspace_media_input(
    ctx: RunContext[RuntimeDeps],
    file_reference: FileReference,
    *,
    category: FileCategory,
    allowed_media_types: Collection[str],
    tool_name: str,
    kind_label: str,
    max_bytes: int | None = None,
    media_type_overrides: Mapping[str, str] | None = None,
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
        media_type_overrides=media_type_overrides,
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
    )


async def _load_workspace_media_input(
    resolved: _ResolvedWorkspaceMediaInput,
    *,
    tool_name: str,
    kind_label: str,
    max_bytes: int | None,
    media_type_overrides: Mapping[str, str] | None,
) -> WorkspaceMediaInput:
    data = await get_storage_provider().get_object(private_ref_from_key(resolved.object_key))
    if max_bytes is not None and len(data) > max_bytes:
        raise ModelRetry(
            f"This {kind_label} is too large for {tool_name}. Choose a {kind_label} smaller "
            f"than {max_bytes:,} bytes."
        )
    overrides = media_type_overrides or {}
    return WorkspaceMediaInput(
        content=BinaryContent(
            data=data,
            media_type=overrides.get(resolved.media_type, resolved.media_type),
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
    media_type_overrides: Mapping[str, str] | None = None,
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
            media_type_overrides=media_type_overrides,
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
