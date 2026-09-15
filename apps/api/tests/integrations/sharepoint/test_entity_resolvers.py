# apps/api/tests/integrations/sharepoint/test_entity_resolvers.py

"""Exact SharePoint reference resolution stays within selected libraries."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx2
import pytest

from core.exceptions.integration import IntegrationValidationError
from integrations.sharepoint.entity_resolvers.drive_item import resolve_items, search_items
from integrations.sharepoint.operations.utils import item_result
from integrations.sharepoint.references import SharePointDriveItemReference
from tests.integrations.sharepoint.support import context, entry, fixture, graph


@pytest.mark.parametrize("change", [{"file": None}, {"size": -1}, {"webUrl": "x" * 8193}])
async def test_exact_resolution_preserves_metadata_error_operation(monkeypatch, change):
    file = fixture("children.json")["value"][0]
    errors = []

    def project(*args, **kwargs):
        try:
            return item_result(*args, **kwargs)
        except IntegrationValidationError as exc:
            errors.append(exc)
            raise

    monkeypatch.setattr("integrations.sharepoint.entity_resolvers.drive_item.item_result", project)
    ctx = SimpleNamespace(
        active_context=context(entry()).deps.active_context,
        db=object(),
        actor=object(),
        workspace=object(),
    )
    async with graph(lambda _: httpx2.Response(200, json={**file, **change})) as provider:
        monkeypatch.setattr(
            "integrations.sharepoint.entity_resolvers.drive_item.drive_client_for_principal",
            AsyncMock(return_value=provider),
        )
        value = SharePointDriveItemReference(drive_id="drive", item_id="file").model_dump()
        assert await resolve_items(ctx, [value], {}) == ()
    assert len(errors) == 1 and errors[0].operation == "get_item"


@pytest.mark.parametrize("drives", [(), ("other",), ("drive", "drive")])
async def test_resolver_skips_missing_and_ambiguous_drives(monkeypatch, drives):
    client = AsyncMock()
    monkeypatch.setattr(
        "integrations.sharepoint.entity_resolvers.drive_item.drive_client_for_principal", client
    )
    ctx = SimpleNamespace(
        active_context=context(*(entry(drive) for drive in drives)).deps.active_context
    )
    value = SharePointDriveItemReference(drive_id="drive", item_id="folder").model_dump()
    assert await resolve_items(ctx, [value, {}], {}) == ()
    client.assert_not_awaited()


@pytest.mark.parametrize("status", [200, 404])
async def test_resolver_refreshes_bounded_exact_references(monkeypatch, status):
    selected = entry()
    ctx = SimpleNamespace(
        active_context=context(selected).deps.active_context,
        db=object(),
        actor=object(),
        workspace=object(),
    )
    file = fixture("children.json")["value"][0]
    async with graph(lambda _: httpx2.Response(status, json=file)) as provider:
        client = AsyncMock(return_value=provider)
        monkeypatch.setattr(
            "integrations.sharepoint.entity_resolvers.drive_item.drive_client_for_principal", client
        )
        value = SharePointDriveItemReference(
            drive_id="drive", item_id="file", name="Stale"
        ).model_dump()
        result = await resolve_items(ctx, [value] * 30, {})
    assert client.await_count == 25
    assert len(result) == (25 if status == 200 else 0)
    for choice in result:
        assert choice.value["item_id"] == "file" and choice.value["drive_id"] == "drive"
        assert choice.label == choice.value["name"] == file["name"]
        assert choice.value["kind"] == "file"


@pytest.mark.parametrize("drives", [(), ("drive", "drive")])
async def test_search_skips_missing_and_ambiguous_drives(monkeypatch, drives):
    client = AsyncMock()
    monkeypatch.setattr(
        "integrations.sharepoint.entity_resolvers.drive_item.drive_client_for_principal", client
    )
    ctx = SimpleNamespace(
        active_context=context(*(entry(drive) for drive in drives)).deps.active_context
    )
    assert (await search_items(ctx, "Report", {}, 25, None)).choices == ()
    client.assert_not_awaited()


@pytest.mark.parametrize("query", ["Report", ""])
@pytest.mark.parametrize("cursor,expected,next_cursor", [(None, 20, "20"), ("20", 5, None)])
async def test_search_bounds_name_choices_across_selected_drives(
    monkeypatch, query, cursor, expected, next_cursor
):
    selected = entry()
    ctx = SimpleNamespace(
        active_context=context(selected, entry("second"), entry("third")).deps.active_context,
        db=object(),
        actor=object(),
        workspace=object(),
    )
    file, folder = fixture("children.json")["value"]
    requests = []

    def handler(request):
        requests.append(request.url.path)
        drive_id = "second" if "/second/" in request.url.path else "drive"
        limit = int(request.url.params["$top"])
        rows = [
            {
                **(file if i % 2 else folder),
                "id": f"item-{i}",
                "name": f"REPORT {i}",
                "parentReference": {"driveId": drive_id},
            }
            for i in range(min(15, limit))
        ]
        return httpx2.Response(200, json={"value": rows})

    async with graph(handler) as provider:
        client = AsyncMock(return_value=provider)
        monkeypatch.setattr(
            "integrations.sharepoint.entity_resolvers.drive_item.drive_client_for_principal", client
        )
        page = await search_items(ctx, query, {}, 20, cursor)
    assert len(page.choices) == expected and page.next_cursor == next_cursor
    assert len(requests) == client.await_count == 2
    assert all("/third/" not in path for path in requests)
    assert {choice.value["kind"] for choice in page.choices} == {"file", "folder"}
    assert all(choice.value["drive_id"] in {"drive", "second"} for choice in page.choices)
    assert all(choice.scope_label == selected.display_name for choice in page.choices)


async def test_name_search_excludes_content_only_matches_and_unselected_drives(monkeypatch):
    ctx = SimpleNamespace(
        active_context=context(entry()).deps.active_context,
        db=object(),
        actor=object(),
        workspace=object(),
    )
    file = fixture("children.json")["value"][0]

    def handler(request):
        assert request.url.path == "/v1.0/drives/drive/root/search(q='Report')"
        return httpx2.Response(
            200,
            json={
                "value": [
                    {**file, "name": "Unrelated"},
                    {**file, "name": "Report", "parentReference": {"driveId": "unselected"}},
                    {**file, "name": "Annual REPORT"},
                ]
            },
        )

    async with graph(handler) as provider:
        monkeypatch.setattr(
            "integrations.sharepoint.entity_resolvers.drive_item.drive_client_for_principal",
            AsyncMock(return_value=provider),
        )
        page = await search_items(ctx, "Report", {}, 25, None)
    assert [choice.label for choice in page.choices] == ["Annual REPORT"]
