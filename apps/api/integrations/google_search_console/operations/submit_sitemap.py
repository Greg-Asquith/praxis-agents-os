# apps/api/integrations/google_search_console/operations/submit_sitemap.py

"""Submit one sitemap to Google Search Console."""

from urllib.parse import quote

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleSearchConsoleClient, site_path


async def submit_sitemap(
    client: GoogleSearchConsoleClient,
    *,
    site_url: str,
    sitemap_url: str,
) -> None:
    """Submits a sitemap for Google to process."""
    await client.webmasters_put(
        f"{site_path(site_url)}/sitemaps/{quote(sitemap_url, safe='')}",
        operation="submit_sitemap",
        policy=IntegrationRequestPolicy.MUTATION,
        allow_empty=True,
    )
