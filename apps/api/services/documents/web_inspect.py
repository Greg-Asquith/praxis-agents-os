# apps/api/services/documents/web_inspect.py

"""Typed facts about a fetched page, sitemap, or robots.txt. Imported only inside the worker.

Every list is capped and reports its full count, so a result stays bounded on any page.
"""

import json
import re
from typing import Any
from urllib.parse import urljoin, urlsplit

from services.documents.web_page import (
    NON_CONTENT_TAGS,
    bounded_text,
    link_href,
    meta_content,
    page_title,
)
from services.documents.web_tags import find_tags, tags_in_sources

type HandlerResult = tuple[dict[str, Any], bytes | None]

_MAX_HEADINGS = 300
_MAX_LINKS = 1_000
_MAX_IMAGES = 500
_MAX_HREFLANG = 100
_MAX_OPEN_GRAPH = 30
_MAX_JSON_LD_BLOCKS = 10
_MAX_JSON_LD_CHARS = 5_000
_MAX_SITEMAP_ENTRIES = 10_000
_MAX_ROBOTS_GROUPS = 200
_MAX_ROBOTS_RULES = 500
_MAX_ROBOTS_SITEMAPS = 100
_MAX_URL_CHARS = 2_048
_MAX_SCRIPT_BUNDLES = 20
_MAX_LABEL_CHARS = 200
# Elements a client-side framework renders into; empty in the source when the browser fills them.
_APP_MOUNT_IDS = ["root", "app", "__next", "__nuxt", "___gatsby", "svelte"]
_LASTMOD = re.compile(
    r"\d{4}(?:-\d{2}(?:-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?)?)?)?"
)


