# apps/api/tests/integrations/outlook_mail/test_outlook_mail_provider.py

"""Outlook Mail package configuration and discovery coverage."""

import json
from pathlib import Path

import pytest

from core.exceptions.integration import IntegrationValidationError
from core.settings import settings
from integrations.outlook_mail import OUTLOOK_MAIL_OAUTH_SCOPES, PROVIDER, oauth_config
from integrations.outlook_mail.settings import outlook_mail_settings
from services.integrations.plugin import IntegrationDiscoveryResult

FIXTURES = Path(__file__).with_name("fixtures")
TENANT_ID = "b2c4d170-11e8-43a7-943e-a758a11b48d4"


def _fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text())


def test_outlook_mail_manifest() -> None:
    assert PROVIDER.manifest.oauth_scopes == OUTLOOK_MAIL_OAUTH_SCOPES
    assert PROVIDER.manifest.resource_types == ("outlook_mailbox",)


def test_outlook_mail_tenant_override_wins_and_invalid_tenants_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(outlook_mail_settings, "OUTLOOK_MAIL_OAUTH_CLIENT_ID", "mail-client")
    monkeypatch.setattr(outlook_mail_settings, "OUTLOOK_MAIL_OAUTH_TENANT", "organizations")
    monkeypatch.setattr(settings, "MICROSOFT_GRAPH_TENANT", TENANT_ID)
    assert "/organizations/" in oauth_config().authorization_url

    monkeypatch.setattr(outlook_mail_settings, "OUTLOOK_MAIL_OAUTH_TENANT", "common")
    with pytest.raises(ValueError, match="identify an organization"):
        oauth_config()


async def test_outlook_mail_discovers_one_writable_mailbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from integrations.outlook_mail import discover_resources as exported_discovery

    module = __import__(exported_discovery.__module__, fromlist=["MicrosoftGraphClient"])

    class Client:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def get(self, path: str, **_kwargs):
            return _fixture("me.json" if path == "/me" else "mailbox_settings.json")

    monkeypatch.setattr(module, "MicrosoftGraphClient", Client)
    resources = await exported_discovery("token")

    assert isinstance(resources, tuple)
    assert len(resources) == 1
    resource = resources[0]
    assert resource.external_id == _fixture("me.json")["id"]
    assert resource.display_name == "person@example.com"
    assert resource.writable is True
    assert resource.required_write_scopes == ("Mail.ReadWrite", "Mail.Send")
    assert resource.permissions_metadata == {
        "user_principal_name": "person@example.com",
        "time_zone": "GMT Standard Time",
    }


async def test_outlook_mail_omits_missing_optional_mailbox_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from integrations.outlook_mail import discover_resources as exported_discovery

    module = __import__(exported_discovery.__module__, fromlist=["MicrosoftGraphClient"])

    class Client:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def get(self, path: str, **_kwargs):
            return _fixture("me.json") if path == "/me" else {}

    monkeypatch.setattr(module, "MicrosoftGraphClient", Client)
    resources = await exported_discovery("token")

    assert resources[0].permissions_metadata == {"user_principal_name": "person@example.com"}


async def test_outlook_mail_records_mailbox_unavailability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from integrations.outlook_mail import discover_resources as exported_discovery

    module = __import__(exported_discovery.__module__, fromlist=["MicrosoftGraphClient"])

    class Client:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def get(self, path: str, **_kwargs):
            if path == "/me":
                return _fixture("me.json")
            raise IntegrationValidationError(
                "Mailbox unavailable",
                error_code="mailbox_unavailable",
            )

    monkeypatch.setattr(module, "MicrosoftGraphClient", Client)
    result = await exported_discovery("token")

    assert isinstance(result, IntegrationDiscoveryResult)
    assert result.resources == ()
    assert result.degraded_reason == "mailbox_unavailable"
