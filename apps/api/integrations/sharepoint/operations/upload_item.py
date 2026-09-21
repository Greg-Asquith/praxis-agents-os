# apps/api/integrations/sharepoint/operations/upload_item.py

"""Creates a file through a conflict-safe upload session."""

from urllib.parse import quote

from services.integrations.microsoft_graph import MicrosoftGraphClient

from .upload_session import UploadTarget, run_upload_session
from .utils import item_path
from .write_utils import DriveWriteState


async def upload_item(
    client: MicrosoftGraphClient,
    *,
    drive_id: str,
    parent_id: str | None,
    name: str,
    data: bytes,
    state: DriveWriteState | None = None,
) -> dict:
    target_path = f"{item_path(drive_id, parent_id)}:/{quote(name, safe='')}"
    return await run_upload_session(
        client,
        target=UploadTarget(
            drive_id=drive_id,
            session_path=f"{target_path}:/createUploadSession",
            item_path=target_path,
            operation="upload_item",
            name=name,
            parent_id=parent_id,
        ),
        data=data,
        state=state if state is not None else DriveWriteState(),
    )
