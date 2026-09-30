# apps/api/services/documents/inputs.py

"""Size and type gates for Files that a tool loads as input. Runs in the host process."""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from uuid import UUID

from pydantic_ai import ModelRetry, RunContext

from models.files import File, FileRevision
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.entity_references.domain import FileReference
from services.agents.runtime.tools.files.utils import current_file_revision
from services.files.contract import FileCategory, contract_for_content_type
from services.files.utils import file_revision_ref
from services.storage.factory import get_storage_provider
from utils.content import ContentScope


@dataclass(frozen=True)
class InputFile:
    file_id: UUID
    revision_id: UUID
    name: str
    content: bytes
    media_type: str
    category: FileCategory
    scope: str = ContentScope.WORKSPACE


async def load_input_files(
    ctx: RunContext[RuntimeDeps],
    references: Sequence[FileReference],
    *,
    tool_name: str,
    categories: Collection[FileCategory],
    max_file_bytes: int,
    max_total_bytes: int,
    media_types: Collection[str] | None = None,
) -> tuple[InputFile, ...]:
    """Loads bounded bytes from visible revisions, retaining conversation pins.

    Checks declared sizes before any download and actual sizes after each one.
    """
    ids = list(dict.fromkeys(reference.entity_id for reference in references))
    total = 0
    revisions: list[tuple[File, FileRevision, FileCategory]] = []
    for file_id in ids:
        file, revision = await current_file_revision(ctx, file_id)
        entry = contract_for_content_type(revision.content_type)
        if entry.category not in categories or (
            media_types is not None and entry.content_type not in media_types
        ):
            raise ModelRetry(f"{file.name} is a file type that {tool_name} can't use.")
        if revision.size_bytes > max_file_bytes:
            raise ModelRetry(
                f"{file.name} is too large for {tool_name}. Choose a file no larger than "
                f"{max_file_bytes:,} bytes."
            )
        total += revision.size_bytes
        if total > max_total_bytes:
            raise ModelRetry(
                f"The files for {tool_name} are too large together. Choose files totaling "
                f"at most {max_total_bytes:,} bytes."
            )
        revisions.append((file, revision, entry.category))

    storage = get_storage_provider()
    loaded: list[InputFile] = []
    actual_total = 0
    for file, revision, category in revisions:
        data = await storage.get_object(file_revision_ref(revision))
        actual_total += len(data)
        if len(data) > max_file_bytes or actual_total > max_total_bytes:
            raise ModelRetry(f"{file.name} is larger than {tool_name} allows.")
        loaded.append(
            InputFile(
                file_id=file.id,
                revision_id=revision.id,
                name=file.name,
                content=data,
                media_type=revision.content_type,
                category=category,
                scope=file.scope,
            )
        )
    return tuple(loaded)
