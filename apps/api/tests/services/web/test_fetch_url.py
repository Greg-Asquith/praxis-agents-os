# apps/api/tests/services/web/test_fetch_url.py

"""Address checks, pinning, redirects, and limits for the shared web fetch transport."""

import gzip
from collections.abc import AsyncIterator, Awaitable, Callable

import httpx2
import pytest

from services.web.domain import FetchedResponse, WebFetchError
from services.web.fetch import fetch_url

Resolver = Callable[[str, int], Awaitable[tuple[str, ...]]]
Handler = Callable[[httpx2.Request], Awaitable[httpx2.Response]]

_PUBLIC = "93.184.216.34"


def resolver_for(mapping: dict[str, tuple[str, ...]]) -> Resolver:
    async def resolve(host: str, _port: int) -> tuple[str, ...]:
        return mapping[host]

    return resolve


async def fetch(
    url: str,
    handler: Handler,
    *,
    hosts: dict[str, tuple[str, ...]] | None = None,
    **options: object,
) -> FetchedResponse:
    return await fetch_url(
        url,
        timeout_seconds=options.pop("timeout_seconds", 5.0),
        max_redirects=options.pop("max_redirects", 3),
        max_bytes=options.pop("max_bytes", 1_000),
        resolver=resolver_for(hosts or {"source.example": (_PUBLIC,)}),
        transport=httpx2.MockTransport(handler),
        **options,
    )


async def never_connect(_request: httpx2.Request) -> httpx2.Response:
    raise AssertionError("A refused URL must never reach the transport")


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
async def test_rejects_non_public_resolved_addresses(address: str) -> None:
    with pytest.raises(WebFetchError, match="non-public") as exc_info:
        await fetch(
            "https://source.example/document",
            never_connect,
            hosts={"source.example": (address,)},
        )

    assert exc_info.value.error_class == "non_public_address"


async def test_rejects_non_http_schemes_and_credentials() -> None:
    with pytest.raises(WebFetchError, match="http or https"):
        await fetch("file:///etc/passwd", never_connect)

    with pytest.raises(WebFetchError, match="credentials"):
        await fetch("https://user:password@source.example/document", never_connect)


async def test_pins_initial_and_redirect_connections() -> None:
    requests: list[httpx2.Request] = []

    async def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if request.url.host == _PUBLIC:
            return httpx2.Response(302, headers={"location": "https://redirect.example/final"})
        return httpx2.Response(200, content=b"<h1>Safe content</h1>")

    fetched = await fetch(
        "https://source.example/document",
        handler,
        hosts={"source.example": (_PUBLIC,), "redirect.example": ("8.8.8.8",)},
    )

    assert fetched.body == b"<h1>Safe content</h1>"
    assert [request.url.host for request in requests] == [_PUBLIC, "8.8.8.8"]
    assert [request.headers["host"] for request in requests] == [
        "source.example",
        "redirect.example",
    ]
    assert [request.extensions["sni_hostname"] for request in requests] == [
        "source.example",
        "redirect.example",
    ]


async def test_brackets_ipv6_literal_host_header() -> None:
    requests: list[httpx2.Request] = []

    async def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, content=b"safe")

    fetched = await fetch(
        "https://[2606:4700:4700::1111]:8443/document",
        handler,
        hosts={"2606:4700:4700::1111": ("2606:4700:4700::1111",)},
    )

    assert fetched.body == b"safe"
    assert requests[0].headers["host"] == "[2606:4700:4700::1111]:8443"


async def test_cookie_set_by_one_hop_is_never_sent_to_the_next() -> None:
    requests: list[httpx2.Request] = []

    async def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx2.Response(
                302,
                headers={"location": "https://redirect.example/final", "set-cookie": "sid=secret"},
            )
        return httpx2.Response(200, content=b"safe")

    await fetch(
        "https://source.example/document",
        handler,
        hosts={"source.example": (_PUBLIC,), "redirect.example": (_PUBLIC,)},
    )

    assert "cookie" not in requests[1].headers


async def test_revalidates_redirect_before_connecting() -> None:
    connected_hosts: list[str] = []

    async def handler(request: httpx2.Request) -> httpx2.Response:
        connected_hosts.append(request.url.host)
        return httpx2.Response(302, headers={"location": "https://private.example/secret"})

    with pytest.raises(WebFetchError, match="non-public") as exc_info:
        await fetch(
            "https://source.example/document",
            handler,
            hosts={"source.example": (_PUBLIC,), "private.example": ("127.0.0.1",)},
        )

    assert connected_hosts == [_PUBLIC]
    assert [hop.location for hop in exc_info.value.redirects] == ["https://private.example/secret"]


