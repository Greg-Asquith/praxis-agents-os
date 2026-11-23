# apps/api/services/agents/runtime/tools/web/inspect_page.py

"""Returns typed facts about one page, sitemap, or robots.txt, with no model call.

The response decides the kind: HTML is a page, `robots.txt` is read as rules, and XML or
gzipped text is tried as a sitemap. Extraction runs in the document worker, and every
string the server chose crosses dispatch as a `web_fetch` provenance node.
"""

import asyncio
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

import httpx2
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
from services.agents.runtime.untrusted import UntrustedContent, UntrustedNode
from services.web import fetch_url as fetch_public_url
from services.web.domain import FetchedResponse, UserAgent, WebFetchError
from services.web.utils import configured_blocked_domains, content_kind
from utils.document_markdown import DocumentConversionError, inspect_web_document

PageFact = Literal["meta", "headings", "links", "images", "structured_data", "tags", "headers"]
InspectedKind = Literal["page", "sitemap", "robots", "unsupported"]

_DEFAULT_INCLUDE: tuple[PageFact, ...] = ("meta", "headings", "tags")
_META_TEXT = ("title", "description", "robots", "canonical", "language", "viewport", "meta_refresh")
_XML_PREFIX_STRIP = b"\xef\xbb\xbf \t\r\n"
_MAX_BUNDLE_BYTES = 2 * 1024 * 1024


class HreflangLink(BaseModel):
    lang: UntrustedNode
    url: UntrustedNode


class PageMeta(BaseModel):
    title: UntrustedNode | None
    description: UntrustedNode | None
    robots: UntrustedNode | None = Field(description="The meta robots tag.")
    canonical: UntrustedNode | None
    language: UntrustedNode | None = Field(description="The html lang attribute.")
    viewport: UntrustedNode | None
    meta_refresh: UntrustedNode | None
    hreflang: list[HreflangLink]
    open_graph: dict[str, UntrustedNode]


class Heading(BaseModel):
    level: int
    text: UntrustedNode | None


class PageHeadings(BaseModel):
    total: int
    h1_count: int
    items: list[Heading]


class PageLink(BaseModel):
    url: UntrustedNode
    text: UntrustedNode | None
    internal: bool = Field(description="Same host as the page, ignoring www.")
    nofollow: bool


class PageLinks(BaseModel):
    total: int
    internal: int
    external: int
    nofollow: int
    items: list[PageLink]


class PageImage(BaseModel):
    src: UntrustedNode | None
    alt: UntrustedNode | None = Field(
        description="Null when missing; empty for a decorative image."
    )


class PageImages(BaseModel):
    total: int
    missing_alt: int
    items: list[PageImage]


class StructuredDataBlock(BaseModel):
    valid: bool = Field(description="False when the JSON-LD doesn't parse.")
    types: list[UntrustedNode]
    content: UntrustedNode
    truncated: bool


class PageStructuredData(BaseModel):
    total: int
    blocks: list[StructuredDataBlock]


class PageTag(BaseModel):
    vendor: str
    category: Literal["tag_manager", "analytics", "advertising", "experience", "consent"]
    id: str | None = Field(description="The tag ID, such as GTM-ABC123; null when only present.")
    found_in: Literal["script_src", "inline_script", "noscript", "script_bundle"]


class PageFacts(BaseModel):
    word_count: int
    looks_client_rendered: bool = Field(
        description="True when scripts likely build the page in a browser; the source lacks it."
    )
    meta: PageMeta | None
    headings: PageHeadings | None
    links: PageLinks | None
    images: PageImages | None
    structured_data: PageStructuredData | None
    tags: list[PageTag] | None


class SitemapEntry(BaseModel):
    loc: UntrustedNode
    lastmod: str | None


class SitemapFacts(BaseModel):
    type: Literal["urlset", "sitemapindex"] = Field(
        description="urlset lists pages; sitemapindex lists child sitemaps."
    )
    total: int
    entries: list[SitemapEntry]


class RobotsGroup(BaseModel):
    user_agents: list[UntrustedNode]
    allow: list[UntrustedNode]
    disallow: list[UntrustedNode]
    crawl_delay: float | None


class RobotsFacts(BaseModel):
    groups: list[RobotsGroup]
    sitemaps: list[UntrustedNode]
    truncated: bool


