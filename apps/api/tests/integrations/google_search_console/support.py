"""Shared builders for Google Search Console integration tests."""

from uuid import uuid4

import httpx2

from services.integrations.context.domain import ResolvedContextEntry


async def static_token(_force: bool) -> str:
    return "access-token"


def sites_transport(site_entries: list[dict[str, str]]) -> httpx2.MockTransport:
    """Return a transport that serves one Search Console sites response."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/webmasters/v3/sites"
        return httpx2.Response(200, json={"siteEntry": site_entries}, request=request)

    return httpx2.MockTransport(handler)


def site_entry(
    external_id: str = "sc-domain:example.com",
    *,
    write_allowed: bool = False,
) -> ResolvedContextEntry:
    return ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="google_search_console",
        resource_type="google_search_console_site",
        external_id=external_id,
        display_name="example.com",
        connection_id=uuid4(),
        connection_label="Client Search Console",
        connection_status="active",
        write_allowed=write_allowed,
    )
