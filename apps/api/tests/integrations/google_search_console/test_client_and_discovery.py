"""Google Search Console REST client and site discovery contracts."""

import httpx2
import pytest

from core.exceptions.integration import IntegrationAuthError, IntegrationValidationError
from integrations.google_search_console.client import (
    GoogleSearchConsoleClient,
    normalize_site_url,
    site_path,
)
from integrations.google_search_console.discover_resources import (
    WEBMASTERS_SCOPE,
    discover_google_search_console_sites,
)
from services.integrations.http import IntegrationRequestPolicy
from tests.integrations.google_search_console.support import sites_transport, static_token


async def test_client_sends_only_bearer_authorization() -> None:
    seen_headers: list[httpx2.Headers] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen_headers.append(request.headers)
        return httpx2.Response(200, json={"siteEntry": []}, request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        await GoogleSearchConsoleClient(static_token, client=http_client).webmasters_get(
            "sites",
            operation="list_sites",
            policy=IntegrationRequestPolicy.READ,
        )

    assert seen_headers[0]["Authorization"] == "Bearer access-token"
    assert "developer-token" not in seen_headers[0]
    assert "login-customer-id" not in seen_headers[0]


async def test_sites_transport_serves_the_single_discovery_response() -> None:
    async with httpx2.AsyncClient(
        transport=sites_transport(
            [{"siteUrl": "sc-domain:example.com", "permissionLevel": "siteOwner"}]
        )
    ) as http_client:
        payload = await GoogleSearchConsoleClient(static_token, client=http_client).webmasters_get(
            "sites",
            operation="list_sites",
            policy=IntegrationRequestPolicy.READ,
        )

    assert payload["siteEntry"][0]["siteUrl"] == "sc-domain:example.com"


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


async def test_client_rejects_non_json_unless_empty_response_is_allowed() -> None:
    def non_json(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=b"not-json", request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(non_json)) as http_client:
        with pytest.raises(IntegrationValidationError, match="invalid JSON"):
            await GoogleSearchConsoleClient(static_token, client=http_client).webmasters_get(
                "sites",
                operation="list_sites",
                policy=IntegrationRequestPolicy.READ,
            )

    def empty(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(204, request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(empty)) as http_client:
        result = await GoogleSearchConsoleClient(static_token, client=http_client).webmasters_put(
            "sites/site/sitemaps/map",
            operation="submit_sitemap",
            policy=IntegrationRequestPolicy.MUTATION,
            allow_empty=True,
        )
    assert result is None


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
    ("value", "expected"),
    [
        (" sc-domain:Example.COM ", "sc-domain:example.com"),
        ("HTTPS://WWW.Example.COM/path/", "https://www.example.com/path/"),
    ],
)
def test_normalize_site_url(value: str, expected: str) -> None:
    assert normalize_site_url(value) == expected


@pytest.mark.parametrize(
    "value",
    ["", "sc-domain:", "sc-domain:example.com/path", "example.com", "https://example.com"],
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


async def test_discovery_accepts_an_empty_site_list() -> None:
    class EmptyClient:
        async def webmasters_get(self, *_args, **_kwargs):
            return {}

    assert await discover_google_search_console_sites(EmptyClient()) == ()


async def test_discovery_rejects_an_invalid_sites_response() -> None:
    class InvalidClient:
        async def webmasters_get(self, *_args, **_kwargs):
            return {"siteEntry": {}}

    with pytest.raises(IntegrationValidationError, match="invalid sites response"):
        await discover_google_search_console_sites(InvalidClient())
