# apps/api/services/documents/web_page.py

"""One part of a fetched HTML page as Markdown, text, or HTML. Imported only inside the worker."""

from typing import Any

from services.documents.markdown import (
    bound_markdown,
    html_to_markdown,
    main_page_root,
    strip_markdown_noise,
)
from services.documents.reading import DocumentRequestError

type HandlerResult = tuple[dict[str, Any], bytes | None]

# Never page content, so Markdown, text, and word counts always leave them out.
NON_CONTENT_TAGS = ["script", "style", "noscript", "template", "svg"]
_TITLE_MAX_CHARS = 500


def web_page(_format: str, args: dict[str, Any], data: bytes, _limits: Any) -> HandlerResult:
    """Returns the requested part and format as the payload, with the page title."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(data, "html.parser")
    title = page_title(soup)
    output_format, part = args["format"], args["part"]
    if output_format == "html":
        root = _html_part(soup, part)
        _drop(root, frozenset(args["drop"]))
        content = str(root) if root is not None else ""
    elif part in {"head", "full"}:
        raise DocumentRequestError(f"part={part!r} needs format='html'.")
    else:
        root = main_page_root(soup) if part == "main" else (soup.body or soup)
        for tag in root.find_all(NON_CONTENT_TAGS):
            if not tag.decomposed:
                tag.decompose()
        if output_format == "text":
            content = root.get_text("\n", strip=True)
        else:
            content = html_to_markdown(str(root))
            if part == "main":
                content = strip_markdown_noise(content)
    content, truncated = bound_markdown(content, max_bytes=args["max_bytes"])
    return {"title": title, "truncated": truncated}, content.encode("utf-8")


def page_facts(_format: str, _args: dict[str, Any], data: bytes, _limits: Any) -> HandlerResult:
    """Returns the title, meta description, canonical, meta robots, and H1 count."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(data, "html.parser")
    facts = {
        "title": page_title(soup),
        "description": meta_content(soup, "description"),
        "canonical": bounded_text(link_href(soup, "canonical")),
        "robots": meta_content(soup, "robots"),
        "h1_count": len(soup.find_all("h1")),
    }
    return facts, None


def meta_content(soup: Any, name: str) -> str | None:
    """Returns the bounded content of the first `<meta name>` tag, matched case-insensitively."""
    for tag in soup.find_all("meta", attrs={"name": True}):
        if str(tag["name"]).strip().lower() == name:
            return bounded_text(tag.get("content"))
    return None


def link_href(soup: Any, rel: str) -> str | None:
    """Returns the `href` of the first `<link>` whose `rel` list includes `rel`."""
    return next(
        (
            link.get("href")
            for link in soup.find_all("link", href=True)
            if rel in [value.lower() for value in link.get("rel") or ()]
        ),
        None,
    )


def bounded_text(value: Any, max_chars: int = _TITLE_MAX_CHARS) -> str | None:
    """Returns a string with whitespace collapsed and cut at `max_chars`, or None when empty."""
    text = " ".join(value.split()) if isinstance(value, str) else ""
    return text[:max_chars] or None


def page_title(soup: Any) -> str | None:
    """Returns the bounded `<title>` text."""
    tag = soup.find("title")
    return bounded_text(tag.get_text()) if tag is not None else None


def _html_part(soup: Any, part: str) -> Any:
    if part == "main":
        return main_page_root(soup)
    if part == "body":
        return soup.body or soup
    if part == "head":
        return soup.head
    return soup


def _drop(root: Any, drop: frozenset[str]) -> None:
    from bs4 import Comment

    if root is None:
        return
    names = [
        name
        for flag, name in (("scripts", "script"), ("styles", "style"), ("svg", "svg"))
        if flag in drop
    ]
    for tag in root.find_all(names) if names else ():
        if not tag.decomposed:
            tag.decompose()
    if "comments" in drop:
        for comment in root.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()
    if "styles" in drop or "data_uris" in drop:
        for tag in [root, *root.find_all(True)]:
            _drop_attributes(tag, drop)


def _drop_attributes(tag: Any, drop: frozenset[str]) -> None:
    if "styles" in drop:
        tag.attrs.pop("style", None)
    if "data_uris" in drop:
        for name, value in tag.attrs.items():
            if isinstance(value, str) and value.lstrip().lower().startswith("data:"):
                # Keeps the media type so an audit still sees what was inlined.
                tag.attrs[name] = value.partition(",")[0] + ",[removed]"
