# apps/api/integrations/sharepoint/operations/replace_item.py

"""Replaces file bytes only when their reviewed version still matches."""

import asyncio

from core.exceptions.integration import IntegrationError, IntegrationFailureDisposition
from services.integrations.microsoft_graph import MicrosoftGraphClient

from .get_item import get_item
from .upload_session import UploadTarget, run_upload_session
from .utils import file_error, item_path
from .write_utils import DriveWriteState, item_version


async def verify_current_version(
    client: MicrosoftGraphClient, *, drive_id: str, item_id: str, expected_version: str
) -> dict:
    try:
        item = await get_item(client, drive_id=drive_id, item_id=item_id)
        if (
            not isinstance(item.get("file"), dict)
            or "folder" in item
            or isinstance(item.get("package"), dict)
        ):
            raise file_error(
                "Choose a file to replace.", "unsupported_type", operation="replace_item"
            )
        if item_version(item, operation="replace_item") != expected_version:
            raise file_error(
                "The file changed in SharePoint. Read it again before replacing it.",
                "version_conflict",
                operation="replace_item",
            )
        return item
    except (IntegrationError, asyncio.CancelledError) as exc:
        exc.failure_disposition = IntegrationFailureDisposition.NOT_DISPATCHED
        raise


async def replace_item(
    client: MicrosoftGraphClient,
    *,
    drive_id: str,
    item_id: str,
    data: bytes,
    expected_version: str,
    state: DriveWriteState | None = None,
) -> dict:
    state = state if state is not None else DriveWriteState()
    state.etag_before = expected_version
    state.item_id = item_id
    await verify_current_version(
        client, drive_id=drive_id, item_id=item_id, expected_version=expected_version
    )
    target_path = item_path(drive_id, item_id)
    return await run_upload_session(
        client,
        target=UploadTarget(
            drive_id=drive_id,
            session_path=f"{target_path}/createUploadSession",
            item_path=target_path,
            operation="replace_item",
            item_id=item_id,
            expected_version=expected_version,
        ),
        data=data,
        state=state,
    )
