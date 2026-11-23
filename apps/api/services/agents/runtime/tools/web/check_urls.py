# apps/api/services/agents/runtime/tools/web/check_urls.py

"""Checks the status, redirects, and key headers of many URLs in one call, with no model call.

Each URL runs through the shared transport with the run's per-host limit. One deadline
and the run's URL budget bound the call; URLs past either return `not_checked`.
"""

import asyncio
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field
from pydantic_ai import ModelRetry, RunContext

from core.settings import settings
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools import (
    TOOL_EGRESS_ARBITRARY_URL,
    TOOL_POLICY_AUTO,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.agents.runtime.tools.registry import runtime_tool
from services.agents.runtime.tools.web.nodes import WebRedirect, redirect_nodes, untrusted
from services.agents.runtime.untrusted import UntrustedNode
from services.web import fetch_url as fetch_public_url
from services.web.domain import FetchedResponse, UserAgent, WebFetchError, WebFetchErrorClass
from services.web.utils import configured_blocked_domains, content_kind
from utils.document_markdown import DocumentConversionError, read_page_facts

_KEY_HEADERS = (
    "x-robots-tag",
    "link",
    "cache-control",
    "strict-transport-security",
    "last-modified",
)
_PAGE_FACT_TEXT = ("title", "description", "canonical", "robots")
# Bounds open connections across hosts; the run's limiter still bounds each host.
_PARALLEL_REQUESTS = 10


class CheckedPage(BaseModel):
    title: UntrustedNode | None
    description: UntrustedNode | None
    canonical: UntrustedNode | None
    robots: UntrustedNode | None = Field(description="The meta robots tag.")
    h1_count: int


class CheckedUrl(BaseModel):
    requested_url: str
    status: int | None = Field(description="The final status; null when the check failed.")
    redirects: list[WebRedirect]
    final_url: UntrustedNode | None
    content_type: UntrustedNode | None
    content_length: int | None
    headers: dict[str, UntrustedNode]
    time_to_first_byte_ms: int | None
    blocked_by_site: bool = Field(
        description="True when the site refused an automated request, not a broken page."
    )
    error_class: WebFetchErrorClass | Literal["not_checked"] | None = Field(
        description=(
            "Why the check failed; not_checked means the call ran out of time or run budget."
        )
    )
    page: CheckedPage | None = Field(description="Facts from an HTML body, with page_facts.")


class CheckUrlsOutput(BaseModel):
    """Model-visible result returned by `check_urls`."""

    user_agent: UserAgent
    checked_at: str
    checked: int
    not_checked: int
    budget_remaining: int = Field(description="URLs this run can still fetch or check.")
    rows: list[CheckedUrl]


@runtime_tool(
    name="check_urls",
    provider="web",
    label="Check URLs",
    code_eligible=True,
    description=(
        f"Check up to {settings.WEB_FETCH_MAX_URLS_PER_CALL} public URLs at once for status, "
        "redirect hops, final URL, content type and length, key headers (x-robots-tag, link, "
        "cache-control, strict-transport-security, last-modified), and time to first byte, "
        "with no model cost. It reads headers only. Set page_facts to also read each HTML "
        "page's title, meta description, canonical, meta robots, and H1 count. A 404 or 500 "
        "is a row with its status; blocked_by_site means the site refused an automated "
        "request; error_class names a failed check. URLs the call has no time or run budget "
        "left for return error_class='not_checked': send them again while budget_remaining "
        "is above 0. To check a sitemap, fetch it and check its URLs in one run_code script. "
        "Use fetch_url to read one page."
    ),
    supports_approval=True,
    supports_auto=True,
    default_policy=TOOL_POLICY_AUTO,
    egress=TOOL_EGRESS_ARBITRARY_URL,
    takes_ctx=True,
    timeout=None,
    output_model=CheckUrlsOutput,
    preview_list_path="rows",
    presentation=ToolPresentation(
        icon="link",
        running_label="Checking URLs",
        completed_label="Checked URLs",
        failed_label="Couldn't Check URLs",
        approval_title="Check URLs",
        approval_prompt="The agent wants to check these URLs.",
        approve_label="Approve & Check",
        arg_fields=(
            ToolFieldPresentation(key="urls", label="URLs", format="list", editable=True),
            ToolFieldPresentation(
                key="page_facts", label="Read Page Facts", format="boolean", editable=True
            ),
            ToolFieldPresentation(key="user_agent", label="Browser", secondary=True),
        ),
    ),
)
async def check_urls(
    ctx: RunContext[RuntimeDeps],
    urls: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=2_048)]],
        Field(
            min_length=1,
            max_length=settings.WEB_FETCH_MAX_URLS_PER_CALL,
            description="HTTP(S) URLs. Duplicates are checked once.",
        ),
    ],
    user_agent: Annotated[
        UserAgent,
        Field(
            description=(
                "praxis (default, an honest agent), desktop_browser, mobile_browser, "
                "googlebot_desktop, or googlebot_mobile."
            )
        ),
    ] = "praxis",
    page_facts: Annotated[
        bool,
        Field(description="Also read each HTML page's title, description, canonical, and H1s."),
    ] = False,
) -> dict[str, Any]:
    """Checks each URL once, concurrently, within one deadline."""
    unique = list(dict.fromkeys(urls))
    budget = ctx.deps.web_fetch_budget
    if budget.remaining < 1:
        raise ModelRetry(f"This run has fetched its limit of {budget.max_urls} URLs.")
    # A partial batch still returns its rows, so a script doesn't lose the work it has done.
    batch, over_budget = unique[: budget.remaining], unique[budget.remaining :]
    budget.take(len(batch))
    rows = await _check_all(ctx.deps, batch, user_agent=user_agent, page_facts=page_facts)
    rows += [_failed_row(url, "not_checked") for url in over_budget]
    not_checked = sum(1 for row in rows if row["error_class"] == "not_checked")
    return {
        "user_agent": user_agent,
        "checked_at": datetime.now(UTC).isoformat(),
        "checked": len(rows) - not_checked,
        "not_checked": not_checked,
        "budget_remaining": budget.remaining,
        "rows": rows,
    }


