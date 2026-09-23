"""Complete report streams preserve errors and reject oversized partial results."""

import json

import httpx2
import pytest
from pydantic import SecretStr

from core.exceptions.integration import IntegrationValidationError
from core.settings import settings
from integrations.google_ads.client import GoogleAdsClient
from services.integrations.http import IntegrationRequestPolicy
from tests.integrations.google_ads.support import _static_token


class ReportStream(httpx2.AsyncByteStream):
    def __init__(self, chunks: list[bytes], *, interrupted: bool = False):
        self.chunks = chunks
        self.interrupted = interrupted
        self.read = 0
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.read += 1
            yield chunk
        if self.interrupted:
            raise httpx2.ReadError("Report interrupted")

    async def aclose(self):
        self.closed = True


async def report(client, *, maximum):
    return await client.post(
        "customers/333/googleAds:searchStream",
        operation="run_report",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id="111",
        json={"query": "SELECT campaign.id FROM campaign"},
        max_response_bytes=maximum,
    )


@pytest.mark.parametrize("maximum", [11, 12])
async def test_report_stream_accepts_complete_body_within_byte_limit(maximum):
    stream = ReportStream([b'[{"a":', b"123}]"])
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda request: httpx2.Response(200, stream=stream))
    ) as http:
        client = GoogleAdsClient(_static_token, developer_token=SecretStr("test"), client=http)
        assert await report(client, maximum=maximum) == [{"a": 123}]
    assert stream.closed


async def test_report_stream_fails_before_consuming_rest_of_oversized_body():
    stream = ReportStream([b"[", b" " * 20, b"]"])
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda request: httpx2.Response(200, stream=stream))
    ) as http:
        client = GoogleAdsClient(_static_token, developer_token=SecretStr("test"), client=http)
        with pytest.raises(IntegrationValidationError, match="No partial report was returned"):
            await report(client, maximum=10)
    assert stream.read == 2
    assert stream.closed


async def test_report_stream_retry_discards_interrupted_attempt(monkeypatch):
    monkeypatch.setattr(settings, "INTEGRATIONS_HTTP_RETRY_BACKOFF_FACTOR", 0)
    streams = [ReportStream([b"["], interrupted=True), ReportStream([b"[", b"]"])]
    remaining = iter(streams)
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda request: httpx2.Response(200, stream=next(remaining)))
    ) as http:
        client = GoogleAdsClient(_static_token, developer_token=SecretStr("test"), client=http)
        assert await report(client, maximum=2) == []
    assert all(stream.closed for stream in streams)


async def test_report_stream_refreshes_credentials_after_rejection():
    forces = []
    streams = [ReportStream([b"{}"]), ReportStream([b"[]"])]
    attempts = iter(zip([401, 200], streams, strict=True))

    async def token(force):
        forces.append(force)
        return "test"

    def respond(request):
        status, stream = next(attempts)
        return httpx2.Response(status, stream=stream)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:
        client = GoogleAdsClient(token, developer_token=SecretStr("test"), client=http)
        assert await report(client, maximum=2) == []
    assert forces == [False, True]
    assert all(stream.closed for stream in streams)


@pytest.mark.parametrize("oversized", [False, True])
async def test_report_stream_preserves_bounded_provider_error_details(oversized):
    message = "Unrecognised report field."
    body = json.dumps({"error": {"message": message}}).encode()
    stream = ReportStream([body[:5], body[5:]] if not oversized else [b" " * 65_537, body])
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda request: httpx2.Response(400, stream=stream))
    ) as http:
        client = GoogleAdsClient(_static_token, developer_token=SecretStr("test"), client=http)
        with pytest.raises(IntegrationValidationError) as error:
            await report(client, maximum=100)
    assert error.value.user_message == (
        "Google Ads rejected the query. Check that its fields and filters are valid GAQL."
        if oversized
        else f"Google Ads rejected the query: {message}"
    )
    assert stream.read == (1 if oversized else 2)
    assert stream.closed
