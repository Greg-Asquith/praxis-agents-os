"""Signed upload requests keep credentials and provider details private."""

import asyncio
import logging
import traceback

import httpx2
import pytest

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationConnectionError,
    IntegrationFailureDisposition,
    IntegrationNotFoundError,
    IntegrationPermissionError,
    IntegrationRateLimitError,
    IntegrationTimeoutError,
    IntegrationValidationError,
)
from services.integrations.http import IntegrationRequestPolicy, track_transport_attempts
from services.integrations.microsoft_graph import MicrosoftGraphClient

UPLOAD_URL = "https://93.184.216.34/session?signature=PRIVATE_UPLOAD_SECRET"


async def no_credentials(_force):
    pytest.fail("Signed uploads must not resolve credentials")


async def invoke(client, method, url=UPLOAD_URL):
    if method == "PUT":
        return await client.upload_fragment(url, b"file", operation="upload", offset=8, total=12)
    if method == "GET":
        return await client.upload_status(url, operation="upload")
    return await client.cancel_upload(url, operation="upload")


@pytest.mark.parametrize(
    "method,status", [("PUT", 200), ("PUT", 201), ("PUT", 202), ("GET", 200), ("DELETE", 204)]
)
async def test_upload_never_uses_credentials_and_sends_exact_headers(monkeypatch, method, status):
    from services.integrations.microsoft_graph import client as module

    requests = []

    async def resolve(host, port):
        assert (host, port) == ("upload.example.com", 443)
        return ("93.184.216.34",)

    def handler(request):
        requests.append(request)
        return httpx2.Response(status, json={"nextExpectedRanges": ["12-"]})

    monkeypatch.setattr(module, "_resolve_host", resolve)
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(handler),
        headers={"Authorization": "Bearer inherited", "Cookie": "private=value"},
        auth=("username", "password"),
    ) as transport:
        client = MicrosoftGraphClient(no_credentials, provider_key="sharepoint", client=transport)
        with track_transport_attempts() as counter:
            result = await invoke(client, method, "https://upload.example.com/session?secret=token")
    assert result == (None if method == "DELETE" else {"nextExpectedRanges": ["12-"]})
    assert (counter.requests, counter.attempts) == (1, 1)
    request = requests[0]
    assert request.url.host == "93.184.216.34"
    assert request.headers["Host"] == "upload.example.com"
    assert request.extensions["sni_hostname"] == "upload.example.com"
    assert not {"authorization", "cookie", "proxy-authorization"}.intersection(request.headers)
    assert "client-request-id" in request.headers
    if method == "PUT":
        assert request.headers["Content-Range"] == "bytes 8-11/12"
        assert request.headers["Content-Length"] == "4"
        assert request.content == b"file"


@pytest.mark.parametrize("method", ["PUT", "GET", "DELETE"])
@pytest.mark.parametrize(
    "url",
    [
        "http://93.184.216.34/session",
        "https://127.0.0.1/session",
        "https://10.0.0.1/session",
        "https://[::1]/session",
        "https://169.254.169.254/session",
        "https://user:password@93.184.216.34/session",
    ],
)
async def test_upload_refuses_unsafe_destinations(method, url):
    client = MicrosoftGraphClient(no_credentials, provider_key="sharepoint")
    with track_transport_attempts() as counter, pytest.raises(IntegrationValidationError) as caught:
        await invoke(client, method, url)
    assert (counter.requests, counter.attempts) == (0, 0)
    assert caught.value.failure_disposition is IntegrationFailureDisposition.NOT_DISPATCHED


@pytest.mark.parametrize("method", ["PUT", "GET", "DELETE"])
async def test_cancellation_during_upload_url_resolution_is_not_dispatched(monkeypatch, method):
    async def resolve(_host, _port):
        raise asyncio.CancelledError

    monkeypatch.setattr("services.integrations.microsoft_graph.client._resolve_host", resolve)
    client = MicrosoftGraphClient(no_credentials, provider_key="sharepoint")
    with track_transport_attempts() as counter, pytest.raises(asyncio.CancelledError) as caught:
        await invoke(client, method)
    assert (counter.requests, counter.attempts) == (0, 0)
    assert caught.value.failure_disposition is IntegrationFailureDisposition.NOT_DISPATCHED


@pytest.mark.parametrize("method", ["PUT", "GET", "DELETE"])
async def test_upload_refuses_mixed_public_and_private_dns(monkeypatch, method):
    from services.integrations.microsoft_graph import client as module

    async def resolve(_host, _port):
        return ("93.184.216.34", "192.168.1.1")

    monkeypatch.setattr(module, "_resolve_host", resolve)
    client = MicrosoftGraphClient(no_credentials, provider_key="sharepoint")
    with pytest.raises(IntegrationValidationError):
        await invoke(client, method, "https://upload.example.com/session")


