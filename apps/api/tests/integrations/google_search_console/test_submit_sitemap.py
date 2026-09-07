# apps/api/tests/integrations/google_search_console/test_submit_sitemap.py

"""Sitemap submission operation coverage."""

from typing import Any

import pytest

from core.exceptions.integration import IntegrationNotFoundError, IntegrationValidationError
from integrations.google_search_console.operations.get_sitemap import get_sitemap
from integrations.google_search_console.operations.submit_sitemap import submit_sitemap
from services.integrations.http import IntegrationRequestPolicy


class _Client:
    def __init__(self, response: Any = None) -> None:
        self.response = response
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def webmasters_get(self, path: str, **kwargs: Any) -> Any:
        self.calls.append(("GET", path, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    async def webmasters_put(self, path: str, **kwargs: Any) -> Any:
        self.calls.append(("PUT", path, kwargs))
        return self.response


async def test_submit_sitemap_encodes_domain_site_and_sitemap_paths() -> None:
    client = _Client()

    await submit_sitemap(
        client,
        site_url="sc-domain:example.com",
        sitemap_url="https://example.com/maps/products index.xml",
    )

    assert client.calls == [
        (
            "PUT",
            "sites/sc-domain%3Aexample.com/sitemaps/https%3A%2F%2Fexample.com%2Fmaps%2Fproducts%20index.xml",
            {
                "operation": "submit_sitemap",
                "policy": IntegrationRequestPolicy.MUTATION,
                "allow_empty": True,
            },
        )
    ]


async def test_get_sitemap_encodes_prefix_site_and_projects_status() -> None:
    client = _Client(
        {
            "path": "https://example.com/docs/sitemap.xml",
            "lastSubmitted": "2026-09-03T11:10:00Z",
            "isPending": True,
            "warnings": "1",
            "errors": 0,
        }
    )

    result = await get_sitemap(
        client,
        site_url="https://example.com/docs/",
        sitemap_url="https://example.com/docs/sitemap.xml",
    )

    assert client.calls[0] == (
        "GET",
        "sites/https%3A%2F%2Fexample.com%2Fdocs%2F/sitemaps/https%3A%2F%2Fexample.com%2Fdocs%2Fsitemap.xml",
        {"operation": "get_sitemap", "policy": IntegrationRequestPolicy.READ},
    )
    assert result == {
        "path": "https://example.com/docs/sitemap.xml",
        "last_submitted": "2026-09-03T11:10:00Z",
        "is_pending": True,
        "warnings": 1,
        "errors": 0,
    }


async def test_get_sitemap_returns_none_for_missing_sitemap() -> None:
    client = _Client(
        IntegrationNotFoundError(
            "Missing sitemap",
            provider_key="google_search_console",
            operation="get_sitemap",
        )
    )

    assert (
        await get_sitemap(
            client,
            site_url="https://example.com/",
            sitemap_url="https://example.com/sitemap.xml",
        )
        is None
    )


@pytest.mark.parametrize("payload", [None, [], {}, {"path": ""}, {"path": "x", "isPending": "yes"}])
async def test_get_sitemap_rejects_malformed_status(payload: Any) -> None:
    with pytest.raises(IntegrationValidationError):
        await get_sitemap(
            _Client(payload),
            site_url="https://example.com/",
            sitemap_url="https://example.com/sitemap.xml",
        )
