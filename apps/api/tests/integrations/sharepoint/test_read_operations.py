# apps/api/tests/integrations/sharepoint/test_read_operations.py

"""SharePoint folder bounds, scope checks, and metadata projection."""

import httpx2
import pytest

from core.exceptions.integration import IntegrationValidationError
from integrations.sharepoint.operations.list_children import list_children
from integrations.sharepoint.operations.utils import ITEM_SELECT
from tests.integrations.sharepoint.support import fixture, graph


@pytest.mark.parametrize("overfull", [True])
async def test_folder_with_over_200_children_reports_more_without_following_links(overfull):
    requests = []
    file, folder = fixture("children.json")["value"]

    def handler(request):
        requests.append(request.url.path)
        assert request.url.params["$select"] == ITEM_SELECT
        if request.url.path.endswith("/items/folder"):
            return httpx2.Response(200, json=folder)
        assert request.url.params["$top"] == "200"
        payload = {"value": [{**file, "id": f"item-{i}"} for i in range(201 if overfull else 200)]}
        if not overfull:
            payload["@odata.nextLink"] = (
                "https://graph.microsoft.com/v1.0/drives/other/root/children"
            )
        return httpx2.Response(200, json=payload)

    async with graph(handler) as client:
        result = await list_children(client, drive_id="drive", folder_id="folder", limit=200)
    assert result["count"] == len(result["items"]) == 200
    assert result["has_more"] is True
    assert requests == [
        "/v1.0/drives/drive/items/folder",
        "/v1.0/drives/drive/items/folder/children",
    ]


async def test_listing_drops_remote_foreign_and_unscoped_items():
    file = fixture("children.json")["value"][0]
    payload = {
        "value": [
            file,
            {**file, "remoteItem": {}},
            {**file, "parentReference": {"driveId": "other"}},
            {**file, "parentReference": {}},
        ]
    }
    async with graph(lambda _: httpx2.Response(200, json=payload)) as client:
        result = await list_children(client, drive_id="drive")
    assert result["count"] == 1


@pytest.mark.parametrize(
    "change",
    [
        {"remoteItem": {}},
        {"parentReference": {"driveId": "other"}},
    ],
)
async def test_target_metadata_rejects_shortcuts_foreign_items_and_files(change):
    requests = []
    folder = fixture("children.json")["value"][1]

    def handler(request):
        requests.append(request.url.path)
        return httpx2.Response(200, json={**folder, **change})

    async with graph(handler) as client:
        with pytest.raises(IntegrationValidationError):
            await list_children(client, drive_id="drive", folder_id="folder")
    assert requests == ["/v1.0/drives/drive/items/folder"]


@pytest.mark.parametrize(
    "packages_only",
    [
        False,
    ],
)
@pytest.mark.parametrize(
    "continuation",
    [
        False,
    ],
)
async def test_packages_are_omitted_without_discarding_supported_items(packages_only, continuation):
    file, folder = fixture("children.json")["value"]
    package = {
        "id": "notebook",
        "parentReference": {"driveId": "drive"},
        "package": {"type": "oneNote"},
    }
    payload = {"value": [package] if packages_only else [file, package, folder]}
    if continuation:
        payload["@odata.nextLink"] = "https://graph.microsoft.com/v1.0/next"
    requests = []

    def handler(request):
        requests.append(request)
        assert "package" in request.url.params["$select"].split(",")
        return httpx2.Response(200, json=payload)

    async with graph(handler) as client:
        result = await list_children(client, drive_id="drive")
    assert len(requests) == 1
    assert result["count"] == len(result["items"]) == (0 if packages_only else 2)
    assert [row["reference"].item_id for row in result["items"]] == (
        [] if packages_only else ["file", "folder"]
    )
    assert result["has_more"] is continuation