@pytest.mark.parametrize("method", ["PUT", "GET", "DELETE"])
@pytest.mark.parametrize(
    "status,error,code",
    [
        (302, IntegrationValidationError, None),
        (307, IntegrationValidationError, None),
        (401, IntegrationAuthError, None),
        (403, IntegrationPermissionError, None),
        (404, IntegrationNotFoundError, "upload_session_expired"),
        (409, IntegrationValidationError, "name_exists"),
        (412, IntegrationValidationError, "version_conflict"),
        (416, IntegrationValidationError, "invalid_range"),
        (423, IntegrationValidationError, "locked"),
        (429, IntegrationRateLimitError, None),
        (503, IntegrationConnectionError, "upload_interrupted"),
        (507, IntegrationValidationError, "quota_exceeded"),
    ],
)
async def test_upload_maps_errors_without_retry_or_signed_url(caplog, method, status, error, code):
    caplog.set_level(logging.DEBUG)
    requests = []

    def handler(request):
        requests.append(request)
        logging.getLogger("httpcore2.http11").debug("Signed upload %s", UPLOAD_URL)
        return httpx2.Response(
            status,
            headers={"Location": UPLOAD_URL, "request-id": UPLOAD_URL, "Retry-After": "0"},
            json={"error": {"message": UPLOAD_URL, "code": "nameAlreadyExists"}},
        )

    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(handler), follow_redirects=True
    ) as transport:
        client = MicrosoftGraphClient(no_credentials, provider_key="sharepoint", client=transport)
        with track_transport_attempts() as counter, pytest.raises(error) as caught:
            await invoke(client, method)
    assert len(requests) == 1
    assert (counter.requests, counter.attempts) == (1, 1)
    assert caught.value.error_code == code
    assert caught.value.original_error is None
    if status == 404:
        assert caught.value.failure_disposition is IntegrationFailureDisposition.NOT_DISPATCHED
    assert "PRIVATE_UPLOAD_SECRET" not in caplog.text
    assert "PRIVATE_UPLOAD_SECRET" not in str(caught.value.to_problem_details())
    assert "PRIVATE_UPLOAD_SECRET" not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize("method", ["PUT", "GET", "DELETE"])
@pytest.mark.parametrize("failure", [httpx2.ReadTimeout, httpx2.ConnectError])
async def test_upload_transport_failure_is_private_and_never_retried(method, failure):
    def handler(request):
        raise failure(UPLOAD_URL, request=request)

    error = IntegrationTimeoutError if failure is httpx2.ReadTimeout else IntegrationConnectionError
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as transport:
        client = MicrosoftGraphClient(no_credentials, provider_key="sharepoint", client=transport)
        with track_transport_attempts() as counter, pytest.raises(error) as caught:
            await invoke(client, method)
    assert (counter.requests, counter.attempts) == (1, 1)
    assert caught.value.error_code == "upload_interrupted"
    assert caught.value.failure_disposition is IntegrationFailureDisposition.AMBIGUOUS
    assert caught.value.original_error is None
    assert "PRIVATE_UPLOAD_SECRET" not in "".join(traceback.format_exception(caught.value))


async def test_upload_cancellation_propagates_with_ambiguous_disposition():
    def handler(_request):
        raise asyncio.CancelledError

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as transport:
        client = MicrosoftGraphClient(no_credentials, provider_key="sharepoint", client=transport)
        with track_transport_attempts() as counter, pytest.raises(asyncio.CancelledError) as caught:
            await invoke(client, "PUT")
    assert (counter.requests, counter.attempts) == (1, 1)
    assert caught.value.failure_disposition is IntegrationFailureDisposition.AMBIGUOUS


@pytest.mark.parametrize("body", [b"[1, 2]", b"not JSON PRIVATE_UPLOAD_SECRET"])
async def test_upload_malformed_response_does_not_leak_body(body):
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(201, content=body))
    ) as transport:
        client = MicrosoftGraphClient(no_credentials, provider_key="sharepoint", client=transport)
        with pytest.raises(IntegrationValidationError) as caught:
            await invoke(client, "PUT")
    assert caught.value.original_error is None
    assert "PRIVATE_UPLOAD_SECRET" not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize("data,offset,total", [(b"", 0, 0), (b"file", -1, 4), (b"file", 0, 3)])
async def test_upload_invalid_range_stops_before_dispatch(data, offset, total):
    client = MicrosoftGraphClient(no_credentials, provider_key="sharepoint")
    with track_transport_attempts() as counter, pytest.raises(ValueError):
        await client.upload_fragment(
            UPLOAD_URL, data, operation="upload", offset=offset, total=total
        )
    assert counter.attempts == 0


