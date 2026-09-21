# apps/api/integraions/sharepoint/operations/write_utils.py

"""Validation and effect evidence for SharePoint writes."""

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, TypeAdapter, ValidationError

from core.exceptions.integration import (
    IntegrationFailureDisposition,
    IntegrationUnverifiedMutationError,
)
from core.settings import settings
from services.files.contract import FILE_CONTRACT
from utils.quickxorhash import quickxorhash

from .utils import file_error, invalid_response, is_local_item, item_result

_RESERVED_NAMES = {".lock", "con", "prn", "aux", "nul", "_vti_", "desktop.ini"} | {
    f"{prefix}{number}" for prefix in ("com", "lpt") for number in range(10)
}
_TEXT_TYPES = {
    extension: entry.content_type
    for entry in FILE_CONTRACT
    if entry.editable
    for extension in entry.extensions
}


def validate_name(value: str) -> str:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("Enter a valid Unicode name.") from None
    if value != value.strip(" .") or value.startswith("~$"):
        raise ValueError("Use a name without leading or trailing spaces or dots, or a ~$ prefix.")
    if any(char in '/\\:*?"<>|' or ord(char) < 32 or 127 <= ord(char) <= 159 for char in value):
        raise ValueError("The name contains a character SharePoint does not allow.")
    lower = value.casefold()
    if lower in _RESERVED_NAMES or lower.split(".")[0] in _RESERVED_NAMES or "_vti_" in lower:
        raise ValueError("SharePoint reserves this name. Choose another name.")
    return value


def validate_text_content(value: str) -> str:
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError:
        raise ValueError("Enter valid Unicode text.") from None
    if any((ord(char) < 32 and char not in "\n\t") or 127 <= ord(char) <= 159 for char in value):
        raise ValueError("Text cannot contain control characters other than newline and tab.")
    if size > settings.FILES_MAX_TEXT_EDIT_BYTES:
        raise ValueError("The text exceeds the file editing size limit.")
    return value


type ItemName = Annotated[
    str, Field(strict=True, min_length=1, max_length=255), AfterValidator(validate_name)
]
type VersionToken = Annotated[
    str,
    Field(
        strict=True,
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9{},.\-\"]{1,200}$",
    ),
]
type TextContent = Annotated[
    str, Field(strict=True, min_length=1), AfterValidator(validate_text_content)
]

_VERSION = TypeAdapter(VersionToken)


@dataclass
class DriveWriteState:
    """Retains bounded evidence without retaining an upload URL or source bytes."""

    session_created: bool = False
    bytes_sent: int = 0  # Bytes acknowledged by a response or verified at commit.
    committed: bool = False
    item_id: str | None = None
    etag_before: str | None = None
    etag_after: str | None = None
    hash_matched: bool | None = None
    item: dict | None = None
    final_fragment_started: bool = False
    session_status: str | None = None


def item_version(item: dict, *, operation: str) -> str:
    try:
        return _VERSION.validate_python(item.get("eTag"))
    except ValidationError:
        raise invalid_response(operation) from None


def text_content_type(name: str, *, operation: str) -> str:
    content_type = _TEXT_TYPES.get(PurePosixPath(name).suffix.casefold())
    if content_type is None:
        raise file_error(
            "Text requires a text file extension, such as .txt, .md, .csv, .json, or .html.",
            "unsupported_type",
            operation=operation,
        )
    return content_type


def verify_uploaded_item(item: dict, *, data: bytes) -> bool:
    file = item.get("file")
    hashes = file.get("hashes") if isinstance(file, dict) else None
    if type(item.get("size")) is not int or item["size"] != len(data):
        return False
    return isinstance(hashes, dict) and hashes.get("quickXorHash") == quickxorhash(data)


def written_item(
    item: dict,
    *,
    drive_id: str,
    operation: str,
    state: DriveWriteState,
    kind: Literal["file", "folder"],
    name: str | None = None,
    parent_id: str | None = None,
) -> dict:
    if not is_local_item(item, drive_id):
        raise invalid_response(operation)
    other_kind = "folder" if kind == "file" else "file"
    if not isinstance(item.get(kind), dict) or other_kind in item:
        raise invalid_response(operation)
    if name is not None and item.get("name") != name:
        raise invalid_response(operation)
    if parent_id is not None and item["parentReference"].get("id") != parent_id:
        raise invalid_response(operation)
    result = item_result(item, drive_id=drive_id, operation=operation)
    state.item_id = result["reference"].item_id
    result["version"] = item_version(item, operation=operation)
    state.etag_after = result["version"]
    state.item = result
    return result


def unverified_write(operation: str, state: DriveWriteState) -> IntegrationUnverifiedMutationError:
    return IntegrationUnverifiedMutationError(
        "The saved file could not be confirmed. Check the file in SharePoint before trying again.",
        provider_key="sharepoint",
        operation=operation,
        error_code="unverified_mutation",
        failure_disposition=IntegrationFailureDisposition.AMBIGUOUS,
        result_data=state.item,
    )