class InspectPageOutput(BaseModel):
    """Model-visible result returned by `inspect_page`."""

    requested_url: str
    final_url: UntrustedNode
    status: int
    redirects: list[WebRedirect]
    blocked_by_site: bool = Field(
        description="True when the site refused an automated request, not a broken page."
    )
    user_agent: UserAgent
    content_type: UntrustedNode
    fetched_at: str
    kind: InspectedKind | None = Field(description="Null when the response wasn't 2xx.")
    headers: dict[str, UntrustedNode] | None
    page: PageFacts | None
    sitemap: SitemapFacts | None
    robots: RobotsFacts | None
    note: str | None = Field(description="Guidance about this result, such as what it can't show.")


@runtime_tool(
    name="inspect_page",
    provider="web",
    label="Inspect Page",
    code_eligible=True,
    description=(
        "Fetch one public URL and return structured facts, with no model cost. For an HTML "
        "page, include selects meta (title, description, robots, canonical, language, "
        "hreflang, viewport, Open Graph, meta refresh), headings, links (internal, "
        "external, nofollow), images (address, alt text, missing alt count), "
        "structured_data (JSON-LD types and blocks), tags (Google Tag Manager, Google "
        "Analytics, Google Ads, Meta Pixel, LinkedIn, TikTok, Hotjar, Clarity, and consent "
        "banners with their IDs), and headers. Default: meta, headings, and tags. Every page "
        "also returns its word count and looks_client_rendered: when true, say the page "
        "needs a browser rather than reporting missing content. With tags, it also scans up "
        "to 20 of the site's own script bundles, where frameworks such as Next.js set "
        "analytics up; each counts against the run's URL budget. Tags loaded through a tag "
        "manager still don't appear. For an XML sitemap (gzipped or an index) "
        "it returns entries with loc and lastmod; for robots.txt, its groups and sitemaps. "
        "A 404 or 500 returns its status with nothing inspected. Use fetch_url for the "
        "content itself and check_urls for status across many URLs."
    ),
    supports_approval=True,
    supports_auto=True,
    default_policy=TOOL_POLICY_AUTO,
    egress=TOOL_EGRESS_ARBITRARY_URL,
    takes_ctx=True,
    timeout=None,
    output_model=InspectPageOutput,
    presentation=ToolPresentation(
        icon="link",
        running_label="Inspecting {url}",
        completed_label="Inspected {url}",
        failed_label="Couldn't Inspect Page",
        approval_title="Inspect Page",
        approval_prompt="The agent wants to inspect this URL: {url}.",
        approve_label="Approve & Inspect",
        arg_fields=(
            ToolFieldPresentation(
                key="url",
                label="URL",
                editable=True,
                placeholder="https://example.com/page",
            ),
            ToolFieldPresentation(key="include", label="Facts", format="list", secondary=True),
            ToolFieldPresentation(key="user_agent", label="Browser", secondary=True),
        ),
    ),
)
async def inspect_page(
    ctx: RunContext[RuntimeDeps],
    url: Annotated[
        str,
        Field(
            min_length=1,
            max_length=2_048,
            description="HTTP(S) URL of a page, an XML sitemap, or robots.txt.",
        ),
    ],
    include: Annotated[
        list[PageFact] | None,
        Field(
            description=(
                "For a page: any of meta, headings, links, images, structured_data, tags, "
                "and headers. Omit for meta, headings, and tags."
            )
        ),
    ] = None,
    user_agent: Annotated[
        UserAgent,
        Field(
            description=(
                "praxis (default, an honest agent), desktop_browser, mobile_browser, "
                "googlebot_desktop, or googlebot_mobile."
            )
        ),
    ] = "praxis",
) -> dict[str, Any]:
    """Fetches one URL and returns the facts its content type supports."""
    selected = frozenset(_DEFAULT_INCLUDE if include is None else include)
    if not ctx.deps.web_fetch_budget.take():
        raise ModelRetry(
            f"This run has fetched its limit of {ctx.deps.web_fetch_budget.max_urls} URLs."
        )
    try:
        # One deadline covers resolution, redirects, reading, and extraction.
        async with asyncio.timeout(settings.WEB_FETCH_TIMEOUT_SECONDS):
            response = await fetch_public_url(
                url,
                timeout_seconds=settings.WEB_FETCH_TIMEOUT_SECONDS,
                max_redirects=settings.WEB_FETCH_MAX_REDIRECTS,
                max_bytes=settings.WEB_FETCH_MAX_BYTES,
                user_agent=user_agent,
                body="success",
                gunzip=True,
                standard_ports_only=True,
                blocked_domains=configured_blocked_domains(),
                limiter=ctx.deps.web_fetch_budget.limiter,
            )
            kind, facts = await _inspect(response, selected)
    except WebFetchError as exc:
        raise ModelRetry(
            f"inspect_page couldn't fetch that URL ({exc.error_class}): {exc.message}."
        ) from None
    except TimeoutError:
        raise ModelRetry(
            "inspect_page couldn't fetch that URL (timeout): it took too long."
        ) from None

    if kind == "page" and facts["script_urls"]:
        await _scan_script_bundles(ctx.deps, facts, user_agent=user_agent)
    source = response.requested_url
    return {
        "requested_url": source,
        "final_url": untrusted(source, response.final_url),
        "status": response.status,
        "redirects": redirect_nodes(source, response.redirects),
        "blocked_by_site": response.blocked_by_site,
        "user_agent": response.user_agent,
        "content_type": untrusted(source, response.content_type),
        "fetched_at": datetime.now(UTC).isoformat(),
        "kind": kind,
        "headers": (
            {name: untrusted(source, value) for name, value in response.headers.items()}
            if "headers" in selected
            else None
        ),
        "page": _page_nodes(source, facts) if kind == "page" else None,
        "sitemap": _sitemap_nodes(source, facts) if kind == "sitemap" else None,
        "robots": _robots_nodes(source, facts) if kind == "robots" else None,
        "note": _note(response, kind, facts),
    }


