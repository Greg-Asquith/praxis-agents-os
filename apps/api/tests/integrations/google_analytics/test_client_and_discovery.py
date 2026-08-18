"""Google Analytics REST client and property discovery contracts."""

import json
from importlib import import_module
from types import SimpleNamespace

import httpx2
import pytest

from core.exceptions.integration import (
    IntegrationAuthError,
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


async def test_client_sends_only_bearer_authorization() -> None:
    seen_headers: list[httpx2.Headers] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen_headers.append(request.headers)
        return httpx2.Response(200, json={"accountSummaries": []}, request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        await GoogleAnalyticsClient(static_token, client=http_client).admin_get(
            "accountSummaries",
            operation="list_account_summaries",
            policy=IntegrationRequestPolicy.READ,
        )

    assert seen_headers[0]["Authorization"] == "Bearer access-token"
    assert "developer-token" not in seen_headers[0]
    assert "login-customer-id" not in seen_headers[0]


async def test_client_refreshes_once_after_auth_rejection_then_fails() -> None:
    force_values: list[bool] = []

    async def access_token(force: bool) -> str:
        force_values.append(force)
        return "still-invalid"

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(401, json={}, request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        with pytest.raises(IntegrationAuthError) as exc_info:
            await GoogleAnalyticsClient(access_token, client=http_client).admin_get(
                "accountSummaries",
                operation="list_account_summaries",
                policy=IntegrationRequestPolicy.READ,
            )

    assert force_values == [False, True]
    assert exc_info.value.original_error is None


async def test_client_rejects_non_json_response() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=b"not-json", request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        with pytest.raises(IntegrationValidationError, match="invalid JSON"):
            await GoogleAnalyticsClient(static_token, client=http_client).data_get(
                "properties/123/metadata",
                operation="get_metadata",
                policy=IntegrationRequestPolicy.READ,
            )


async def test_client_extracts_and_bounds_google_error_detail() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            400,
            json={
                "error": {
                    "message": " invalid   dimension " + "x" * 1200,
                    "status": "INVALID_ARGUMENT",
                    "details": [{"reason": "FIELD_NOT_FOUND"}],
                }
            },
            request=request,
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        with pytest.raises(IntegrationValidationError) as exc_info:
            await GoogleAnalyticsClient(static_token, client=http_client).data_post(
                "properties/123:runReport",
                operation="run_report",
                policy=IntegrationRequestPolicy.READ,
                json={},
            )

    assert exc_info.value.user_message.startswith(
        "Google Analytics rejected run_report: invalid dimension"
    )
    assert len(exc_info.value.user_message) <= 1000
    assert exc_info.value.original_error is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [("123456", "123456"), (" properties/987 ", "987")],
)
def test_normalize_property_id(value: str, expected: str) -> None:
    assert normalize_property_id(value) == expected


@pytest.mark.parametrize("value", ["", "properties/", "G-ABC", "properties/12x"])
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


async def test_discovery_accepts_an_empty_account_list() -> None:
    class EmptyClient:
        async def admin_get_paged(self, *_args, **_kwargs):
            return ()

    assert await discover_google_analytics_properties(EmptyClient()) == ()


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
