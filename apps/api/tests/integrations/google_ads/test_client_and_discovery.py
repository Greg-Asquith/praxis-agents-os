"""Google Ads client routing and resource discovery contracts."""

import httpx2
from pydantic import SecretStr

from integrations.google_ads.client import GoogleAdsClient
from integrations.google_ads.discover_resources import discover_google_ads_resources
from tests.integrations.google_ads.support import (
    _DiscoveryClient,
    _DuplicateRouteDiscoveryClient,
    _static_token,
)


async def test_client_routes_login_customer_id_from_each_request() -> None:
    seen_headers: list[httpx2.Headers] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen_headers.append(request.headers)
        return httpx2.Response(200, json={"results": []}, request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        client = GoogleAdsClient(
            _static_token,
            developer_token=SecretStr("developer-secret"),
            client=http_client,
        )
        await client.post(
            "customers/333/googleAds:searchStream",
            operation="report",
            login_customer_id="111-111-1111",
            json={"query": "SELECT campaign.id FROM campaign"},
        )

    assert seen_headers[0]["login-customer-id"] == "1111111111"
    assert seen_headers[0]["developer-token"] == "developer-secret"


async def test_discovery_preserves_root_routing_and_immediate_parent() -> None:
    client = _DiscoveryClient()
    resources = await discover_google_ads_resources(
        client,
        principal_email="agent@example.iam.gserviceaccount.com",
    )
    by_id = {resource.external_id: resource for resource in resources}

    assert by_id["111"].parent_external_id is None
    assert by_id["222"].parent_external_id == "111"
    assert by_id["333"].parent_external_id == "222"
    assert by_id["333"].permissions_metadata["login_customer_id"] == "111"
    assert by_id["333"].permissions_metadata["level"] == 2
    assert by_id["111"].writable is False
    assert by_id["222"].writable is False
    assert by_id["333"].writable is True
    assert {call["login_customer_id"] for call in client.calls} == {"111"}
    access_queries = [call for call in client.calls if "customer_user_access" in call["query"]]
    assert [call["path"] for call in access_queries] == ["customers/111/googleAds:searchStream"]
    hierarchy_queries = [
        call for call in client.calls if "customer_user_access" not in call["query"]
    ]
    assert [call["path"] for call in hierarchy_queries] == [
        "customers/111/googleAds:searchStream",
        "customers/222/googleAds:searchStream",
    ]


async def test_discovery_keeps_accounts_read_only_for_read_only_manager_role() -> None:
    resources = await discover_google_ads_resources(
        _DiscoveryClient(manager_access_role="READ_ONLY"),
        principal_email="agent@example.iam.gserviceaccount.com",
    )
    by_id = {resource.external_id: resource for resource in resources}

    assert by_id["333"].writable is False
    assert by_id["333"].permissions_metadata["access_role"] == "READ_ONLY"


async def test_discovery_prefers_writable_manager_route_for_duplicate_account() -> None:
    resources = await discover_google_ads_resources(
        _DuplicateRouteDiscoveryClient(),
        principal_email="agent@example.iam.gserviceaccount.com",
    )
    by_id = {resource.external_id: resource for resource in resources}

    assert by_id["333"].writable is True
    assert by_id["333"].permissions_metadata["login_customer_id"] == "111"