async def _inspect(
    response: FetchedResponse, include: frozenset[PageFact]
) -> tuple[InspectedKind | None, dict[str, Any]]:
    if not 200 <= response.status < 300 or not response.body:
        return None, {}
    body_kind = content_kind(response)
    path = httpx2.URL(response.final_url).path.lower()
    try:
        if body_kind == "html":
            facts = await inspect_web_document(
                "inspect_web_page",
                response.body,
                include=sorted(include - {"headers"}),
                base_url=response.final_url,
            )
            return "page", facts
        if body_kind == "text" and path.endswith("/robots.txt"):
            return "robots", await inspect_web_document("read_robots", response.body)
        if body_kind == "text" and response.body.lstrip(_XML_PREFIX_STRIP).startswith(b"<"):
            facts = await inspect_web_document("read_sitemap", response.body)
            return ("sitemap", facts) if facts["type"] else ("unsupported", {})
    except DocumentConversionError:
        return "unsupported", {"unreadable": True}
    return "unsupported", {}


async def _scan_script_bundles(
    deps: RuntimeDeps, facts: dict[str, Any], *, user_agent: UserAgent
) -> None:
    """Adds tags found in the page's same-site script bundles to `facts["tags"]`.

    Frameworks such as Next.js set analytics up inside their bundles, so the page source
    holds no tag. Each bundle counts against the run budget; one that fails is skipped.
    """
    budget = deps.web_fetch_budget
    urls = facts["script_urls"][: budget.remaining]
    budget.take(len(urls))
    blocked_domains = configured_blocked_domains()

    async def fetch(bundle_url: str) -> bytes:
        response = await fetch_public_url(
            bundle_url,
            timeout_seconds=settings.WEB_FETCH_TIMEOUT_SECONDS,
            max_redirects=settings.WEB_FETCH_MAX_REDIRECTS,
            max_bytes=min(settings.WEB_FETCH_MAX_BYTES, _MAX_BUNDLE_BYTES),
            user_agent=user_agent,
            body="success",
            standard_ports_only=True,
            blocked_domains=blocked_domains,
            limiter=budget.limiter,
        )
        return response.body if 200 <= response.status < 300 else b""

    tasks = [asyncio.create_task(fetch(bundle_url)) for bundle_url in urls]
    try:
        await asyncio.wait(tasks, timeout=settings.WEB_FETCH_TIMEOUT_SECONDS)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    bodies = [
        task.result()
        for task in tasks
        if not task.cancelled() and task.exception() is None and task.result()
    ]
    facts["bundles_scanned"] = len(bodies)
    facts["bundles_found"] = len(facts["script_urls"])
    if not bodies:
        return
    try:
        result = await inspect_web_document(
            "find_bundle_tags",
            b"".join(bodies),
            sizes=[len(body) for body in bodies],
            known=facts["tags"],
        )
    except DocumentConversionError:
        return
    facts["tags"] = result["tags"]


