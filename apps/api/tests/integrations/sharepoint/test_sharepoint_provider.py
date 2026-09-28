# apps/api/tests/integrations/sharepoint/test_sharepoint_provider.py

"""SharePoint package configuration and bounded discovery coverage."""

import json
from pathlib import Path

import pytest

from core.exceptions.integration import (
    IntegrationConnectionError,
    IntegrationNotFoundError,
)
from integrations.sharepoint.settings import sharepoint_settings
from services.integrations.plugin import IntegrationDiscoveryResult

FIXTURES = Path(__file__).with_name("fixtures")


def _fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text())


async def test_sharepoint_discovers_onedrive_then_followed_and_accessible_sites(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from integrations.sharepoint import discover_resources as exported_discovery

    module = __import__(exported_discovery.__module__, fromlist=["MicrosoftGraphClient"])
    client_options: dict[str, object] = {}

    class Client:
        def __init__(self, *_args, **kwargs) -> None:
            client_options.update(kwargs)

        async def get(self, *_args, **_kwargs):
            return _fixture("drive.json")

        async def paginate(self, path: str, **_kwargs):
            if path == "/me/followedSites":
                return _fixture("followed_sites.json")["value"]
            if path == "/sites":
                return _fixture("sites_search.json")["value"]
            drives = _fixture("site_drives.json")["value"]
            if "accessible" in path:
                return [{**drives[0], "id": "drive-accessible"}]
            return drives

    monkeypatch.setattr(module, "MicrosoftGraphClient", Client)
    resources = await exported_discovery("token", pacing_key="connection-key")

    assert isinstance(resources, tuple)
    assert [resource.external_id for resource in resources] == [
        "drive-personal",
        "drive-documents",
        "drive-accessible",
    ]
    assert [resource.display_name for resource in resources] == [
        "OneDrive",
        "Followed site › Documents",  # noqa: RUF001
        "Accessible site › Documents",  # noqa: RUF001
    ]
    assert resources[1].permissions_metadata["followed"] is True
    assert resources[2].permissions_metadata["followed"] is False
    assert all(resource.writable for resource in resources)
    assert all(
        resource.required_write_scopes == ("Files.ReadWrite.All", "Sites.ReadWrite.All")
        for resource in resources
    )
    assert client_options["pacing_key"] == "connection-key"
    assert client_options["client"] is not None


async def test_sharepoint_missing_onedrive_continues_with_site_libraries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from integrations.sharepoint import discover_resources as exported_discovery

    module = __import__(exported_discovery.__module__, fromlist=["MicrosoftGraphClient"])

    class Client:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def get(self, *_args, **_kwargs):
            raise IntegrationNotFoundError("No OneDrive")

        async def paginate(self, path: str, **_kwargs):
            if path == "/me/followedSites":
                return _fixture("followed_sites.json")["value"]
            if path == "/sites":
                return []
            return _fixture("site_drives.json")["value"]

    monkeypatch.setattr(module, "MicrosoftGraphClient", Client)
    result = await exported_discovery("token")

    assert isinstance(result, IntegrationDiscoveryResult)
    assert result.degraded_reason == "onedrive_unavailable"
    assert [resource.external_id for resource in result.resources] == ["drive-documents"]


async def test_sharepoint_preserves_one_failed_site_and_records_partial_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from integrations.sharepoint import discover_resources as exported_discovery

    module = __import__(exported_discovery.__module__, fromlist=["MicrosoftGraphClient"])
    monkeypatch.setattr(sharepoint_settings, "SHAREPOINT_DISCOVERY_MAX_SITES", 1)

    class Client:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def get(self, *_args, **_kwargs):
            return _fixture("drive.json")

        async def paginate(self, path: str, **_kwargs):
            if path == "/me/followedSites":
                return _fixture("followed_sites.json")["value"]
            if path.startswith("/sites/"):
                raise IntegrationConnectionError("Site unavailable")
            return []

    monkeypatch.setattr(module, "MicrosoftGraphClient", Client)
    result = await exported_discovery("token")

    assert isinstance(result, IntegrationDiscoveryResult)
    assert result.degraded_reason == "sharepoint_site_discovery_partial"
    assert result.preserved_parent_external_ids == frozenset(
        {"example.sharepoint.com,followed,web"}
    )
    assert [resource.external_id for resource in result.resources] == ["drive-personal"]