async def test_upload_response_excludes_signed_url_annotations():
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(
            lambda _: httpx2.Response(
                201,
                json={
                    "id": "item",
                    "uploadUrl": UPLOAD_URL,
                    "@microsoft.graph.downloadUrl": UPLOAD_URL,
                },
            )
        )
    ) as transport:
        client = MicrosoftGraphClient(no_credentials, provider_key="sharepoint", client=transport)
        assert await invoke(client, "PUT") == {"id": "item"}


@pytest.mark.parametrize(
    "status,code",
    [(409, "name_exists"), (412, "version_conflict"), (423, "locked"), (507, "quota_exceeded")],
)
async def test_authenticated_session_creation_maps_write_errors(status, code):
    async def token(_force):
        return "credential"

    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(
            lambda _: httpx2.Response(status, json={"error": {"code": "nameAlreadyExists"}})
        )
    ) as transport:
        client = MicrosoftGraphClient(token, provider_key="sharepoint", client=transport)
        with pytest.raises(IntegrationValidationError) as caught:
            await client.post(
                "/drives/drive/items/item/createUploadSession",
                operation="replace_item",
                policy=IntegrationRequestPolicy.MUTATION,
            )
    assert caught.value.error_code == code


async def test_malformed_session_creation_does_not_retain_upload_url():
    async def token(_force):
        return "credential"

    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(
            lambda _: httpx2.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=f'{{"uploadUrl": "{UPLOAD_URL}"'.encode(),
            )
        )
    ) as transport:
        client = MicrosoftGraphClient(token, provider_key="sharepoint", client=transport)
        with pytest.raises(IntegrationValidationError) as caught:
            await client.post(
                "/drives/drive/items/item/createUploadSession",
                operation="replace_item",
                policy=IntegrationRequestPolicy.MUTATION,
            )
    assert caught.value.original_error is None
    assert "PRIVATE_UPLOAD_SECRET" not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize("provider_code", [None, "ErrorIrresolvableConflict", "unexpected"])
async def test_outlook_conflict_keeps_generic_fallback(provider_code):
    async def token(_force):
        return "credential"

    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(
            lambda _: httpx2.Response(409, json={"error": {"code": provider_code}})
        )
    ) as transport:
        client = MicrosoftGraphClient(token, provider_key="outlook_mail", client=transport)
        with pytest.raises(IntegrationValidationError) as caught:
            await client.post(
                "/me/messages/message/move",
                operation="move_message",
                policy=IntegrationRequestPolicy.MUTATION,
            )
    assert caught.value.error_code is None
    assert caught.value.user_message == "Integration request was rejected"


@pytest.mark.parametrize("status", [412, 423, 507])
async def test_shared_write_errors_do_not_assume_sharepoint(status):
    from services.integrations.microsoft_graph.errors import graph_response_error

    error = graph_response_error(
        httpx2.Response(status), provider_key="outlook_mail", operation="update_message"
    )
    assert error is not None
    assert "SharePoint" not in error.user_message
    assert "file" not in error.user_message
    assert "library" not in error.user_message


@pytest.mark.parametrize("method", ["PUT", "GET", "DELETE"])
@pytest.mark.parametrize(
    "body,name_conflict",
    [
        ({"error": {"code": "nameAlreadyExists", "message": UPLOAD_URL}}, True),
        ({"error": {"code": "ErrorIrresolvableConflict", "message": UPLOAD_URL}}, False),
        ({"error": {"code": UPLOAD_URL}}, False),
        ({"error": {"code": 123}}, False),
        ({"error": UPLOAD_URL}, False),
        ({}, False),
        ([], False),
        (None, False),
    ],
)
async def test_signed_conflict_uses_only_known_code(caplog, method, body, name_conflict):
    caplog.set_level(logging.DEBUG)
    response = httpx2.Response(
        409,
        headers={"request-id": UPLOAD_URL},
        content=b"invalid JSON PRIVATE_UPLOAD_SECRET" if body is None else None,
        json=body if body is not None else None,
    )
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(lambda _: response)) as transport:
        client = MicrosoftGraphClient(no_credentials, provider_key="sharepoint", client=transport)
        with (
            track_transport_attempts() as counter,
            pytest.raises(IntegrationValidationError) as caught,
        ):
            await invoke(client, method)
    assert (counter.requests, counter.attempts) == (1, 1)
    assert caught.value.failure_disposition is IntegrationFailureDisposition.REJECTED
    assert caught.value.error_code == ("name_exists" if name_conflict else None)
    if not name_conflict:
        assert caught.value.user_message == "Integration request was rejected"
    assert caught.value.original_error is None
    assert "PRIVATE_UPLOAD_SECRET" not in caplog.text
    assert "PRIVATE_UPLOAD_SECRET" not in str(caught.value.to_problem_details())
    assert "PRIVATE_UPLOAD_SECRET" not in "".join(traceback.format_exception(caught.value))
