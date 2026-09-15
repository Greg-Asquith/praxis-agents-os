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
    assert (await search_items(ctx, "Report", {}, 25, None)).choices == ()
