# apps/api/tests/integrations/sharepoint/test_entity_resolvers.py

"""Exact SharePoint reference resolution stays within selected libraries."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx2
import pytest

from integrations.sharepoint.entity_resolvers.drive_item import resolve_items, search_items
from integrations.sharepoint.references import SharePointDriveItemReference
from tests.integrations.sharepoint.support import context, entry, fixture, graph


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
