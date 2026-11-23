# apps/api/tests/support/web.py

"""A fake public web for tests that reach the shared fetch transport or PageSpeed Insights."""

import json
from collections.abc import Callable, Mapping
from functools import cache, partial
from pathlib import Path
from typing import Any

import httpx2

from services.web.fetch import fetch_url
from services.web.page_speed import run_page_speed_test

_PUBLIC_ADDRESS = "93.184.216.34"


def fake_web(pages: Mapping[str, httpx2.Response]) -> Any:
    """Returns `fetch_url` serving `pages`, keyed by host and path, from a public address.

    Unknown pages answer `404`; every host resolves, so address checks still run.
    """

    async def resolve(_host: str, _port: int) -> tuple[str, ...]:
        return (_PUBLIC_ADDRESS,)

    def handler(request: httpx2.Request) -> httpx2.Response:
        # Requests are pinned to the address, so the page key comes from the Host header.
        return pages.get(f"{request.headers['host']}{request.url.path}") or httpx2.Response(404)

    return partial(fetch_url, resolver=resolve, transport=httpx2.MockTransport(handler))


def html_page(html: str, *, status: int = 200) -> httpx2.Response:
    return httpx2.Response(status, text=html, headers={"content-type": "text/html; charset=utf-8"})


@cache
def _page_speed_fixture() -> str:
    return (Path(__file__).parents[1] / "fixtures" / "web" / "pagespeed_mobile.json").read_text()


def page_speed_response(url: str) -> dict[str, Any]:
    """Returns the recorded PageSpeed Insights response, retargeted at `url`."""
    return json.loads(_page_speed_fixture().replace("https://shop.example/", url))


def fake_page_speed(
    respond: Callable[[httpx2.Request], httpx2.Response],
    *,
    requests: list[httpx2.Request] | None = None,
) -> Any:
    """Returns `run_page_speed_test` answered by `respond`, with every host public.

    Each request to Google is appended to `requests` when given.
    """

    async def resolve(_host: str, _port: int) -> tuple[str, ...]:
        return (_PUBLIC_ADDRESS,)

    def handler(request: httpx2.Request) -> httpx2.Response:
        if requests is not None:
            requests.append(request)
        return respond(request)

    return partial(run_page_speed_test, resolver=resolve, transport=httpx2.MockTransport(handler))
