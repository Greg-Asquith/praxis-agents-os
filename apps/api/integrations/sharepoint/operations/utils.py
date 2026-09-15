# apps/api/integrations/sharepoint/operations/utils.py

"""Bounded metadata and provenance for SharePoint drive items."""

from typing import Literal
from urllib.parse import quote

from pydantic import ValidationError

from core.exceptions.integration import IntegrationValidationError
from services.agents.runtime.untrusted import UntrustedNode

from ..references import SharePointDriveItemReference

ITEM_SELECT = (
    "id,name,size,file,folder,package,lastModifiedDateTime,webUrl,parentReference,remoteItem"
)
MAX_CITATION_URL_CHARS = 8192


def item_path(drive_id: str, item_id: str | None = None) -> str:
    if drive_id in {".", ".."} or item_id in {".", ".."}:
        raise invalid_response("get_item")
    root = f"/drives/{quote(drive_id, safe='')}"
    return f"{root}/items/{quote(item_id, safe='')}" if item_id else f"{root}/root"


def invalid_response(operation: str) -> IntegrationValidationError:
    return IntegrationValidationError(
        "SharePoint returned invalid item metadata.",
        provider_key="sharepoint",
        operation=operation,
    )


def object_payload(value: object, *, operation: str) -> dict:
    if not isinstance(value, dict):
        raise invalid_response(operation)
    return value


def is_local_item(item: dict, drive_id: str) -> bool:
    parent = item.get("parentReference")
    return (
        "remoteItem" not in item and isinstance(parent, dict) and parent.get("driveId") == drive_id
    )


def untrusted(drive_id: str, item_id: str, value: object, limit: int = 500) -> UntrustedNode:
    return UntrustedNode(
        source_kind="sharepoint_drive_item",
        source_ref=f"{drive_id}:{item_id}",
        content=value[:limit] if isinstance(value, str) else "",
    )


def item_kind(item: dict) -> Literal["file", "folder"] | None:
    """Returns a supported kind, or None for package items."""
    if isinstance(item.get("package"), dict):
        return None
    if isinstance(item.get("folder"), dict):
        return "folder"
    if isinstance(item.get("file"), dict):
        return "file"
    raise invalid_response("list_folder")


def citation_url(drive_id: str, item_id: str, value: object) -> UntrustedNode:
    if isinstance(value, str) and len(value) > MAX_CITATION_URL_CHARS:
        raise IntegrationValidationError(
            "SharePoint returned a citation URL that is too long.",
            provider_key="sharepoint",
            operation="list_folder",
        )
    return untrusted(drive_id, item_id, value, MAX_CITATION_URL_CHARS)


def item_result(item: dict, *, drive_id: str) -> dict:
    kind = item_kind(item)
    if kind is None:
        raise invalid_response("list_folder")
    try:
        reference = SharePointDriveItemReference(
            drive_id=drive_id, item_id=item.get("id"), kind=kind
        )
    except ValidationError:
        raise invalid_response("list_folder") from None
    item_id = reference.item_id
    parent = object_payload(item.get("parentReference"), operation="list_folder")
    file = item.get("file")
    size = item.get("size", 0)
    if type(size) is not int or size < 0:
        raise invalid_response("list_folder")
    return {
        "reference": reference,
        "name": untrusted(drive_id, item_id, item.get("name")),
        "kind": kind,
        "path": untrusted(drive_id, item_id, parent.get("path"), 2000),
        "size_bytes": size,
        "content_type": untrusted(
            drive_id, item_id, file.get("mimeType") if isinstance(file, dict) else None, 255
        ),
        "modified_at": untrusted(drive_id, item_id, item.get("lastModifiedDateTime"), 100),
        "web_url": citation_url(drive_id, item_id, item.get("webUrl")),
    }