def _page_nodes(source: str, facts: dict[str, Any]) -> dict[str, Any]:
    def node(value: str | None) -> UntrustedContent | None:
        return untrusted(source, value) if value is not None else None

    meta, headings, links, images, data = (
        facts[key] for key in ("meta", "headings", "links", "images", "structured_data")
    )
    return {
        "word_count": facts["word_count"],
        "looks_client_rendered": facts["looks_client_rendered"],
        "meta": {
            **{key: node(meta[key]) for key in _META_TEXT},
            "hreflang": [
                {"lang": node(entry["lang"]), "url": node(entry["url"])}
                for entry in meta["hreflang"]
            ],
            "open_graph": {key: node(value) for key, value in meta["open_graph"].items()},
        }
        if meta
        else None,
        "headings": {
            **headings,
            "items": [{**item, "text": node(item["text"])} for item in headings["items"]],
        }
        if headings
        else None,
        "links": {
            **links,
            "items": [
                {**item, "url": node(item["url"]), "text": node(item["text"])}
                for item in links["items"]
            ],
        }
        if links
        else None,
        "images": {
            **images,
            "items": [
                {"src": node(item["src"]), "alt": node(item["alt"])} for item in images["items"]
            ],
        }
        if images
        else None,
        "structured_data": {
            **data,
            "blocks": [
                {
                    **block,
                    "types": [node(name) for name in block["types"] if name],
                    "content": node(block["content"]),
                }
                for block in data["blocks"]
            ],
        }
        if data
        else None,
        # Vendors are Praxis names and IDs match fixed patterns, so tags carry no page text.
        "tags": facts["tags"],
    }


def _sitemap_nodes(source: str, facts: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": facts["type"],
        "total": facts["total"],
        "entries": [
            {"loc": untrusted(source, entry["loc"]), "lastmod": entry["lastmod"]}
            for entry in facts["entries"]
        ],
    }


def _robots_nodes(source: str, facts: dict[str, Any]) -> dict[str, Any]:
    def nodes(values: list[str]) -> list[UntrustedContent]:
        return [untrusted(source, value) for value in values]

    return {
        "groups": [
            {
                "user_agents": nodes(group["user_agents"]),
                "allow": nodes(group["allow"]),
                "disallow": nodes(group["disallow"]),
                "crawl_delay": group["crawl_delay"],
            }
            for group in facts["groups"]
        ],
        "sitemaps": nodes(facts["sitemaps"]),
        "truncated": facts["truncated"],
    }


def _note(
    response: FetchedResponse, kind: InspectedKind | None, facts: dict[str, Any]
) -> str | None:
    if response.blocked_by_site:
        return "The site refused an automated request; the page itself may be fine."
    if kind is None:
        return f"The URL returned status {response.status}, so there was nothing to inspect."
    if facts.get("unreadable"):
        return "The response couldn't be read; fetch_url returns it as served."
    if kind == "unsupported":
        return (
            "inspect_page reads HTML pages, XML sitemaps, and robots.txt; use fetch_url for "
            "this content type."
        )
    if kind == "sitemap" and facts["total"] > len(facts["entries"]):
        return (
            f"The sitemap lists {facts['total']:,} entries and the first "
            f"{len(facts['entries']):,} are returned. Parse the rest from fetch_url in run_code."
        )
    if kind != "page":
        return None
    notes = []
    if facts["looks_client_rendered"]:
        notes.append(
            "The page looks built by scripts in the browser, so its source may lack what a "
            "visitor sees."
        )
    scanned, found = facts.get("bundles_scanned", 0), facts.get("bundles_found", 0)
    if scanned < found:
        notes.append(
            f"Only {scanned} of the page's {found} script bundles were scanned for tags, so "
            "some tags may be missing."
        )
    containers = [tag["id"] for tag in facts["tags"] or () if tag["category"] == "tag_manager"]
    if containers and containers[0]:
        notes.append(
            "Tags loaded through Google Tag Manager don't appear in the page source. To list "
            "them, fetch_url https://www.googletagmanager.com/gtm.js?id="
            f"{containers[0]} and read the container."
        )
    return " ".join(notes) or None
