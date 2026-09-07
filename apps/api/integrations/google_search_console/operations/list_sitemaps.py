# apps/api/integrations/google_search_console/operations/list_sitemaps.py

"""List bounded sitemap status for one Search Console site."""

from typing import Any

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleSearchConsoleClient, site_path
from .utils import bounded_text, invalid_response, nonnegative_int, provider_bool, untrusted

MAX_SITEMAPS = 200
MAX_SITEMAP_CONTENT_TYPES = 20


async def list_sitemaps(
    client: GoogleSearchConsoleClient,
    *,
    site_url: str,
) -> dict[str, Any]:
    """Returns bounded sitemap processing status for one site."""
    payload = await client.webmasters_get(
        f"{site_path(site_url)}/sitemaps",
        operation="list_sitemaps",
        policy=IntegrationRequestPolicy.READ,
    )
    if not isinstance(payload, dict):
        raise invalid_response("list_sitemaps")
    raw_sitemaps = payload.get("sitemap", [])
    if not isinstance(raw_sitemaps, list):
        raise invalid_response("list_sitemaps")
    shaped = [_shape_sitemap(item, site_url=site_url) for item in raw_sitemaps]
    shaped.sort(key=lambda item: item["last_submitted"] or "", reverse=True)
    sitemaps = shaped[:MAX_SITEMAPS]
    return {"sitemaps": sitemaps, "sitemap_count": len(sitemaps)}


def _shape_sitemap(value: Any, *, site_url: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise invalid_response("list_sitemaps")
    raw_contents = value.get("contents", [])
    if not isinstance(raw_contents, list):
        raise invalid_response("list_sitemaps")
    contents = [_shape_content(item) for item in raw_contents[:MAX_SITEMAP_CONTENT_TYPES]]
    path = bounded_text(value.get("path"), max_length=4_096)
    if not path:
        raise invalid_response("list_sitemaps")
    return {
        "path": untrusted(
            path,
            source_kind="search_console_sitemap",
            source_ref=site_url,
        ),
        "type": bounded_text(value.get("type")),
        "last_submitted": bounded_text(value.get("lastSubmitted")) or None,
        "last_downloaded": bounded_text(value.get("lastDownloaded")) or None,
        "is_pending": provider_bool(value.get("isPending", False), operation="list_sitemaps"),
        "is_sitemaps_index": provider_bool(
            value.get("isSitemapsIndex", False), operation="list_sitemaps"
        ),
        "warnings": nonnegative_int(value.get("warnings", 0), operation="list_sitemaps"),
        "errors": nonnegative_int(value.get("errors", 0), operation="list_sitemaps"),
        "contents": contents,
        "submitted_url_count": sum(item["submitted"] for item in contents),
    }


def _shape_content(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise invalid_response("list_sitemaps")
    return {
        "type": bounded_text(value.get("type")),
        "submitted": nonnegative_int(value.get("submitted", 0), operation="list_sitemaps"),
    }
