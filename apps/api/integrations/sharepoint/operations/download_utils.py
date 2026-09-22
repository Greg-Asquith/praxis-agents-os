# apps/api/integrations/sharepoint/operations/download_utils.py

"""Validates shared file metadata and bounds confidential downloads."""

import asyncio
import hashlib

from core.exceptions.integration import IntegrationDownloadTooLargeError
from services.integrations.microsoft_graph import MicrosoftGraphClient
from utils.quickxorhash import quickxorhash

from .get_item import get_item
from .utils import file_error, invalid_response, item_kind, item_result, require_file_citation


async def download_metadata(
    client: MicrosoftGraphClient,
    *,
    drive_id: str,
    item_id: str,
    operation: str,
    unsupported_message: str,
) -> tuple[dict, object]:
    """Returns validated file metadata and its private download URL."""
    item = await get_item(client, drive_id=drive_id, item_id=item_id, include_download_url=True)
    url = item.pop("@microsoft.graph.downloadUrl", None)
    if item_kind(item, operation=operation) != "file":
        raise file_error(unsupported_message, "unsupported_type", operation=operation)
    result = item_result(item, drive_id=drive_id, operation=operation)
    item["file"] = {**item["file"], "mimeType": result["content_type"].content}
    require_file_citation(item.get("webUrl"), operation=operation)
    if "size" not in item:
        raise invalid_response(operation)
    return item, url


async def download_content(
    client: MicrosoftGraphClient,
    *,
    item: dict,
    url: object,
    operation: str,
    max_bytes: int,
    content_type: str,
    too_large_message: str,
) -> bytes:
    """Downloads bounded bytes and normalises the MIME type without losing hashes."""
    if item["size"] > max_bytes:
        raise file_error(too_large_message, "too_large", operation=operation)
    if not isinstance(url, str) or not url:
        raise invalid_response(operation)
    try:
        data = await client.get_bytes(url, operation=operation, max_bytes=max_bytes)
    except IntegrationDownloadTooLargeError:
        raise file_error(too_large_message, "too_large", operation=operation) from None
    item["file"] = {**item["file"], "mimeType": content_type}
    return data


def _download_hashes_match(hashes: dict, data: bytes) -> bool:
    quickxor = hashes.get("quickXorHash")
    if quickxor is not None and quickxor != quickxorhash(data):
        return False
    sha1 = hashes.get("sha1Hash")
    if sha1 is not None:
        return (
            isinstance(sha1, str)
            and sha1.casefold() == hashlib.sha1(data, usedforsecurity=False).hexdigest()
        )
    return True


async def validate_copy_content(item: dict, data: bytes, *, operation: str) -> None:
    """Checks exact byte size and available supported hashes before local writes."""
    hashes = item["file"].get("hashes")
    if len(data) != item["size"] or (
        hashes is not None
        and (
            not isinstance(hashes, dict)
            or not await asyncio.to_thread(_download_hashes_match, hashes, data)
        )
    ):
        raise file_error(
            "The downloaded file does not match its SharePoint metadata. "
            "Read the file again before copying it.",
            "source_changed",
            operation=operation,
        )
