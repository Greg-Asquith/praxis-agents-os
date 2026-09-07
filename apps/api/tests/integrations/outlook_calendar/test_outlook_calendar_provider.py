# apps/api/tests/integrations/outlook_calendar/test_outlook_calendar_provider.py

"""Outlook Calendar package configuration and discovery coverage."""

import json
from pathlib import Path

import pytest

from integrations.outlook_calendar import OUTLOOK_CALENDAR_OAUTH_SCOPES, PROVIDER

FIXTURES = Path(__file__).with_name("fixtures")
TENANT_ID = "b2c4d170-11e8-43a7-943e-a758a11b48d4"
USER_ID = "3a1c8019-6e25-4f52-8035-d2fa75a42cc1"


def _fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text())


def test_outlook_calendar_manifest() -> None:
    assert PROVIDER.manifest.oauth_scopes == OUTLOOK_CALENDAR_OAUTH_SCOPES
    assert PROVIDER.manifest.resource_types == ("outlook_calendar",)


async def test_outlook_calendar_discovers_editable_and_read_only_calendars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from integrations.outlook_calendar import discover_resources as exported_discovery

    module = __import__(exported_discovery.__module__, fromlist=["MicrosoftGraphClient"])

    class Client:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def get(self, path: str, **_kwargs):
            return _fixture("me.json" if path == "/me" else "mailbox_settings.json")

        async def paginate(self, *_args, **_kwargs):
            return _fixture("calendars.json")["value"]

    monkeypatch.setattr(module, "MicrosoftGraphClient", Client)
    resources = await exported_discovery("token")

    assert [resource.display_name for resource in resources] == ["Calendar", "Team calendar"]
    assert [resource.writable for resource in resources] == [True, False]
    assert all(resource.required_write_scopes == ("Calendars.ReadWrite",) for resource in resources)
    assert resources[0].permissions_metadata == {
        "is_default": True,
        "mailbox_id": USER_ID,
        "can_view_private_items": True,
        "owner_address": "person@example.com",
        "time_zone": "GMT Standard Time",
    }


async def test_outlook_calendar_omits_missing_optional_mailbox_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from integrations.outlook_calendar import discover_resources as exported_discovery

    module = __import__(exported_discovery.__module__, fromlist=["MicrosoftGraphClient"])

    class Client:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def get(self, path: str, **_kwargs):
            return _fixture("me.json") if path == "/me" else {}

        async def paginate(self, *_args, **_kwargs):
            return _fixture("calendars.json")["value"][:1]

    monkeypatch.setattr(module, "MicrosoftGraphClient", Client)
    resources = await exported_discovery("token")
    assert "time_zone" not in (resources[0].permissions_metadata or {})
