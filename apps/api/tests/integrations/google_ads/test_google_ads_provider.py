# apps/api/tests/integrations/google_ads/test_google_ads_provider.py

"""Google Ads discovery, REST operation, and service-account contracts."""

import json
from urllib.parse import parse_qs

import httpx2
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)
from pydantic import SecretStr
from pydantic_ai import ModelRetry

from integrations.google_ads.client import GoogleAdsClient
from integrations.google_ads.discover_resources import discover_google_ads_resources
from integrations.google_ads.operations.run_report import run_report
from integrations.google_ads.operations.update_campaign_status import update_campaign_status
from integrations.google_ads.tools.run_report import google_ads_run_report
from services.integrations.credentials.google_service_account import (
    GOOGLE_TOKEN_URL,
    GoogleServiceAccountTokenProvider,
    parse_google_service_account_json,
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
    hierarchy_queries = [
        call for call in client.calls if "customer_user_access" not in call["query"]
    ]
    assert [call["path"] for call in hierarchy_queries] == [
        "customers/111/googleAds:searchStream",
        "customers/222/googleAds:searchStream",
    ]


async def test_report_caps_rows_and_preserves_plain_provider_values() -> None:
    client = _OperationClient(
        [{"results": [{"campaign": {"name": "one"}}, {"campaign": {"name": "two"}}]}]
    )
    result = await run_report(
        client,
        customer_id="333",
        login_customer_id="111",
        query="SELECT campaign.name FROM campaign",
        max_rows=1,
    )
    assert result["row_count"] == 1
    assert result["truncated"] is True
    assert result["rows"][0]["campaign"]["name"] == "one"
    assert client.last_json["query"].endswith("LIMIT 2")


async def test_report_tool_rejects_non_select_gaql_before_dispatch() -> None:
    with pytest.raises(ModelRetry, match="requires a GAQL SELECT query"):
        await google_ads_run_report(None, "UPDATE campaign SET status = 'PAUSED'")  # type: ignore[arg-type]


async def test_mutate_uses_partial_failure_and_surfaces_campaign_error() -> None:
    payload = {
        "results": [{"resourceName": "customers/333/campaigns/10"}],
        "partialFailureError": {
            "details": [
                {
                    "errors": [
                        {
                            "message": "Campaign is removed",
                            "errorCode": {"campaignError": "CANNOT_MODIFY_REMOVED_CAMPAIGN"},
                            "location": {
                                "fieldPathElements": [{"fieldName": "operations", "index": 1}]
                            },
                        }
                    ]
                }
            ]
        },
    }
    client = _OperationClient(payload)
    result = await update_campaign_status(
        client,
        customer_id="333",
        login_customer_id="111",
        campaign_ids=["10", "20"],
        status="PAUSED",
    )
    assert client.last_json["partialFailure"] is True
    assert client.last_login_customer_id == "111"
    assert result["resource_names"] == ["customers/333/campaigns/10"]
    assert result["campaign_errors"][0]["campaign_id"] == "20"


async def test_service_account_assertion_claims_and_token_cache() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
    ).decode()
    raw = json.dumps(
        {
            "type": "service_account",
            "client_email": "agent@example.iam.gserviceaccount.com",
            "private_key": private_pem,
            "token_uri": GOOGLE_TOKEN_URL,
        }
    )
    assertions: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        form = parse_qs(request.read().decode())
        assertions.append(form["assertion"][0])
        return httpx2.Response(
            200,
            json={"access_token": "short-lived-token", "expires_in": 3600},
            request=request,
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        provider = GoogleServiceAccountTokenProvider(
            parse_google_service_account_json(raw),
            scope="https://www.googleapis.com/auth/adwords",
            client=http_client,
        )
        assert await provider.access_token() == "short-lived-token"
        assert await provider.access_token() == "short-lived-token"

    assert len(assertions) == 1
    claims = jwt.decode(
        assertions[0],
        private_key.public_key(),
        algorithms=["RS256"],
        audience=GOOGLE_TOKEN_URL,
    )
    assert claims["iss"] == "agent@example.iam.gserviceaccount.com"
    assert claims["sub"] == "agent@example.iam.gserviceaccount.com"
    assert claims["scope"] == "https://www.googleapis.com/auth/adwords"
    assert private_pem not in assertions[0]


def test_service_account_validation_never_echoes_secret() -> None:
    secret = "private-key-must-not-leak"
    with pytest.raises(Exception) as exc_info:
        parse_google_service_account_json(json.dumps({"private_key": secret}))
    assert secret not in str(exc_info.value)


async def _static_token(_force: bool) -> str:
    return "access-token"


class _DiscoveryClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def get(self, _path: str, **_kwargs):
        return {"resourceNames": ["customers/111"]}

    async def post(self, path: str, **kwargs):
        query = kwargs["json"]["query"]
        self.calls.append(
            {
                "path": path,
                "login_customer_id": kwargs["login_customer_id"],
                "query": query,
            }
        )
        if "customer_user_access" in query:
            return [
                {
                    "results": [
                        {
                            "customerUserAccess": {
                                "emailAddress": "agent@example.iam.gserviceaccount.com",
                                "accessRole": "STANDARD",
                            }
                        }
                    ]
                }
            ]
        customer_id = path.split("/")[1]
        if customer_id == "111":
            return [_hierarchy_page(("111", 0, True), ("222", 1, True))]
        if customer_id == "222":
            return [_hierarchy_page(("222", 0, True), ("333", 1, False))]
        return [_hierarchy_page((customer_id, 0, False))]


class _OperationClient:
    def __init__(self, payload):
        self.payload = payload
        self.last_json = None
        self.last_login_customer_id = None

    async def post(self, _path: str, **kwargs):
        self.last_json = kwargs["json"]
        self.last_login_customer_id = kwargs["login_customer_id"]
        return self.payload


def _hierarchy_page(*customers: tuple[str, int, bool]) -> dict:
    return {
        "results": [
            {
                "customerClient": {
                    "clientCustomer": f"customers/{customer_id}",
                    "level": str(level),
                    "manager": manager,
                    "descriptiveName": f"Account {customer_id}",
                    "currencyCode": "GBP",
                    "status": "ENABLED",
                }
            }
            for customer_id, level, manager in customers
        ]
    }
