"""Google Analytics REST client and property discovery contracts."""

import json
from importlib import import_module
from types import SimpleNamespace

import pytest

from core.exceptions.integration import (
    IntegrationValidationError,
)
from integrations.google_analytics.client import (
    GoogleAnalyticsClient,
    normalize_property_id,
)
from integrations.google_analytics.discover_resources import (
    ANALYTICS_READONLY_SCOPE,
    discover_google_analytics_properties,
    discover_resources,
)
from services.integrations.http import IntegrationRequestPolicy
from tests.integrations.google_analytics.support import static_token


@pytest.mark.parametrize(
    "value",
    [
        "",
        "properties/",
    ],
)
def test_normalize_property_id_rejects_non_numeric_values(value: str) -> None:
    with pytest.raises(IntegrationValidationError, match="digits only"):
        normalize_property_id(value)


async def test_discovery_pages_deduplicates_sorts_and_preserves_account_metadata() -> None:
    calls: list[dict[str, object]] = []

    class DiscoveryClient:
        async def admin_get(self, path: str, **kwargs):
            assert path == "accountSummaries"
            assert kwargs["policy"] is IntegrationRequestPolicy.READ
            params = kwargs["params"]
            calls.append(params)
            if "pageToken" not in params:
                return {
                    "accountSummaries": [
                        {
                            "account": "accounts/20",
                            "displayName": "Zulu account",
                            "propertySummaries": [
                                {
                                    "property": "properties/222",
                                    "displayName": "Store",
                                    "propertyType": "PROPERTY_TYPE_ORDINARY",
                                }
                            ],
                        }
                    ],
                    "nextPageToken": "page-2",
                }
            return {
                "accountSummaries": [
                    {
                        "account": "accounts/10",
                        "displayName": "Alpha account",
                        "propertySummaries": [
                            {
                                "property": "properties/111",
                                "displayName": "Website",
                                "propertyType": "PROPERTY_TYPE_ORDINARY",
                            },
                            {
                                "property": "properties/222",
                                "displayName": "Duplicate loses",
                            },
                            {"property": "properties/not-a-number", "displayName": "Invalid"},
                        ],
                    }
                ]
            }

    client = GoogleAnalyticsClient(static_token)
    client.admin_get = DiscoveryClient().admin_get
    resources = await discover_google_analytics_properties(client)

    assert [resource.external_id for resource in resources] == ["111", "222"]
    assert resources[0].permissions_metadata == {
        "account_id": "10",
        "account_display_name": "Alpha account",
        "property_type": "PROPERTY_TYPE_ORDINARY",
        "resource_name": "properties/111",
    }
    assert resources[0].resource_type == "google_analytics_property"
    assert resources[0].parent_external_id is None
    assert resources[0].writable is False
    assert resources[1].display_name == "Store"
    assert calls == [
        {"pageSize": 200},
        {"pageSize": 200, "pageToken": "page-2"},
    ]


async def test_admin_paging_rejects_repeated_tokens_and_page_cap() -> None:
    class RepeatingClient:
        async def admin_get(self, *_args, **_kwargs):
            return {"accountSummaries": [], "nextPageToken": "same"}

    client = GoogleAnalyticsClient(static_token)
    client.admin_get = RepeatingClient().admin_get
    with pytest.raises(IntegrationValidationError, match="repeated"):
        await client.admin_get_paged(
            "accountSummaries", items_key="accountSummaries", page_size=200, max_pages=25
        )

    class EndlessClient:
        page = 0

        async def admin_get(self, *_args, **_kwargs):
            self.page += 1
            return {"accountSummaries": [], "nextPageToken": f"page-{self.page}"}

    client.admin_get = EndlessClient().admin_get
    with pytest.raises(IntegrationValidationError, match="page limit"):
        await client.admin_get_paged(
            "accountSummaries", items_key="accountSummaries", page_size=200, max_pages=2
        )


async def test_service_account_discovery_uses_readonly_scope(monkeypatch) -> None:
    captured: dict[str, object] = {}
    module = import_module("integrations.google_analytics.discover_resources")

    class TokenProvider:
        def __init__(self, credentials, *, provider_key: str, scope: str) -> None:
            captured.update(credentials=credentials, provider_key=provider_key, scope=scope)

        async def access_token(self, _force: bool = False) -> str:
            return "service-account-token"

    async def fake_discovery(client: GoogleAnalyticsClient):
        captured["client"] = client
        return ()

    monkeypatch.setattr(module, "GoogleServiceAccountTokenProvider", TokenProvider)
    monkeypatch.setattr(
        module,
        "parse_google_service_account_json",
        lambda raw, *, provider_key: SimpleNamespace(raw=raw, provider_key=provider_key),
    )
    monkeypatch.setattr(module, "discover_google_analytics_properties", fake_discovery)

    assert await discover_resources(json.dumps({"type": "service_account"})) == ()
    assert captured["provider_key"] == "google_analytics"
    assert captured["scope"] == ANALYTICS_READONLY_SCOPE
