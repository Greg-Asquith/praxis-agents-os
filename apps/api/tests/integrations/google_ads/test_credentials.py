"""Google Ads service-account credential contracts."""

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

from services.integrations.credentials.google_service_account import (
    GOOGLE_TOKEN_URL,
    GoogleServiceAccountTokenProvider,
    parse_google_service_account_json,
)


async def test_service_account_assertion_claims_and_token_cache() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
    ).decode()
    raw = json.dumps(
        {
            "type": "service_account",
            "project_id": "praxis-ads",
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
            parse_google_service_account_json(raw, provider_key="google_ads"),
            provider_key="google_ads",
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
        parse_google_service_account_json(
            json.dumps({"private_key": secret}),
            provider_key="google_ads",
        )
    assert secret not in str(exc_info.value)