def inspect_web_page(
    _format: str, args: dict[str, Any], data: bytes, _limits: Any
) -> HandlerResult:
    """Returns the facts `args["include"]` selects, with word count and a client-rendering hint.

    `args["base_url"]` is the final URL, which resolves relative links and images.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(data, "html.parser")
    include = frozenset(args["include"])
    base_url = _base_url(soup, args["base_url"])
    # Scripts are read before word counting removes them.
    facts: dict[str, Any] = {
        "meta": _meta(soup, base_url) if "meta" in include else None,
        "headings": _headings(soup) if "headings" in include else None,
        "links": _links(soup, base_url) if "links" in include else None,
        "images": _images(soup, base_url) if "images" in include else None,
        "structured_data": _structured_data(soup) if "structured_data" in include else None,
        "tags": find_tags(soup) if "tags" in include else None,
        # Frameworks often set tags up inside the site's own bundles, so the tool scans them too.
        "script_urls": _same_site_scripts(soup, base_url) if "tags" in include else [],
    }
    script_count = len(soup.find_all("script"))
    empty_mount = any(not tag.get_text(strip=True) for tag in soup.find_all(id=_APP_MOUNT_IDS))
    root = soup.body or soup
    for tag in root.find_all(NON_CONTENT_TAGS):
        if not tag.decomposed:
            tag.decompose()
    word_count = len(root.get_text(" ", strip=True).split())
    facts["word_count"] = word_count
    facts["looks_client_rendered"] = (empty_mount and word_count < 300) or (
        word_count < 50 and script_count >= 2
    )
    return facts, None


def find_bundle_tags(
    _format: str, args: dict[str, Any], data: bytes, _limits: Any
) -> HandlerResult:
    """Returns `args["known"]` tags plus those found in script bundles packed in `data`.

    `args["sizes"]` gives each bundle's length in bytes, in order.
    """
    sources, offset = [], 0
    for size in args["sizes"]:
        sources.append(("script_bundle", data[offset : offset + size].decode("utf-8", "replace")))
        offset += size
    return {"tags": tags_in_sources(sources, args["known"])}, None


def read_sitemap(_format: str, _args: dict[str, Any], data: bytes, _limits: Any) -> HandlerResult:
    """Returns a sitemap's page entries, or an index's child sitemaps, with `loc` and `lastmod`.

    `type` is null when the body isn't a sitemap. DTDs and entities are refused.
    """
    from defusedxml import DefusedXmlException, ElementTree

    try:
        root = ElementTree.fromstring(data, forbid_dtd=True)
    except (ElementTree.ParseError, DefusedXmlException):
        return {"type": None}, None
    sitemap_type = _local_name(root.tag)
    if sitemap_type not in {"urlset", "sitemapindex"}:
        return {"type": None}, None
    child = "url" if sitemap_type == "urlset" else "sitemap"
    entries, total = [], 0
    for element in root:
        if _local_name(element.tag) != child:
            continue
        fields = {_local_name(field.tag): (field.text or "").strip() for field in element}
        if not fields.get("loc"):
            continue
        total += 1
        if len(entries) < _MAX_SITEMAP_ENTRIES:
            lastmod = fields.get("lastmod", "")
            entries.append(
                {
                    "loc": fields["loc"][:_MAX_URL_CHARS],
                    # Only a W3C date passes, so the value carries no free text.
                    "lastmod": lastmod if _LASTMOD.fullmatch(lastmod) else None,
                }
            )
    return {"type": sitemap_type, "total": total, "entries": entries}, None


def read_robots(_format: str, _args: dict[str, Any], data: bytes, _limits: Any) -> HandlerResult:
    """Returns robots.txt groups (user agents, allow, disallow, crawl delay) and its sitemaps.

    Consecutive `User-agent` lines share one group, as crawlers read them.
    """
    groups: list[dict[str, Any]] = []
    sitemaps: list[str] = []
    current: dict[str, Any] | None = None
    reading_agents = False
    truncated = False
    for raw in data.decode("utf-8", "replace").splitlines():
        key, separator, value = raw.partition("#")[0].partition(":")
        key, value = key.strip().lower(), value.strip()[:_MAX_URL_CHARS]
        if not separator:
            continue
        if key == "sitemap":
            truncated |= not _append(sitemaps, value, _MAX_ROBOTS_SITEMAPS)
        elif key == "user-agent":
            if current is None or not reading_agents:
                if len(groups) >= _MAX_ROBOTS_GROUPS:
                    truncated = True
                    break
                current = {"user_agents": [], "allow": [], "disallow": [], "crawl_delay": None}
                groups.append(current)
            current["user_agents"].append(value)
            reading_agents = True
        elif current is not None and key in {"allow", "disallow", "crawl-delay"}:
            reading_agents = False
            if key == "crawl-delay":
                current["crawl_delay"] = _number(value)
            else:
                truncated |= not _append(current[key], value, _MAX_ROBOTS_RULES)
    return {"groups": groups, "sitemaps": sitemaps, "truncated": truncated}, None


def _meta(soup: Any, base_url: str) -> dict[str, Any]:
    html = soup.find("html")
    refresh = next(
        (
            tag.get("content")
            for tag in soup.find_all("meta", attrs={"http-equiv": True})
            if str(tag["http-equiv"]).strip().lower() == "refresh"
        ),
        None,
    )
    hreflang = [
        {"lang": bounded_text(tag.get("hreflang"), 50), "url": _absolute(base_url, tag["href"])}
        for tag in soup.find_all("link", href=True, hreflang=True)
        if "alternate" in [value.lower() for value in tag.get("rel") or ()]
    ]
    open_graph = {}
    for tag in soup.find_all("meta", attrs={"property": True}):
        name = str(tag["property"]).strip().lower()
        content = bounded_text(tag.get("content"))
        if name.startswith("og:") and content and len(open_graph) < _MAX_OPEN_GRAPH:
            open_graph.setdefault(name[:_MAX_LABEL_CHARS], content)
    canonical = link_href(soup, "canonical")
    return {
        "title": page_title(soup),
        "description": meta_content(soup, "description"),
        "robots": meta_content(soup, "robots"),
        "canonical": _absolute(base_url, canonical) if isinstance(canonical, str) else None,
        "language": bounded_text(html.get("lang"), 50) if html is not None else None,
        "viewport": meta_content(soup, "viewport"),
        "meta_refresh": bounded_text(refresh),
        "hreflang": [entry for entry in hreflang if entry["lang"] and entry["url"]][:_MAX_HREFLANG],
        "open_graph": open_graph,
    }


def _headings(soup: Any) -> dict[str, Any]:
    tags = soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
    return {
        "total": len(tags),
        "h1_count": sum(1 for tag in tags if tag.name == "h1"),
        "items": [
            {"level": int(tag.name[1]), "text": bounded_text(tag.get_text(" "), _MAX_LABEL_CHARS)}
            for tag in tags[:_MAX_HEADINGS]
        ],
    }


def _links(soup: Any, base_url: str) -> dict[str, Any]:
    host = _site_host(base_url)
    items = []
    for tag in soup.find_all("a", href=True):
        url = _absolute(base_url, tag["href"])
        # A fragment-only link points within the page.
        if url is None or str(tag["href"]).strip().startswith("#"):
            continue
        rel = [value.lower() for value in tag.get("rel") or ()]
        items.append(
            {
                "url": url,
                "text": bounded_text(tag.get_text(" "), _MAX_LABEL_CHARS),
                "internal": _site_host(url) == host,
                "nofollow": "nofollow" in rel,
            }
        )
    internal = sum(1 for item in items if item["internal"])
    return {
        "total": len(items),
        "internal": internal,
        "external": len(items) - internal,
        "nofollow": sum(1 for item in items if item["nofollow"]),
        "items": items[:_MAX_LINKS],
    }


def _images(soup: Any, base_url: str) -> dict[str, Any]:
    tags = soup.find_all("img")
    items = []
    for tag in tags[:_MAX_IMAGES]:
        src = str(tag.get("src") or tag.get("data-src") or "").strip()
        if src.lower().startswith("data:"):
            # Keeps the media type so the audit still sees what was inlined.
            src = src.partition(",")[0][:_MAX_LABEL_CHARS] + ",[removed]"
        else:
            src = _absolute(base_url, src) or ""
        alt = tag.get("alt")
        items.append(
            {
                "src": src or None,
                # None means the attribute is missing; "" marks a decorative image.
                "alt": " ".join(alt.split())[:_MAX_LABEL_CHARS] if isinstance(alt, str) else None,
            }
        )
    return {
        "total": len(tags),
        "missing_alt": sum(1 for tag in tags if not isinstance(tag.get("alt"), str)),
        "items": items,
    }


def _structured_data(soup: Any) -> dict[str, Any]:
    scripts = [
        tag
        for tag in soup.find_all("script")
        if str(tag.get("type") or "").strip().lower() == "application/ld+json"
    ]
    blocks = []
    for tag in scripts[:_MAX_JSON_LD_BLOCKS]:
        text = tag.get_text().strip()
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        types: list[str] = []
        _collect_types(parsed, types)
        blocks.append(
            {
                "valid": parsed is not None,
                "types": [bounded_text(value, _MAX_LABEL_CHARS) for value in types[:20]],
                "content": text[:_MAX_JSON_LD_CHARS],
                "truncated": len(text) > _MAX_JSON_LD_CHARS,
            }
        )
    return {"total": len(scripts), "blocks": blocks}


def _collect_types(value: Any, types: list[str]) -> None:
    if isinstance(value, list):
        for item in value:
            _collect_types(item, types)
    elif isinstance(value, dict):
        declared = value.get("@type")
        for name in declared if isinstance(declared, list) else [declared]:
            if isinstance(name, str) and name.strip() and name not in types:
                types.append(name)
        for item in value.values():
            _collect_types(item, types)


def _same_site_scripts(soup: Any, base_url: str) -> list[str]:
    host = _site_host(base_url)
    urls = (_absolute(base_url, tag.get("src")) for tag in soup.find_all("script", src=True))
    same_site = [url for url in urls if url and _site_host(url) == host]
    return list(dict.fromkeys(same_site))[:_MAX_SCRIPT_BUNDLES]


def _base_url(soup: Any, final_url: str) -> str:
    base = soup.find("base", href=True)
    return _absolute(final_url, base["href"]) or final_url if base is not None else final_url


def _absolute(base_url: str, href: Any) -> str | None:
    """Returns an absolute http(s) URL, or None for other schemes and unusable values."""
    if not isinstance(href, str) or not href.strip():
        return None
    try:
        url = urljoin(base_url, href.strip())
    except ValueError:
        return None
    return url[:_MAX_URL_CHARS] if urlsplit(url).scheme in {"http", "https"} else None


def _site_host(url: str) -> str:
    host = (urlsplit(url).hostname or "").rstrip(".")
    return host.removeprefix("www.")


def _local_name(tag: Any) -> str:
    return str(tag).rpartition("}")[2]


def _number(value: str) -> float | None:
    try:
        number = float(value)
    except ValueError:
        return None
    return number if 0 <= number < 1e6 else None


def _append(values: list[str], value: str, limit: int) -> bool:
    if len(values) >= limit:
        return False
    values.append(value)
    return True
