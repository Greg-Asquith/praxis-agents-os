"""Google Search Console REST client and site discovery contracts."""

import httpx2
import pytest

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationPermissionError,
    IntegrationValidationError,
)
from integrations.google_search_console.client import (
    GoogleSearchConsoleClient,
    _raise_indexing_permission_error,
    normalize_site_url,
    site_path,
)
from integrations.google_search_console.discover_resources import (
    WEBMASTERS_SCOPE,
    discover_google_search_console_sites,
)
from services.integrations.http import IntegrationRequestPolicy
from tests.integrations.google_search_console.support import static_token


async def test_indexing_client_uses_the_indexing_api_base_and_query_encoding() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(
            200,
            json={
                "url": "https://example.com/jobs/one",
                "latestUpdate": {
                    "type": "URL_UPDATED",
                    "notifyTime": "2026-09-03T12:00:00Z",
                },
            },
            request=request,
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        await GoogleSearchConsoleClient(static_token, client=http_client).indexing_get(
            "urlNotifications/metadata",
            operation="get_url_notification_metadata",
            policy=IntegrationRequestPolicy.READ,
            params={"url": "https://example.com/jobs/one"},
        )

    assert seen[0].url.host == "indexing.googleapis.com"
    assert seen[0].url.path == "/v3/urlNotifications/metadata"
    assert seen[0].url.params["url"] == "https://example.com/jobs/one"


def test_indexing_permission_error_retains_google_ownership_denial() -> None:
    request = httpx2.Request("POST", "https://indexing.googleapis.com/v3/urlNotifications:publish")
    response = httpx2.Response(
        403,
        json={
            "error": {
                "code": 403,
                "message": "Permission denied. Failed to verify the URL ownership.",
                "status": "PERMISSION_DENIED",
            }
        },
        request=request,
    )

    with pytest.raises(IntegrationPermissionError) as exc_info:
        _raise_indexing_permission_error(response, operation="publish_url_notification")

    assert "Failed to verify the URL ownership" in exc_info.value.user_message


async def test_client_refreshes_once_after_auth_rejection_then_fails() -> None:
    force_values: list[bool] = []

    async def access_token(force: bool) -> str:
        force_values.append(force)
        return "still-invalid"

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(401, json={}, request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        with pytest.raises(IntegrationAuthError) as exc_info:
            await GoogleSearchConsoleClient(access_token, client=http_client).webmasters_get(
                "sites",
                operation="list_sites",
                policy=IntegrationRequestPolicy.READ,
            )

    assert force_values == [False, True]
    assert exc_info.value.original_error is None


async def test_client_extracts_and_bounds_google_error_detail() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            400,
            json={
                "error": {
                    "message": " invalid property " + "x" * 1200,
                    "status": "INVALID_ARGUMENT",
                    "details": [{"reason": "SITE_NOT_FOUND"}],
                }
            },
            request=request,
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        with pytest.raises(IntegrationValidationError) as exc_info:
            await GoogleSearchConsoleClient(static_token, client=http_client).inspection_post(
                "urlInspection/index:inspect",
                operation="inspect_url",
                policy=IntegrationRequestPolicy.READ,
                json={},
            )

    assert exc_info.value.user_message.startswith(
        "Google Search Console rejected inspect_url: invalid property"
    )
    assert len(exc_info.value.user_message) <= 1000
    assert exc_info.value.original_error is None


@pytest.mark.parametrize(
    "value",
    [
        "",
        "sc-domain:",
    ],
)
def test_normalize_site_url_rejects_invalid_values(value: str) -> None:
    with pytest.raises(IntegrationValidationError, match="ending in '/'"):
        normalize_site_url(value)


def test_site_path_encodes_domain_and_url_prefix_identifiers() -> None:
    assert site_path("sc-domain:example.com") == "sites/sc-domain%3Aexample.com"
    assert site_path("https://www.example.com/") == ("sites/https%3A%2F%2Fwww.example.com%2F")


async def test_discovery_filters_deduplicates_sorts_and_maps_permissions() -> None:
    class DiscoveryClient:
        async def webmasters_get(self, path: str, **kwargs):
            assert path == "sites"
            assert kwargs == {
                "operation": "list_sites",
                "policy": IntegrationRequestPolicy.READ,
            }
            return {
                "siteEntry": [
                    {
                        "siteUrl": "https://z.example.com/",
                        "permissionLevel": "siteRestrictedUser",
                    },
                    {"siteUrl": "sc-domain:B.example", "permissionLevel": "siteFullUser"},
                    {"siteUrl": "sc-domain:a.example", "permissionLevel": "siteOwner"},
                    {"siteUrl": "sc-domain:a.example", "permissionLevel": "siteRestrictedUser"},
                    {
                        "siteUrl": "sc-domain:hidden.example",
                        "permissionLevel": "siteUnverifiedUser",
                    },
                    {"permissionLevel": "siteOwner"},
                ]
            }

    resources = await discover_google_search_console_sites(DiscoveryClient())

    assert [resource.external_id for resource in resources] == [
        "sc-domain:a.example",
        "sc-domain:b.example",
        "https://z.example.com/",
    ]
    assert resources[0].display_name == "a.example"
    assert resources[0].writable is True
    assert resources[0].required_write_scopes == (WEBMASTERS_SCOPE,)
    assert resources[0].permissions_metadata == {
        "permission_level": "siteOwner",
        "property_type": "domain",
    }
    assert resources[1].writable is False
    assert resources[1].required_write_scopes == ()
    assert resources[2].writable is False
    assert resources[2].required_write_scopes == ()
    assert resources[2].permissions_metadata == {
        "permission_level": "siteRestrictedUser",
        "property_type": "url_prefix",
    }
