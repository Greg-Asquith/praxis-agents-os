# apps/api/tests/services/kb/test_fetch_url.py

"""SSRF and pinned-connect coverage for knowledge-base URL ingestion."""

from collections.abc import Awaitable, Callable

import httpx2
import pytest

from core.exceptions.general import AppValidationError
from core.settings import settings
from services.kb.utils import fetch_url

Resolver = Callable[[str, int], Awaitable[tuple[str, ...]]]


def resolver_for(mapping: dict[str, tuple[str, ...]]) -> Resolver:
    async def resolve(host: str, _port: int) -> tuple[str, ...]:
        return mapping[host]

    return resolve


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.10.2",
        "::1",
        "fc00::1",
        "fe80::1",
    ],
)
async def test_fetch_url_rejects_non_public_resolved_addresses(address: str) -> None:
    async def should_not_run(_request: httpx2.Request) -> httpx2.Response:
        raise AssertionError("A rejected address must never reach the transport")

    with pytest.raises(AppValidationError, match="non-public"):
        await fetch_url(
            "https://source.example/document",
            resolver=resolver_for({"source.example": (address,)}),
            transport=httpx2.MockTransport(should_not_run),
        )


async def test_fetch_url_rejects_non_http_schemes_and_credentials() -> None:
    with pytest.raises(AppValidationError, match="http or https"):
        await fetch_url("file:///etc/passwd")

    with pytest.raises(AppValidationError, match="credentials"):
        await fetch_url("https://user:password@source.example/document")


async def test_fetch_url_pins_initial_and_redirect_connections() -> None:
    requests: list[httpx2.Request] = []

    async def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if request.url.host == "93.184.216.34":
            return httpx2.Response(
                302,
                headers={"location": "https://redirect.example/final"},
            )
        return httpx2.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=b"<h1>Safe content</h1>",
        )

    body, content_type = await fetch_url(
        "https://source.example/document",
        resolver=resolver_for(
            {
                "source.example": ("93.184.216.34",),
                "redirect.example": ("8.8.8.8",),
            }
        ),
        transport=httpx2.MockTransport(handler),
    )

    assert body == b"<h1>Safe content</h1>"
    assert content_type == "text/html; charset=utf-8"
    assert [request.url.host for request in requests] == ["93.184.216.34", "8.8.8.8"]
    assert [request.headers["host"] for request in requests] == [
        "source.example",
        "redirect.example",
    ]
    assert [request.extensions["sni_hostname"] for request in requests] == [
        "source.example",
        "redirect.example",
    ]


async def test_fetch_url_brackets_ipv6_literal_host_header() -> None:
    requests: list[httpx2.Request] = []

    async def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, content=b"safe")

    body, _ = await fetch_url(
        "https://[2606:4700:4700::1111]:8443/document",
        resolver=resolver_for({"2606:4700:4700::1111": ("2606:4700:4700::1111",)}),
        transport=httpx2.MockTransport(handler),
    )

    assert body == b"safe"
    assert requests[0].headers["host"] == "[2606:4700:4700::1111]:8443"


async def test_fetch_url_revalidates_redirect_before_connecting() -> None:
    connected_hosts: list[str] = []

    async def handler(request: httpx2.Request) -> httpx2.Response:
        connected_hosts.append(request.url.host)
        return httpx2.Response(
            302,
            headers={"location": "https://private.example/secret"},
        )

    with pytest.raises(AppValidationError, match="non-public"):
        await fetch_url(
            "https://source.example/document",
            resolver=resolver_for(
                {
                    "source.example": ("93.184.216.34",),
                    "private.example": ("127.0.0.1",),
                }
            ),
            transport=httpx2.MockTransport(handler),
        )

    assert connected_hosts == ["93.184.216.34"]


async def test_fetch_url_aborts_when_stream_exceeds_size_limit(monkeypatch) -> None:
    monkeypatch.setattr(settings, "KB_URL_MAX_BYTES", 4)

    async def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=b"12345")

    with pytest.raises(AppValidationError, match="size limit"):
        await fetch_url(
            "https://source.example/document",
            resolver=resolver_for({"source.example": ("93.184.216.34",)}),
            transport=httpx2.MockTransport(handler),
        )
