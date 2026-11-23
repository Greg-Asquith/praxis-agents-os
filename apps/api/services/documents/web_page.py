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

# Never page content, so Markdown and text always leave them out.
_NON_CONTENT_TAGS = ["script", "style", "noscript", "template", "svg"]
_TITLE_MAX_CHARS = 500


def web_page(_format: str, args: dict[str, Any], data: bytes, _limits: Any) -> HandlerResult:
    """Returns the requested part and format as the payload, with the page title."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(data, "html.parser")
    title = _title(soup)
    output_format, part = args["format"], args["part"]
    if output_format == "html":
        root = _html_part(soup, part)
        _drop(root, frozenset(args["drop"]))
        content = str(root) if root is not None else ""
    elif part in {"head", "full"}:
        raise DocumentRequestError(f"part={part!r} needs format='html'.")
    else:
        root = main_page_root(soup) if part == "main" else (soup.body or soup)
        for tag in root.find_all(_NON_CONTENT_TAGS):
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


def _title(soup: Any) -> str | None:
    tag = soup.find("title")
    text = " ".join(tag.get_text().split()) if tag is not None else ""
    return text[:_TITLE_MAX_CHARS] or None


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
