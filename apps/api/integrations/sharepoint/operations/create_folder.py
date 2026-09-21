# apps/api/integrations/sharepoint/operations/create_folder.py

"""Creates a folder without replacing a namesake item."""

from services.integrations.http import IntegrationRequestPolicy
from services.integrations.microsoft_graph import MicrosoftGraphClient

from .utils import item_path, object_payload
from .write_utils import DriveWriteState, written_item


async def create_folder(
    client: MicrosoftGraphClient,
    *,
    drive_id: str,
    parent_id: str | None,
    name: str,
    state: DriveWriteState | None = None,
) -> dict:
    state = state if state is not None else DriveWriteState()
    payload = object_payload(
        await client.post(
            f"{item_path(drive_id, parent_id)}/children",
            operation="create_folder",
            policy=IntegrationRequestPolicy.MUTATION,
            json={"name": name, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"},
        ),
        operation="create_folder",
    )
    state.committed = True
    return written_item(
        payload,
        drive_id=drive_id,
        operation="create_folder",
        state=state,
        kind="folder",
        name=name,
        parent_id=parent_id,
    )
