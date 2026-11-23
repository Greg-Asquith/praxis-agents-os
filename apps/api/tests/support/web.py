# apps/api/tests/support/web.py

"""A fake public web for tests that reach the shared fetch transport."""

from collections.abc import Mapping
from functools import partial
from typing import Any

import httpx2

from services.web.fetch import fetch_url

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