async def test_refuses_redirect_to_blocked_domain_before_connecting() -> None:
    connected_hosts: list[str] = []

    async def handler(request: httpx2.Request) -> httpx2.Response:
        connected_hosts.append(request.url.host)
        return httpx2.Response(302, headers={"location": "https://cdn.blocked.example/page"})

    with pytest.raises(WebFetchError) as exc_info:
        await fetch(
            "https://source.example/document",
            handler,
            hosts={"source.example": (_PUBLIC,), "cdn.blocked.example": ("8.8.8.8",)},
            blocked_domains=("blocked.example",),
        )

    assert exc_info.value.error_class == "blocked_domain"
    assert connected_hosts == [_PUBLIC]


async def test_internationalised_host_is_sent_and_denylisted_in_its_ascii_form() -> None:
    requests: list[httpx2.Request] = []
    hosts = {"xn--mnchen-3ya.example": (_PUBLIC,)}

    async def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, content=b"safe")

    await fetch("https://münchen.example/page", handler, hosts=hosts)

    assert requests[0].headers["host"] == "xn--mnchen-3ya.example"
    assert requests[0].extensions["sni_hostname"] == "xn--mnchen-3ya.example"
    with pytest.raises(WebFetchError) as exc_info:
        await fetch(
            "https://münchen.example/page",
            never_connect,
            hosts=hosts,
            blocked_domains=("xn--mnchen-3ya.example",),
        )
    assert exc_info.value.error_class == "blocked_domain"


async def test_refuses_redirect_to_non_standard_port_when_required() -> None:
    async def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(302, headers={"location": "https://source.example:8080/admin"})

    with pytest.raises(WebFetchError) as exc_info:
        await fetch("https://source.example/document", handler, standard_ports_only=True)

    assert exc_info.value.error_class == "unsupported_port"


async def test_returns_error_status_with_every_redirect_hop() -> None:
    async def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/old":
            return httpx2.Response(301, headers={"location": "/moved"})
        if request.url.path == "/moved":
            return httpx2.Response(302, headers={"location": "https://source.example/gone"})
        return httpx2.Response(404, content=b"Not here")

    fetched = await fetch("https://source.example/old", handler)

    assert fetched.status == 404
    assert fetched.final_url == "https://source.example/gone"
    assert fetched.body == b"Not here"
    assert [(hop.url, hop.status, hop.location) for hop in fetched.redirects] == [
        ("https://source.example/old", 301, "https://source.example/moved"),
        ("https://source.example/moved", 302, "https://source.example/gone"),
    ]


async def test_marks_challenge_response_as_blocked_by_site() -> None:
    async def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(403, headers={"cf-mitigated": "challenge"})

    fetched = await fetch("https://source.example/page", handler)

    assert fetched.status == 403
    assert fetched.blocked_by_site is True


async def test_enforces_redirect_limit() -> None:
    async def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(302, headers={"location": "/again"})

    with pytest.raises(WebFetchError, match="redirect limit") as exc_info:
        await fetch("https://source.example/document", handler, max_redirects=1)

    assert exc_info.value.error_class == "too_many_redirects"


async def test_aborts_when_stream_exceeds_size_limit() -> None:
    async def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=b"12345")

    with pytest.raises(WebFetchError, match="size limit"):
        await fetch("https://source.example/document", handler, max_bytes=4)


async def test_gunzip_stops_at_size_limit() -> None:
    compressed = gzip.compress(b"<url></url>" * 10_000)

    async def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200, headers={"content-type": "application/gzip"}, content=compressed
        )

    assert len(compressed) < 1_000
    with pytest.raises(WebFetchError) as exc_info:
        await fetch("https://source.example/sitemap.xml.gz", handler, gunzip=True)

    assert exc_info.value.error_class == "too_large"


async def test_headers_only_mode_never_reads_the_body() -> None:
    class UnreadableStream(httpx2.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            raise AssertionError("Headers-only fetches must not read the body")
            yield b""

    async def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200, headers={"content-type": "text/html"}, stream=UnreadableStream()
        )

    fetched = await fetch("https://source.example/page", handler, body="none")

    assert fetched.status == 200
    assert fetched.body == b""
    assert fetched.content_type == "text/html"
