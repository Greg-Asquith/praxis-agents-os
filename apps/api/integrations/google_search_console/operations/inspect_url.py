# apps/api/integrations/google_search_console/operations/inspect_url.py

"""Inspect one URL through Google Search Console."""

from typing import Any

from core.exceptions.integration import IntegrationError
from integrations.google_search_console.client import GoogleSearchConsoleClient
from services.integrations.http import IntegrationRequestPolicy

from .utils import bounded_text, invalid_response, nonnegative_int, untrusted

MAX_INSPECTION_URLS = 20


async def inspect_url(
    client: GoogleSearchConsoleClient,
    *,
    site_url: str,
    url: str,
    language_code: str,
) -> dict[str, Any]:
    """Return a bounded projection of one URL Inspection response."""
    try:
        payload = await client.inspection_post(
            "urlInspection/index:inspect",
            operation="inspect_url",
            policy=IntegrationRequestPolicy.READ,
            json={"inspectionUrl": url, "siteUrl": site_url, "languageCode": language_code},
        )
    except IntegrationError as exc:
        return _error_result(site_url=site_url, url=url, exc=exc)
    if not isinstance(payload, dict) or not isinstance(payload.get("inspectionResult"), dict):
        raise invalid_response("inspect_url")
    result = payload["inspectionResult"]
    index = result.get("indexStatusResult", {})
    mobile = result.get("mobileUsabilityResult", {})
    rich = result.get("richResultsResult", {})
    if not all(isinstance(item, dict) for item in (index, mobile, rich)):
        raise invalid_response("inspect_url")
    return {
        "url": url,
        "verdict": bounded_text(index.get("verdict")),
        "coverage_state": bounded_text(index.get("coverageState")),
        "robots_txt_state": bounded_text(index.get("robotsTxtState")),
        "indexing_state": bounded_text(index.get("indexingState")),
        "page_fetch_state": bounded_text(index.get("pageFetchState")),
        "crawled_as": bounded_text(index.get("crawledAs")),
        "last_crawl_time": bounded_text(index.get("lastCrawlTime")),
        "google_canonical": _optional_url(index.get("googleCanonical"), site_url=site_url),
        "user_canonical": _optional_url(index.get("userCanonical"), site_url=site_url),
        "sitemap": _urls(index.get("sitemap"), site_url=site_url),
        "referring_urls": _urls(index.get("referringUrls"), site_url=site_url),
        "mobile_usability_verdict": bounded_text(mobile.get("verdict")),
        "rich_results_verdict": bounded_text(rich.get("verdict")),
        "rich_results": _rich_results(rich.get("detectedItems")),
        "inspection_result_link": bounded_text(
            result.get("inspectionResultLink"), max_length=4_096
        ),
        "error_code": None,
        "message": None,
    }


def _optional_url(value: Any, *, site_url: str):
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise invalid_response("inspect_url")
    return untrusted(value, source_kind="search_console_inspection", source_ref=site_url)


def _urls(value: Any, *, site_url: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise invalid_response("inspect_url")
    return [
        untrusted(item, source_kind="search_console_inspection", source_ref=site_url)
        for item in value[:MAX_INSPECTION_URLS]
    ]


def _rich_results(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise invalid_response("inspect_url")
    output: list[dict[str, Any]] = []
    for detected in value[:MAX_INSPECTION_URLS]:
        if not isinstance(detected, dict):
            raise invalid_response("inspect_url")
        items = detected.get("items", [])
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise invalid_response("inspect_url")
        issue_count = 0
        for item in items:
            issues = item.get("issues", [])
            if not isinstance(issues, list):
                raise invalid_response("inspect_url")
            issue_count += len(issues)
        output.append(
            {
                "type": bounded_text(detected.get("richResultType")),
                "issue_count": nonnegative_int(issue_count, operation="inspect_url"),
            }
        )
    return output


def _error_result(*, site_url: str, url: str, exc: IntegrationError) -> dict[str, Any]:
    return {
        "url": url,
        "verdict": "",
        "coverage_state": "",
        "robots_txt_state": "",
        "indexing_state": "",
        "page_fetch_state": "",
        "crawled_as": "",
        "last_crawl_time": "",
        "google_canonical": None,
        "user_canonical": None,
        "sitemap": [],
        "referring_urls": [],
        "mobile_usability_verdict": "",
        "rich_results_verdict": "",
        "rich_results": [],
        "inspection_result_link": "",
        "error_code": exc.__class__.__name__,
        "message": untrusted(
            exc.user_message,
            source_kind="search_console_inspection_error",
            source_ref=site_url,
        ),
    }
