# apps/api/services/files/contract.py

"""File type contract shared by file services and future UI code."""

from dataclasses import dataclass
from enum import StrEnum

from core.exceptions.general import AppValidationError
from core.settings import settings
from services.assets.utils import normalize_content_type
from services.files.utils import normalize_extension


class FileCategory(StrEnum):
    """Supported file policy categories."""

    EDITABLE_TEXT = "editable_text"
    INGESTIBLE_DOCUMENT = "ingestible_document"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"


@dataclass(frozen=True)
class FileContractEntry:
    """Policy for one accepted MIME type."""

    category: FileCategory
    content_type: str
    extensions: tuple[str, ...]
    max_size_setting: str
    editable: bool
    ingestible: bool


FILE_CONTRACT: tuple[FileContractEntry, ...] = (
    FileContractEntry(
        category=FileCategory.EDITABLE_TEXT,
        content_type="text/plain",
        extensions=(".txt",),
        max_size_setting="MAX_FILE_SIZE_DOCUMENT",
        editable=True,
        ingestible=False,
    ),
    FileContractEntry(
        category=FileCategory.EDITABLE_TEXT,
        content_type="text/markdown",
        extensions=(".md", ".markdown", ".mdx"),
        max_size_setting="MAX_FILE_SIZE_DOCUMENT",
        editable=True,
        ingestible=False,
    ),
    FileContractEntry(
        category=FileCategory.EDITABLE_TEXT,
        content_type="text/csv",
        extensions=(".csv",),
        max_size_setting="MAX_FILE_SIZE_DOCUMENT",
        editable=True,
        ingestible=False,
    ),
    FileContractEntry(
        category=FileCategory.EDITABLE_TEXT,
        content_type="application/json",
        extensions=(".json",),
        max_size_setting="MAX_FILE_SIZE_DOCUMENT",
        editable=True,
        ingestible=False,
    ),
    FileContractEntry(
        category=FileCategory.EDITABLE_TEXT,
        content_type="application/html",
        extensions=(".html",),
        max_size_setting="MAX_FILE_SIZE_DOCUMENT",
        editable=True,
        ingestible=False,
    ),
    FileContractEntry(
        category=FileCategory.INGESTIBLE_DOCUMENT,
        content_type="application/pdf",
        extensions=(".pdf",),
        max_size_setting="MAX_FILE_SIZE_DOCUMENT",
        editable=False,
        ingestible=True,
    ),
    FileContractEntry(
        category=FileCategory.INGESTIBLE_DOCUMENT,
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        extensions=(".docx",),
        max_size_setting="MAX_FILE_SIZE_DOCUMENT",
        editable=False,
        ingestible=True,
    ),
    FileContractEntry(
        category=FileCategory.INGESTIBLE_DOCUMENT,
        content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        extensions=(".pptx",),
        max_size_setting="MAX_FILE_SIZE_DOCUMENT",
        editable=False,
        ingestible=True,
    ),
    FileContractEntry(
        category=FileCategory.INGESTIBLE_DOCUMENT,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        extensions=(".xlsx",),
        max_size_setting="MAX_FILE_SIZE_DOCUMENT",
        editable=False,
        ingestible=True,
    ),
    FileContractEntry(
        category=FileCategory.IMAGE,
        content_type="image/png",
        extensions=(".png",),
        max_size_setting="MAX_FILE_SIZE_IMAGE",
        editable=False,
        ingestible=False,
    ),
    FileContractEntry(
        category=FileCategory.IMAGE,
        content_type="image/jpeg",
        extensions=(".jpg", ".jpeg"),
        max_size_setting="MAX_FILE_SIZE_IMAGE",
        editable=False,
        ingestible=False,
    ),
    FileContractEntry(
        category=FileCategory.IMAGE,
        content_type="image/webp",
        extensions=(".webp",),
        max_size_setting="MAX_FILE_SIZE_IMAGE",
        editable=False,
        ingestible=False,
    ),
    FileContractEntry(
        category=FileCategory.VIDEO,
        content_type="video/mp4",
        extensions=(".mp4",),
        max_size_setting="MAX_FILE_SIZE_VIDEO",
        editable=False,
        ingestible=False,
    ),
    FileContractEntry(
        category=FileCategory.VIDEO,
        content_type="video/mov",
        extensions=(".mov",),
        max_size_setting="MAX_FILE_SIZE_VIDEO",
        editable=False,
        ingestible=False,
    ),
)

_CONTRACT_BY_CONTENT_TYPE = {entry.content_type: entry for entry in FILE_CONTRACT}

def _validate_contract() -> None:
    seen_extensions: dict[str, str] = {}
    for entry in FILE_CONTRACT:
        if _CONTRACT_BY_CONTENT_TYPE[entry.content_type] is not entry:
            raise RuntimeError(f"Duplicate file content type: {entry.content_type}")
        for extension in entry.extensions:
            owner = seen_extensions.setdefault(extension, entry.content_type)
            if owner != entry.content_type:
                raise RuntimeError(
                    f"File extension {extension} maps to both {owner} and {entry.content_type}"
                )


def contract_for_content_type(content_type: str) -> FileContractEntry:
    """Return the file contract entry for an accepted MIME type."""
    normalized = normalize_content_type(content_type)
    entry = _CONTRACT_BY_CONTENT_TYPE.get(normalized)
    if entry is None:
        raise AppValidationError("Unsupported file type", field="content_type")
    return entry


def require_matching_pair(content_type: str, extension: str) -> FileContractEntry:
    """Return the contract entry when MIME type and extension are an allowed pair."""
    entry = contract_for_content_type(content_type)
    normalized_extension = normalize_extension(extension)
    if normalized_extension not in entry.extensions:
        raise AppValidationError("File extension does not match file type", field="extension")
    return entry


def max_size_bytes(entry: FileContractEntry) -> int:
    """Resolve the configured byte limit for a contract entry."""
    try:
        return int(getattr(settings, entry.max_size_setting))
    except AttributeError as exc:
        raise RuntimeError(f"Missing file size setting: {entry.max_size_setting}") from exc


def is_ingestible(content_type: str) -> bool:
    """Return whether the file type should be extracted to markdown."""
    return contract_for_content_type(content_type).ingestible


def is_editable(content_type: str) -> bool:
    """Return whether the file type supports text edits."""
    return contract_for_content_type(content_type).editable


_validate_contract()