async def _check_all(
    deps: RuntimeDeps, urls: list[str], *, user_agent: UserAgent, page_facts: bool
) -> list[dict[str, Any]]:
    slots = asyncio.Semaphore(_PARALLEL_REQUESTS)
    blocked_domains = configured_blocked_domains()

    async def check(url: str) -> dict[str, Any]:
        async with slots:
            return await _check_one(
                deps,
                url,
                user_agent=user_agent,
                page_facts=page_facts,
                blocked_domains=blocked_domains,
            )

    tasks = [asyncio.create_task(check(url)) for url in urls]
    try:
        _, pending = await asyncio.wait(tasks, timeout=settings.WEB_FETCH_BATCH_DEADLINE_SECONDS)
    finally:
        # Also runs when the run itself is cancelled, so no request outlives the call.
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return [
        _failed_row(url, "not_checked") if task in pending else task.result()
        for url, task in zip(urls, tasks, strict=True)
    ]


async def _check_one(
    deps: RuntimeDeps,
    url: str,
    *,
    user_agent: UserAgent,
    page_facts: bool,
    blocked_domains: tuple[str, ...],
) -> dict[str, Any]:
    try:
        response = await fetch_public_url(
            url,
            timeout_seconds=settings.WEB_FETCH_TIMEOUT_SECONDS,
            max_redirects=settings.WEB_FETCH_MAX_REDIRECTS,
            max_bytes=settings.WEB_FETCH_MAX_BYTES,
            user_agent=user_agent,
            body="success" if page_facts else "none",
            standard_ports_only=True,
            blocked_domains=blocked_domains,
            limiter=deps.web_fetch_budget.limiter,
        )
    except WebFetchError as exc:
        return _failed_row(url, exc.error_class, redirects=redirect_nodes(url, exc.redirects))
    page = await _page(response) if page_facts else None
    return {
        "requested_url": url,
        "status": response.status,
        "redirects": redirect_nodes(url, response.redirects),
        "final_url": untrusted(url, response.final_url),
        "content_type": untrusted(url, response.content_type),
        "content_length": _content_length(response),
        "headers": {
            name: untrusted(url, response.headers[name])
            for name in _KEY_HEADERS
            if name in response.headers
        },
        "time_to_first_byte_ms": response.time_to_first_byte_ms,
        "blocked_by_site": response.blocked_by_site,
        "error_class": None,
        "page": page,
    }


async def _page(response: FetchedResponse) -> dict[str, Any] | None:
    if not response.body or content_kind(response) != "html":
        return None
    try:
        facts = await read_page_facts(response.body)
    except DocumentConversionError:
        return None
    source = response.requested_url
    return {
        **{key: untrusted(source, facts[key]) if facts[key] else None for key in _PAGE_FACT_TEXT},
        "h1_count": facts["h1_count"],
    }


def _content_length(response: FetchedResponse) -> int | None:
    header = response.headers.get("content-length", "")
    if header.isdigit():
        return int(header)
    return len(response.body) if response.body_read else None


def _failed_row(
    url: str,
    error_class: WebFetchErrorClass | Literal["not_checked"],
    *,
    redirects: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "requested_url": url,
        "status": None,
        "redirects": redirects or [],
        "final_url": None,
        "content_type": None,
        "content_length": None,
        "headers": {},
        "time_to_first_byte_ms": None,
        "blocked_by_site": False,
        "error_class": error_class,
        "page": None,
    }
