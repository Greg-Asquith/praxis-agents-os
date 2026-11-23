# apps/api/services/web/page_speed.py

"""Runs Google PageSpeed Insights on one public page and reduces Google's report.

Google fetches the page, so the shared transport isn't used. The URL still passes the
public-address and denylist checks first, so an internal host name never reaches Google.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any, Literal

import httpx2

from core.exceptions.general import AppValidationError
from services.web.domain import WebFetchError
from services.web.utils import (
    Resolver,
    ascii_host,
    blocked_domain_for_host,
    resolve_public_addresses,
    validate_public_url,
)

PAGESPEED_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
# Fits one read_file window, so the agent reads a page's report in one call.
REPORT_MAX_BYTES = 40_000

PageSpeedStrategy = Literal["mobile", "desktop"]
PageSpeedCategory = Literal["performance", "accessibility", "best_practices", "seo"]
PageSpeedErrorClass = Literal[
    "invalid_url",
    "unsupported_port",
    "non_public_address",
    "blocked_domain",
    "dns_failure",
    "page_unreachable",
    "page_error",
    "key_rejected",
    "quota_exceeded",
    "timeout",
    "service_error",
]
Rating = Literal["good", "needs_improvement", "poor"]

_LIGHTHOUSE_CATEGORIES: dict[PageSpeedCategory, str] = {
    "performance": "performance",
    "accessibility": "accessibility",
    "best_practices": "best-practices",
    "seo": "seo",
}
_LAB_METRICS = {
    "lcp_ms": "largest-contentful-paint",
    "cls": "cumulative-layout-shift",
    "tbt_ms": "total-blocking-time",
    "fcp_ms": "first-contentful-paint",
    "speed_index_ms": "speed-index",
}
_FIELD_METRICS = {
    "lcp_ms": "LARGEST_CONTENTFUL_PAINT_MS",
    "inp_ms": "INTERACTION_TO_NEXT_PAINT",
    "cls": "CUMULATIVE_LAYOUT_SHIFT_SCORE",
    "ttfb_ms": "EXPERIMENTAL_TIME_TO_FIRST_BYTE",
}
_FIELD_RATINGS: dict[str, Rating] = {
    "FAST": "good",
    "AVERAGE": "needs_improvement",
    "SLOW": "poor",
}
_SCORED_MODES = frozenset({"numeric", "binary", "metricSavings"})
_SKIPPED_GROUPS = frozenset({"metrics", "hidden"})
_SAVING_METRICS = ("LCP", "FCP", "TBT", "INP")
_DETAIL_TYPES = frozenset({"opportunity", "table", "list"})
_LCP_AUDITS = ("largest-contentful-paint-element", "lcp-breakdown-insight", "lcp-discovery-insight")
_THIRD_PARTY_AUDITS = ("third-party-summary", "third-parties-insight")
_ITEM_NUMBERS = {
    "totalBytes": "total_bytes",
    "transferSize": "transfer_bytes",
    "wastedBytes": "wasted_bytes",
    "wastedMs": "wasted_ms",
}
_UNREACHABLE_ERRORS = frozenset(
    {
        "CHROME_INTERSTITIAL_ERROR",
        "DNS_FAILURE",
        "ERRORED_DOCUMENT_REQUEST",
        "FAILED_DOCUMENT_REQUEST",
        "INSECURE_DOCUMENT_REQUEST",
    }
)
_LIGHTHOUSE_ERROR = re.compile(r"Lighthouse returned error: ([A-Z_]+)")
# Audit IDs and versions travel as plain values, so they must match fixed patterns.
AUDIT_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,99}")
_VERSION = re.compile(r"[0-9][0-9.]{0,19}")
_MAX_TOP_ISSUES = 3
_MAX_ITEMS = 20
_MAX_THIRD_PARTIES = 20
_MAX_WARNINGS = 10


class PageSpeedError(AppValidationError):
    """Raised when a page can't be tested, before or after the request to Google."""

    def __init__(self, message: str, *, error_class: PageSpeedErrorClass) -> None:
        super().__init__(message, field="url", details={"error_class": error_class})
        self.error_class = error_class


