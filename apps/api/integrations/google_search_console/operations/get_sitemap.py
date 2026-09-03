# apps/api/integrations/google_search_console/operations/get_sitemap.py

"""Read one sitemap from Google Search Console."""

from typing import Any
from urllib.parse import quote

from core.exceptions.integration import IntegrationNotFoundError
from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleSearchConsoleClient, site_path
from .utils import bounded_text, invalid_response, nonnegative_int, provider_bool


async def get_sitemap(
    client: GoogleSearchConsoleClient,
    *,
    site_url: str,
    sitemap_url: str,
) -> dict[str, Any] | None:
    """Returns bounded processing status for one submitted sitemap."""
    try:
        payload = await client.webmasters_get(
            f"{site_path(site_url)}/sitemaps/{quote(sitemap_url, safe='')}",
            operation="get_sitemap",
            policy=IntegrationRequestPolicy.READ,
        )
    except IntegrationNotFoundError:
        return None
    if not isinstance(payload, dict):
        raise invalid_response("get_sitemap")
    path = bounded_text(payload.get("path"), max_length=4_096)
    if not path:
        raise invalid_response("get_sitemap")
    return {
        "path": path,
        "last_submitted": bounded_text(payload.get("lastSubmitted")) or None,
        "is_pending": provider_bool(payload.get("isPending", False), operation="get_sitemap"),
        "warnings": nonnegative_int(payload.get("warnings", 0), operation="get_sitemap"),
        "errors": nonnegative_int(payload.get("errors", 0), operation="get_sitemap"),
    }
