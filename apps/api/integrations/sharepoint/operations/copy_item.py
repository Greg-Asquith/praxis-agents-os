# apps/api/integrations/sharepoint/operations/copy_item.py

"""Downloads original bytes accepted by the workspace file contract."""

from core.exceptions.general import AppValidationError
from services.files.contract import contract_for_content_type, max_size_bytes
from services.integrations.microsoft_graph import MicrosoftGraphClient

from ..settings import sharepoint_settings
from .download_utils import download_content, download_metadata, validate_copy_content
from .utils import file_error
from .write_utils import item_version


async def copy_item(
    client: MicrosoftGraphClient, *, drive_id: str, item_id: str
) -> tuple[dict, bytes]:
    item, url = await download_metadata(
        client,
        drive_id=drive_id,
        item_id=item_id,
        operation="copy_to_files",
        unsupported_message="Select a file to copy. Folders and packages cannot be copied.",
    )
    item_version(item, operation="copy_to_files")
    try:
        contract = contract_for_content_type(item["file"].get("mimeType"))
    except AppValidationError:
        raise file_error(
            "Files does not support this file type. Select a supported document, image, or video.",
            "unsupported_type",
            operation="copy_to_files",
        ) from None
    data = await download_content(
        client,
        item=item,
        url=url,
        operation="copy_to_files",
        max_bytes=min(
            sharepoint_settings.SHAREPOINT_FILE_MAX_DOWNLOAD_BYTES, max_size_bytes(contract)
        ),
        content_type=contract.content_type,
        too_large_message="This file exceeds the copy size limit. Select a smaller file.",
    )
    await validate_copy_content(item, data, operation="copy_to_files")
    return item, data
