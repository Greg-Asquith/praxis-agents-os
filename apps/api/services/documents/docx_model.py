# apps/api/services/documents/docx_model.py

"""Bounded, paged reads of Word documents. Runs only inside the document worker."""

from typing import Any

from services.documents.packages import external_relationships, image_parts
from services.documents.reading import (
    ReadPage,
    color,
    compact,
    external_links,
    formatting,
    local_name,
    name,
    spans,
)

_DEFAULT_BLOCKS = 200
_MAX_BLOCKS = 1_000
_BODY_BLOCKS = frozenset({"p", "tbl", "sdt"})
_REVISIONS = frozenset(
    {
        "ins",
        "del",
        "moveFrom",
        "moveTo",
        "rPrChange",
        "pPrChange",
        "sectPrChange",
        "tblPrChange",
        "trPrChange",
        "tcPrChange",
        "numberingChange",
    }
)
_STORY_VARIANTS = (
    ("primary", "header", "footer"),
    ("first_page", "first_page_header", "first_page_footer"),
    ("even_page", "even_page_header", "even_page_footer"),
)


def read_document(document: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Returns body blocks in order. The first page, without `start`, also has styles and stories.

    Paragraph and table indexes count only paragraphs and tables directly in the
    body, matching the targets that edit operations use.
    """
    page = ReadPage(args)
    start = args.get("start")
    limit = min(int(args.get("limit") or _DEFAULT_BLOCKS), _MAX_BLOCKS)
    body = document.element.body
    elements = [
        element for element in body.iterchildren() if local_name(element.tag) in _BODY_BLOCKS
    ]
    result: dict[str, Any] = {
        "block_count": len(elements),
        "has_tracked_changes": has_revisions(document),
    }
    if start is None:
        result.update(_document_parts(document, page))
    blocks = []
    counts = {"p": 0, "tbl": 0}
    for position, element in enumerate(elements):
        tag = local_name(element.tag)
        index = counts.get(tag, 0)
        if tag in counts:
            counts[tag] += 1
        if position < int(start or 0):
            continue
        if len(blocks) >= limit:
            result["next_start"] = position
            break
        item = read_block(document, element, tag, index, page)
        too_large = (
            f"Block {position} is larger than one read page. Pass start {position + 1} to skip it."
        )
        if not page.add(item, first=not blocks, too_large=too_large):
            result["next_start"] = position
            break
        blocks.append(item)
    result["blocks"] = blocks
    return result


def has_revisions(document: Any) -> bool:
    """Checks the body, headers, footers, and notes for any tracked-change element."""
    for part in document.part.package.iter_parts():
        element = getattr(part, "_element", None)
        if element is not None and any(
            local_name(node.tag) in _REVISIONS for node in element.iter()
        ):
            return True
    return False


def _document_parts(document: Any, page: ReadPage) -> dict[str, Any]:
    from docx.enum.style import WD_STYLE_TYPE

    parts: dict[str, Any] = {"paragraph_styles": [], "headers": [], "footers": [], "comments": []}
    for style in document.styles:
        if style.type == WD_STYLE_TYPE.PARAGRAPH:
            if not page.fits(name(style.name)):
                parts["paragraph_styles_truncated"] = True
                break
            parts["paragraph_styles"].append(name(style.name))
    for key, item in _stories(document, page):
        if not page.fits(item):
            parts[f"{key}_truncated"] = True
            continue
        parts[key].append(item)
    for comment in document.comments:
        item = read_comment(comment, page)
        if not page.fits(item):
            parts["comments_truncated"] = True
            break
        parts["comments"].append(item)
    parts.update(external_links(external_relationships(document), page))
    return compact(parts)


def _stories(document: Any, page: ReadPage) -> Any:
    """Yields each section's own headers and footers, including first and even page variants."""
    even_pages = document.settings.odd_and_even_pages_header_footer
    for number, section in enumerate(document.sections, start=1):
        for variant, header, footer in _STORY_VARIANTS:
            if variant == "first_page" and not section.different_first_page_header_footer:
                continue
            if variant == "even_page" and not even_pages:
                continue
            for key, attribute in (("headers", header), ("footers", footer)):
                story = getattr(section, attribute)
                if story.is_linked_to_previous:
                    continue
                item = read_story(story, number, variant, page)
                if "text" in item or "images" in item:
                    yield key, item


def read_story(story: Any, section: int, variant: str, page: ReadPage) -> dict[str, Any]:
    """Returns a section's header or footer text and images as reads show them."""
    return {
        "section": section,
        "variant": variant,
        **compact(
            {
                "text": page.text(_story_text(story)),
                "images": image_parts(story._element, story.part),
            }
        ),
    }


def read_comment(comment: Any, page: ReadPage) -> dict[str, Any]:
    """Returns a comment's id, author, and text as reads show them."""
    return compact(
        {
            "comment_id": comment.comment_id,
            "author": name(comment.author),
            "text": page.text(comment.text),
        }
    )


def _story_text(story: Any) -> str:
    from docx.table import Table

    lines = []
    for item in story.iter_inner_content():
        if isinstance(item, Table):
            lines.extend("\t".join(cell.text for cell in row.cells) for row in item.rows)
        else:
            lines.append(item.text)
    return "\n".join(lines).strip("\n")


def read_block(document: Any, element: Any, tag: str, index: int, page: ReadPage) -> dict[str, Any]:
    """Returns one body paragraph, table, or content control as reads show it."""
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    if tag == "p":
        return _paragraph(Paragraph(element, document.part), document, index, page)
    images = image_parts(element, document.part)
    if tag == "tbl":
        table = Table(element, document.part)
        return compact(
            {
                "type": "table",
                "index": index,
                "style": name(table.style.name) if table.style is not None else None,
                "rows": [[page.text(cell.text) for cell in row.cells] for row in table.rows],
                "images": images,
            }
        )
    # Content controls hold paragraphs that edit operations can't target yet.
    text = "\n".join(
        "".join(node.text or "" for node in paragraph.iter() if local_name(node.tag) == "t")
        for paragraph in element.iter()
        if local_name(paragraph.tag) == "p"
    )
    return compact({"type": "content_control", "text": page.text(text), "images": images})


def _paragraph(paragraph: Any, document: Any, index: int, page: ReadPage) -> dict[str, Any]:
    text, ranges = spans((run.text, _run_style(run)) for run in _runs(paragraph))
    return {
        "type": "paragraph",
        "index": index,
        "text": page.text(text),
        **compact(
            {
                "style": name(paragraph.style.name) if paragraph.style is not None else None,
                "list_level": _list_level(paragraph),
                "spans": ranges,
                "images": image_parts(paragraph._p, document.part),
            }
        ),
    }


def _runs(paragraph: Any) -> Any:
    """Yields runs in document order, including those inside hyperlinks."""
    from docx.text.hyperlink import Hyperlink

    for item in paragraph.iter_inner_content():
        if isinstance(item, Hyperlink):
            yield from item.runs
        else:
            yield item


def _list_level(paragraph: Any) -> int | None:
    """Returns the paragraph's own list level; numbering from its style isn't resolved."""
    properties = paragraph._p.pPr
    if properties is None or properties.numPr is None:
        return None
    level = properties.numPr.ilvl
    return level.val if level is not None else 0


def _run_style(run: Any) -> dict[str, Any]:
    font = run.font
    return formatting(
        {
            "bold": run.bold,
            "italic": run.italic,
            "underline": bool(run.underline) if run.underline is not None else None,
            "size": font.size.pt if font.size is not None else None,
            "font": name(font.name) if font.name else None,
            "color": color(font.color),
            "style": _character_style(run),
        }
    )


def _character_style(run: Any) -> str | None:
    style = run.style
    if style is None or style.name == "Default Paragraph Font":
        return None
    return name(style.name)