@dataclass(frozen=True)
class PageSpeedTest:
    """One page's reduced test: a short summary for model context and a bounded report."""

    final_url: str | None
    summary: dict[str, Any]
    origin_field: dict[str, Any] | None
    report: dict[str, Any]


async def run_page_speed_test(
    url: str,
    *,
    strategy: PageSpeedStrategy,
    categories: Iterable[PageSpeedCategory],
    api_key: str,
    timeout_seconds: float,
    blocked_domains: Iterable[str] = (),
    resolver: Resolver = resolve_public_addresses,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> PageSpeedTest:
    """Tests one page with PageSpeed Insights and returns its reduced result.

    Sends one request to Google with the key in a header, never in the URL.

    Raises:
        PageSpeedError: If the URL is refused before the request, Google can't test the
            page, the key or quota is rejected, or the test passes `timeout_seconds`.
    """
    chosen = tuple(dict.fromkeys(categories))
    await _check_page_url(url, blocked_domains=tuple(blocked_domains), resolver=resolver)
    params = [
        ("url", url),
        ("strategy", strategy.upper()),
        *(("category", category.upper()) for category in chosen),
    ]
    try:
        async with asyncio.timeout(timeout_seconds):
            async with httpx2.AsyncClient(
                transport=transport, timeout=timeout_seconds, trust_env=False
            ) as client:
                response = await client.get(
                    PAGESPEED_ENDPOINT, params=params, headers={"X-Goog-Api-Key": api_key}
                )
    except (TimeoutError, httpx2.TimeoutException) as exc:
        raise PageSpeedError("The test did not finish in time", error_class="timeout") from exc
    except httpx2.TransportError as exc:
        raise PageSpeedError(
            "PageSpeed Insights could not be reached", error_class="service_error"
        ) from exc
    if response.status_code != 200:
        raise PageSpeedError(
            "PageSpeed Insights could not test the page", error_class=_error_class(response)
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise PageSpeedError(
            "PageSpeed Insights returned an unreadable result", error_class="service_error"
        ) from exc
    return reduce_page_speed(payload, requested_url=url, strategy=strategy, categories=chosen)


def reduce_page_speed(
    payload: Any,
    *,
    requested_url: str,
    strategy: PageSpeedStrategy,
    categories: tuple[PageSpeedCategory, ...],
) -> PageSpeedTest:
    """Reduces a PageSpeed Insights response to a summary and a report under the byte limit.

    Raises:
        PageSpeedError: If the response has no Lighthouse result or Lighthouse failed.
    """
    record = _record(payload)
    lighthouse = _record(record.get("lighthouseResult"))
    if not lighthouse:
        raise PageSpeedError("PageSpeed Insights returned no report", error_class="service_error")
    runtime_error = _record(lighthouse.get("runtimeError"))
    if isinstance(runtime_error.get("code"), str) and runtime_error["code"] != "NO_ERROR":
        raise PageSpeedError(
            "Lighthouse could not test the page",
            error_class=_lighthouse_error_class(runtime_error["code"]),
        )
    audits = _record(lighthouse.get("audits"))
    scored = list(_scored_audits(lighthouse, audits, categories))
    failed = [(category, audit) for category, audit, passed in scored if not passed]
    final_url = _final_url(record, lighthouse)
    scores = _scores(lighthouse, categories)
    lab = _lab(audits)
    field = _field(record.get("loadingExperience"), page=True)
    summary = {
        "requested_url": requested_url,
        "final_url": final_url if final_url != requested_url else None,
        "scores": scores,
        "lab": lab,
        "field": field,
        "top_issues": _top_issues(failed),
    }
    report = {
        "requested_url": requested_url,
        "final_url": final_url,
        "strategy": strategy,
        "lighthouse_version": _matching(lighthouse.get("lighthouseVersion"), _VERSION),
        "fetch_time": _text(lighthouse.get("fetchTime"), 40),
        "test_time_ms": _whole(_record(lighthouse.get("timing")).get("total")),
        "scores": scores,
        "lab": lab,
        "field": field,
        "failed_audits": [_failed_audit(category, audit) for category, audit in failed],
        "lcp_element": _lcp_element(audits),
        "third_parties": _third_parties(audits),
        "passed_audits": [audit["id"] for _, audit, passed in scored if passed],
        "run_warnings": [
            _text(warning, 300) for warning in _list(lighthouse.get("runWarnings"))[:_MAX_WARNINGS]
        ],
        "truncated": False,
    }
    origin = _record(record.get("originLoadingExperience"))
    return PageSpeedTest(
        final_url=final_url,
        summary=summary,
        origin_field=_field(origin, page=False) if _same_origin(origin, requested_url) else None,
        report=_bounded(report),
    )


def report_json(report: dict[str, Any]) -> str:
    """Serialises a report as ASCII JSON, so its character count equals its byte count."""
    return json.dumps(report, ensure_ascii=True, separators=(",", ":"))


def url_origin(url: str) -> str:
    """Returns a URL's origin as a browser writes it, such as `https://example.com`."""
    parsed = httpx2.URL(url)
    host = ascii_host(parsed)
    port = f":{parsed.port}" if parsed.port is not None else ""
    return f"{parsed.scheme}://{host}{port}"


async def _check_page_url(
    url: str, *, blocked_domains: tuple[str, ...], resolver: Resolver
) -> None:
    try:
        parsed = validate_public_url(url, standard_ports_only=True)
        host = ascii_host(parsed)
        if blocked_domain_for_host(host, blocked_domains) is not None:
            raise PageSpeedError("URL is on the blocked domain list", error_class="blocked_domain")
        await resolver(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except WebFetchError as exc:
        raise PageSpeedError(exc.message, error_class=exc.error_class) from exc


def _error_class(response: httpx2.Response) -> PageSpeedErrorClass:
    try:
        error = _record(_record(response.json()).get("error"))
    except ValueError:
        error = {}
    message = error.get("message") if isinstance(error.get("message"), str) else ""
    if match := _LIGHTHOUSE_ERROR.search(message):
        return _lighthouse_error_class(match[1])
    if response.status_code == 429:
        return "quota_exceeded"
    if response.status_code in {401, 403} or "API key" in message or "API_KEY" in response.text:
        return "key_rejected"
    if response.status_code == 400:
        return "page_error"
    return "service_error"


def _lighthouse_error_class(code: str) -> PageSpeedErrorClass:
    return "page_unreachable" if code in _UNREACHABLE_ERRORS else "page_error"


def _scored_audits(
    lighthouse: dict[str, Any],
    audits: dict[str, Any],
    categories: tuple[PageSpeedCategory, ...],
) -> Iterator[tuple[PageSpeedCategory, dict[str, Any], bool]]:
    seen: set[str] = set()
    lighthouse_categories = _record(lighthouse.get("categories"))
    for category in categories:
        refs = _list(
            _record(lighthouse_categories.get(_LIGHTHOUSE_CATEGORIES[category])).get("auditRefs")
        )
        for ref in map(_record, refs):
            audit_id = ref.get("id")
            if ref.get("group") in _SKIPPED_GROUPS or audit_id in seen:
                continue
            audit = _record(audits.get(audit_id))
            score = audit.get("score")
            if (
                _matching(audit_id, AUDIT_ID) is None
                or audit.get("scoreDisplayMode") not in _SCORED_MODES
                or not isinstance(score, int | float)
            ):
                continue
            seen.add(audit_id)
            yield category, {**audit, "id": audit_id}, score >= 0.9


def _scores(
    lighthouse: dict[str, Any], categories: tuple[PageSpeedCategory, ...]
) -> dict[str, int | None]:
    lighthouse_categories = _record(lighthouse.get("categories"))
    scores: dict[str, int | None] = {}
    for category in categories:
        score = _record(lighthouse_categories.get(_LIGHTHOUSE_CATEGORIES[category])).get("score")
        scores[category] = round(score * 100) if isinstance(score, int | float) else None
    return scores


def _lab(audits: dict[str, Any]) -> dict[str, int | float | None]:
    lab: dict[str, int | float | None] = {}
    for key, audit_id in _LAB_METRICS.items():
        value = _record(audits.get(audit_id)).get("numericValue")
        if not isinstance(value, int | float):
            lab[key] = None
        else:
            lab[key] = round(value, 3) if key == "cls" else round(value)
    return lab


def _field(experience: Any, *, page: bool) -> dict[str, Any] | None:
    record = _record(experience)
    # Without page data, Google falls back to the origin's data; that isn't the page's.
    if page and record.get("origin_fallback"):
        return None
    metrics = _record(record.get("metrics"))
    field: dict[str, Any] = {}
    for key, name in _FIELD_METRICS.items():
        metric = _record(metrics.get(name))
        percentile = metric.get("percentile")
        if not isinstance(percentile, int | float):
            continue
        # Google reports layout shift multiplied by 100.
        value = round(percentile / 100, 3) if key == "cls" else round(percentile)
        field[key] = {"p75": value, "rating": _FIELD_RATINGS.get(metric.get("category"))}
    if not field:
        return None
    field["core_web_vitals"] = _core_web_vitals(field)
    return field


def _core_web_vitals(field: dict[str, Any]) -> Literal["passed", "failed"] | None:
    # Google assesses LCP and CLS, plus INP when the page has interaction data.
    if "lcp_ms" not in field or "cls" not in field:
        return None
    vitals = [field[key] for key in ("lcp_ms", "inp_ms", "cls") if key in field]
    return "passed" if all(metric["rating"] == "good" for metric in vitals) else "failed"


def _same_origin(origin: dict[str, Any], requested_url: str) -> bool:
    origin_id = origin.get("id")
    return isinstance(origin_id, str) and origin_id.rstrip("/") == url_origin(requested_url)


def _top_issues(
    failed: list[tuple[PageSpeedCategory, dict[str, Any]]],
) -> list[dict[str, int | str]]:
    savings = [
        (*_savings(audit), audit["id"]) for category, audit in failed if category == "performance"
    ]
    ranked = sorted((saving for saving in savings if saving[0] or saving[1]), reverse=True)
    return [
        {"audit": audit_id, "saving_ms": saving_ms, "saving_bytes": saving_bytes}
        for saving_ms, saving_bytes, audit_id in ranked[:_MAX_TOP_ISSUES]
    ]


def _savings(audit: dict[str, Any]) -> tuple[int, int]:
    details = _record(audit.get("details"))
    metric_savings = _record(audit.get("metricSavings"))
    candidates = [details.get("overallSavingsMs"), *map(metric_savings.get, _SAVING_METRICS)]
    saving_ms = max((value for value in candidates if isinstance(value, int | float)), default=0)
    saving_bytes = details.get("overallSavingsBytes")
    return round(saving_ms), round(saving_bytes) if isinstance(saving_bytes, int | float) else 0


def _failed_audit(category: PageSpeedCategory, audit: dict[str, Any]) -> dict[str, Any]:
    saving_ms, saving_bytes = _savings(audit)
    rows = [item for item in map(_item, _detail_rows(audit)) if item]
    return {
        "id": audit["id"],
        "category": category,
        "title": _text(audit.get("title"), 200),
        "description": _text(audit.get("description"), 600),
        "display_value": _text(audit.get("displayValue"), 200),
        "score": round(audit["score"], 2),
        "saving_ms": saving_ms,
        "saving_bytes": saving_bytes,
        "item_count": len(rows),
        "items": rows[:_MAX_ITEMS],
    }


def _detail_rows(audit: Any) -> list[dict[str, Any]]:
    details = _record(_record(audit).get("details"))
    if details.get("type") not in _DETAIL_TYPES:
        return []
    rows: list[dict[str, Any]] = []
    for item in map(_record, _list(details.get("items"))):
        if details.get("type") != "list":
            rows.append(item)
        elif item.get("type") == "node":
            rows.append({"node": item})
        elif item.get("type") in _DETAIL_TYPES:
            rows.extend(map(_record, _list(item.get("items"))))
    return rows


def _item(raw: dict[str, Any]) -> dict[str, Any]:
    item: dict[str, Any] = {}
    url = raw.get("url") or _record(raw.get("source")).get("url")
    if isinstance(url, str):
        item["url"] = _text(url, 500)
    node = _record(raw.get("node"))
    if node.get("type") == "node":
        item.update(_node(node))
    for key, name in _ITEM_NUMBERS.items():
        if isinstance(raw.get(key), int | float):
            item[name] = round(raw[key])
    if entity := _entity(raw.get("entity")):
        item["entity"] = entity
    return item


def _node(node: dict[str, Any]) -> dict[str, str | None]:
    return {
        "selector": _text(node.get("selector"), 300),
        "snippet": _text(node.get("snippet"), 300),
        "label": _text(node.get("nodeLabel"), 200),
    }


def _lcp_element(audits: dict[str, Any]) -> dict[str, str | None] | None:
    for audit_id in _LCP_AUDITS:
        for row in _detail_rows(audits.get(audit_id)):
            node = _record(row.get("node"))
            if node.get("type") == "node":
                return _node(node)
    return None


def _third_parties(audits: dict[str, Any]) -> list[dict[str, Any]]:
    for audit_id in _THIRD_PARTY_AUDITS:
        rows = _detail_rows(audits.get(audit_id))
        if rows:
            return [
                {
                    "entity": _entity(row.get("entity")),
                    "transfer_bytes": _whole(row.get("transferSize")),
                    "blocking_ms": _whole(row.get("blockingTime")),
                    "main_thread_ms": _whole(row.get("mainThreadTime")),
                }
                for row in rows[:_MAX_THIRD_PARTIES]
            ]
    return []


def _final_url(payload: dict[str, Any], lighthouse: dict[str, Any]) -> str | None:
    for value in (
        lighthouse.get("finalDisplayedUrl"),
        lighthouse.get("mainDocumentUrl"),
        lighthouse.get("finalUrl"),
        payload.get("id"),
    ):
        if isinstance(value, str) and value:
            return _text(value, 2_048)
    return None


def _bounded(report: dict[str, Any]) -> dict[str, Any]:
    """Shortens a report until it fits `REPORT_MAX_BYTES`, trimming detail items first."""
    for limit in (_MAX_ITEMS, 10, 5, 0):
        for audit in report["failed_audits"]:
            audit["items"] = audit["items"][:limit]
        if len(report_json(report)) <= REPORT_MAX_BYTES:
            return report
    report["truncated"] = True
    report["passed_audits"] = []
    report["third_parties"] = []
    while report["failed_audits"] and len(report_json(report)) > REPORT_MAX_BYTES:
        report["failed_audits"].pop()
    return report


def _entity(value: Any) -> str | None:
    # Lighthouse names a third party as a string or, in earlier versions, a link record.
    text = value.get("text") if isinstance(value, dict) else value
    return _text(text, 100)


def _matching(value: Any, pattern: re.Pattern[str]) -> str | None:
    return value if isinstance(value, str) and pattern.fullmatch(value) else None


def _text(value: Any, limit: int) -> str | None:
    return value[:limit] if isinstance(value, str) and value else None


def _whole(value: Any) -> int | None:
    return round(value) if isinstance(value, int | float) else None


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
