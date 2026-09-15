# apps/api/tests/integrations/sharepoint/test_read_operations.py

"""SharePoint folder bounds, scope checks, and metadata projection."""

from urllib.parse import quote

import httpx2
import pytest

from core.exceptions.integration import IntegrationNotFoundError, IntegrationValidationError
from integrations.sharepoint.operations.get_item import get_item
from integrations.sharepoint.operations.list_children import list_children
from integrations.sharepoint.operations.utils import ITEM_SELECT
from tests.integrations.sharepoint.support import fixture, graph


async def test_root_listing_selects_only_bounded_metadata():
    def handler(request):
        assert request.url.path == "/v1.0/drives/drive/root/children"
        assert dict(request.url.params) == {"$select": ITEM_SELECT, "$top": "50"}
        return httpx2.Response(200, json=fixture("children.json"))

    async with graph(handler) as client:
        result = await list_children(client, drive_id="drive")
    assert result["count"] == 2 and result["has_more"] is False
    assert [item["kind"] for item in result["items"]] == ["file", "folder"]
    assert result["items"][0]["size_bytes"] == 1234
    assert result["items"][1]["content_type"].content == ""


@pytest.mark.parametrize("overfull", [False, True])
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


@pytest.mark.parametrize("targeted", [False, True])
async def test_not_found_propagates(targeted):
    async with graph(lambda _: httpx2.Response(404)) as client:
        with pytest.raises(IntegrationNotFoundError):
            await list_children(client, drive_id="drive", folder_id="missing" if targeted else None)


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
        {"id": "other"},
        {"folder": None, "file": {}},
        {"folder": None, "package": {"type": "oneNote"}},
        {"package": {"type": "oneNote"}},
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


async def test_get_item_excludes_unrequested_download_annotation(caplog):
    file = fixture("children.json")["value"][0]
    url = "https://example.sharepoint.com/preauthenticated-secret"
    async with graph(
        lambda _: httpx2.Response(200, json={**file, "@microsoft.graph.downloadUrl": url})
    ) as client:
        result = await get_item(client, drive_id="drive", item_id="file")
    assert result == file
    assert url not in str(result) + caplog.text


@pytest.mark.parametrize("payload", [[], {}, {"value": "invalid"}])
async def test_malformed_listing_fails(payload):
    async with graph(lambda _: httpx2.Response(200, json=payload)) as client:
        with pytest.raises(IntegrationValidationError):
            await list_children(client, drive_id="drive")


@pytest.mark.parametrize("change", [{"file": None}, {"size": -1}, {"id": ""}])
async def test_malformed_local_supported_items_still_fail(change):
    file = fixture("children.json")["value"][0]
    async with graph(
        lambda _: httpx2.Response(200, json={"value": [file, {**file, **change}]})
    ) as client:
        with pytest.raises(IntegrationValidationError, match="invalid item metadata") as caught:
            await list_children(client, drive_id="drive")
    assert caught.value.operation == "list_folder"


@pytest.mark.parametrize("packages_only", [False, True])
@pytest.mark.parametrize("continuation", [False, True])
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


async def test_packages_do_not_expand_the_200_row_provider_page_bound():
    file = fixture("children.json")["value"][0]
    package = {
        "id": "notebook",
        "parentReference": {"driveId": "drive"},
        "package": {"type": "oneNote"},
    }
    values = [package, *[{**file, "id": f"file-{i}"} for i in range(200)]]
    async with graph(lambda _: httpx2.Response(200, json={"value": values})) as client:
        result = await list_children(client, drive_id="drive", limit=200)
    assert result["count"] == len(result["items"]) == 199
    assert result["items"][-1]["reference"].item_id == "file-198"
    assert result["has_more"] is True


@pytest.mark.parametrize(
    "item_id", ["REJECTED_PROVIDER_MARKER invalid", "REJECTED_PROVIDER_MARKER" * 30]
)
async def test_invalid_provider_ids_raise_safe_typed_errors(item_id):
    file = fixture("children.json")["value"][0]
    async with graph(
        lambda _: httpx2.Response(200, json={"value": [{**file, "id": item_id}]})
    ) as client:
        with pytest.raises(IntegrationValidationError) as caught:
            await list_children(client, drive_id="drive")
    assert caught.value.user_message == "SharePoint returned invalid item metadata."
    assert caught.value.provider_key == "sharepoint"
    assert caught.value.operation == "list_folder"
    assert caught.value.__suppress_context__ is True


@pytest.mark.parametrize("length", [None, 8192, 8193])
async def test_citation_urls_are_complete_or_rejected(length):
    file = fixture("children.json")["value"][0]
    prefix = "https://example.sharepoint.com/"
    url = prefix + (quote("界" * 250 + ".txt") if length is None else "a" * (length - len(prefix)))
    async with graph(
        lambda _: httpx2.Response(200, json={"value": [{**file, "webUrl": url}]})
    ) as client:
        if length == 8193:
            with pytest.raises(IntegrationValidationError, match="citation URL") as caught:
                await list_children(client, drive_id="drive")
            assert url not in str(caught.value)
            assert caught.value.operation == "list_folder"
        else:
            result = await list_children(client, drive_id="drive")
            assert result["items"][0]["web_url"].content == url
