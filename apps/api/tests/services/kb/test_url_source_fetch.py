# apps/api/tests/services/kb/test_url_source_fetch.py

"""Knowledge-base URL source adapter and page conversion."""

import time
from collections.abc import Awaitable, Callable

import httpx2
import pytest

from services.documents.markdown import strip_markdown_noise
from services.kb.domain import KBSourceUnavailableError
from services.kb.utils import convert_html_to_markdown, fetch_url

Resolver = Callable[[str, int], Awaitable[tuple[str, ...]]]


def resolver_for(mapping: dict[str, tuple[str, ...]]) -> Resolver:
    async def resolve(host: str, _port: int) -> tuple[str, ...]:
        return mapping[host]

    return resolve


async def test_fetch_url_sends_stored_validators_on_first_hop_only() -> None:
    requests: list[httpx2.Request] = []

    async def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if request.url.path == "/document":
            return httpx2.Response(302, headers={"location": "/moved"})
        return httpx2.Response(200, content=b"moved content")

    fetched = await fetch_url(
        "https://source.example/document",
        etag='"revision-1"',
        last_modified="Tue, 01 Sep 2026 09:00:00 GMT",
        resolver=resolver_for({"source.example": ("93.184.216.34",)}),
        transport=httpx2.MockTransport(handler),
    )

    assert fetched.data == b"moved content"
    assert requests[0].headers["if-none-match"] == '"revision-1"'
    assert "if-none-match" not in requests[1].headers
    assert "if-modified-since" not in requests[1].headers


async def test_fetch_url_accepts_not_modified_response() -> None:
    async def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(304)

    etag = '"revision-1"'
    last_modified = "Tue, 01 Sep 2026 09:00:00 GMT"
    fetched = await fetch_url(
        "https://source.example/document",
        etag=etag,
        last_modified=last_modified,
        resolver=resolver_for({"source.example": ("93.184.216.34",)}),
        transport=httpx2.MockTransport(handler),
    )

    assert fetched.data == b""
    assert fetched.not_modified is True
    assert fetched.etag == etag
    assert fetched.last_modified == last_modified


@pytest.mark.parametrize(
    ("status_code", "error_code"),
    [(401, "access_lost"), (404, "not_found")],
)
async def test_fetch_url_maps_definitive_source_failures(
    status_code: int,
    error_code: str,
) -> None:
    async def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status_code)

    with pytest.raises(KBSourceUnavailableError) as exc_info:
        await fetch_url(
            "https://source.example/document",
            resolver=resolver_for({"source.example": ("93.184.216.34",)}),
            transport=httpx2.MockTransport(handler),
        )

    assert exc_info.value.error_code == error_code
    assert exc_info.value.details == {"status_code": status_code}


async def test_convert_html_to_markdown_drops_boilerplate_and_image_markup() -> None:
    html = b"""
    <html><head><title>Pricing</title><style>body { color: red; }</style></head><body>
    <header><a href="/"><img src="/G.svg" alt="Greg Asquith Logo">Greg Asquith</a></header>
    <nav><a href="/pricing">Pricing</a><a href="/blog">Blog</a></nav>
    <div role="banner"><a href="/signup">Sign up</a></div>
    <main>
      <h1>Plans</h1>
      <p><img src="/hero.png" alt="Plan comparison chart"> Tiers are listed below.</p>
      <p>See <a href="/plans/pro">the Pro plan</a> for details.</p>
      <p><a href="/plans/team"><img src="/team-mark.svg" alt=""></a></p>
      <p aria-hidden="true">Decorative marquee</p>
    </main>
    <footer><a href="/privacy">Privacy</a></footer>
    </body></html>
    """

    markdown = await convert_html_to_markdown(
        html,
        content_type="text/html; charset=utf-8",
        source_url="https://source.example/pricing",
    )

    assert "Plans" in markdown
    assert "Tiers are listed below." in markdown
    assert "the Pro plan" in markdown
    assert "Plan comparison chart" in markdown
    assert "![" not in markdown
    assert "Greg Asquith Logo" not in markdown
    assert "G.svg" not in markdown
    assert "/plans/team" not in markdown
    assert "Sign up" not in markdown
    assert "Privacy" not in markdown
    assert "Decorative marquee" not in markdown
    assert "\n\n\n" not in markdown


def test_markdown_noise_cleanup_is_linear_on_unclosed_markup() -> None:
    for payload in ("![" * 32_768, "[](" * 21_846):
        started = time.perf_counter()
        strip_markdown_noise(payload)
        assert time.perf_counter() - started < 0.5
