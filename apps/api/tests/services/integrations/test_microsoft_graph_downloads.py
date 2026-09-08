"""Authenticated Graph download transport boundaries."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx2
import pytest

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationNotFoundError,
    IntegrationPermissionError,
    IntegrationTimeoutError,
    IntegrationValidationError,
)
from core.settings import settings
from services.integrations.http import track_transport_attempts
from services.integrations.microsoft_graph import MicrosoftGraphClient, fixed_access_token

PATH = "/me/messages/message/attachments/attachment/$value"


class ChunkStream(httpx2.AsyncByteStream):
    def __init__(self, *, fail: bool = False) -> None:
        self.closed = False
        self.fail = fail

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b"file"
        if self.fail:
            raise httpx2.ReadTimeout("private provider detail")
        yield b"!"

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.parametrize("status", [401, 429, 503])
async def test_download_refreshes_or_retries_with_pacing(monkeypatch, status):
    from services.integrations import http
    from services.integrations.microsoft_graph import client as module

    requests, refreshes, events, waits = [], [], [], []

    async def token(force):
        refreshes.append(force)
        return "fresh" if force else "initial"

    @asynccontextmanager
    async def pace(key):
        assert key == "connection"
        events.append("pace")
        try:
            yield
        finally:
            events.append("release")

    async def sleep(seconds):
        waits.append(seconds)

    def handler(request):
        requests.append(request)
        events.append("dispatch")
        if len(requests) == 1:
            return httpx2.Response(status, headers={"Retry-After": "2"})
        return httpx2.Response(200, content=b"file", headers={"Content-Type": "application/pdf"})

    monkeypatch.setattr(module, "paced_request", pace)
    monkeypatch.setattr(http.asyncio, "sleep", sleep)
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as transport:
        client = MicrosoftGraphClient(
            token, provider_key="outlook_mail", client=transport, pacing_key="connection"
        )
        with track_transport_attempts() as counter:
            assert (
                await client.get_graph_bytes(PATH, operation="attachment", max_bytes=4) == b"file"
            )
    assert refreshes == ([False, True] if status == 401 else [False])
    assert waits == ([] if status == 401 else [2.0])
    assert (counter.requests, counter.attempts) == (2 if status == 401 else 1, 2)
    assert events == ["pace", "dispatch", "release"] * 2
    assert len({request.headers["client-request-id"] for request in requests}) == 2
    for request in requests:
        assert request.url.host == "graph.microsoft.com"
        assert request.headers["Prefer"] == 'IdType="ImmutableId"'
        assert request.headers["Accept"] == "*/*"
        assert "PraxisAgents-outlook_mail" in request.headers["User-Agent"]
    assert requests[-1].headers["Authorization"] == (
        "Bearer fresh" if status == 401 else "Bearer initial"
    )


@pytest.mark.parametrize("length", [None, "1", "5"])
async def test_download_bounds_stream_and_declared_length(length):
    stream = ChunkStream()
    requests = []

    def handler(request):
        requests.append(request)
        return httpx2.Response(
            200, stream=stream, headers={} if length is None else {"Content-Length": length}
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as transport:
        client = MicrosoftGraphClient(
            fixed_access_token("secret"), provider_key="outlook_mail", client=transport
        )
        with pytest.raises(IntegrationValidationError, match="size limit"):
            await client.get_graph_bytes(PATH, operation="attachment", max_bytes=4)
    assert stream.closed
    assert len(requests) == 1


@pytest.mark.parametrize(
    "status,error",
    [
        (401, IntegrationAuthError),
        (403, IntegrationPermissionError),
        (404, IntegrationNotFoundError),
        (302, IntegrationValidationError),
    ],
)
async def test_download_maps_errors_and_never_follows_redirects(status, error):
    requests, refreshes = [], []

    async def token(force):
        refreshes.append(force)
        return "secret"

    def handler(request):
        requests.append(request)
        return httpx2.Response(status, headers={"Location": "https://example.com/private"})

    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(handler), follow_redirects=True
    ) as transport:
        client = MicrosoftGraphClient(token, provider_key="outlook_mail", client=transport)
        with pytest.raises(error):
            await client.get_graph_bytes(PATH, operation="attachment", max_bytes=4)
    assert len(requests) == (2 if status == 401 else 1)
    assert refreshes == ([False, True] if status == 401 else [False])
    assert all(request.url.host == "graph.microsoft.com" for request in requests)


@pytest.mark.parametrize(
    "path,max_bytes",
    [
        ("https://example.com/file", 4),
        ("http://graph.microsoft.com/file", 4),
        ("https://user:secret@graph.microsoft.com/file", 4),
        (PATH, 0),
    ],
)
async def test_download_rejects_invalid_input_before_credentials(path, max_bytes):
    async def token(_force):
        pytest.fail("Invalid downloads must not resolve credentials")

    client = MicrosoftGraphClient(token, provider_key="outlook_mail")
    with pytest.raises(ValueError):
        await client.get_graph_bytes(path, operation="attachment", max_bytes=max_bytes)


async def test_download_restarts_partial_read_and_closes_stream(monkeypatch):
    from services.integrations import http

    streams = []

    async def sleep(_seconds):
        return None

    def handler(_request):
        stream = ChunkStream(fail=not streams)
        streams.append(stream)
        return httpx2.Response(200, stream=stream)

    monkeypatch.setattr(http.asyncio, "sleep", sleep)
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as transport:
        client = MicrosoftGraphClient(
            fixed_access_token("secret"), provider_key="outlook_mail", client=transport
        )
        with track_transport_attempts() as counter:
            assert (
                await client.get_graph_bytes(PATH, operation="attachment", max_bytes=5) == b"file!"
            )
    assert (counter.requests, counter.attempts) == (1, 2)
    assert all(stream.closed for stream in streams)


@pytest.mark.parametrize("cancel", [False, True])
async def test_download_propagates_terminal_transport_failure(monkeypatch, cancel):
    def handler(_request):
        if cancel:
            raise asyncio.CancelledError
        raise httpx2.ReadTimeout("private provider detail")

    monkeypatch.setattr(settings, "INTEGRATIONS_HTTP_RETRY_MAX_ATTEMPTS", 1)
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as transport:
        client = MicrosoftGraphClient(
            fixed_access_token("secret"), provider_key="outlook_mail", client=transport
        )
        with (
            track_transport_attempts() as counter,
            pytest.raises(asyncio.CancelledError if cancel else IntegrationTimeoutError) as exc,
        ):
            await client.get_graph_bytes(PATH, operation="attachment", max_bytes=4)
    assert (counter.requests, counter.attempts) == (1, 1)
    if not cancel:
        assert exc.value.original_error is None
