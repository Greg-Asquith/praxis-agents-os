# apps/api/services/web/read_page.py

"""Turns a fetched body into the text an agent reads."""

from __future__ import annotations

import codecs
from dataclasses import dataclass
from typing import Literal

from core.settings import settings
from services.web.domain import FetchedResponse
from services.web.utils import content_kind, page_file_name
from utils.document_markdown import convert_document_to_markdown_result, render_web_page

OutputFormat = Literal["markdown", "text", "html"]
PagePart = Literal["main", "body", "head", "full"]
DropKind = Literal["scripts", "styles", "svg", "comments", "data_uris"]
ReturnedFormat = Literal["markdown", "text", "html", "unsupported"]


@dataclass(frozen=True)
class PageContent:
    """The content of one fetched body in the format it was returned in."""

    format: ReturnedFormat
    content: str | None
    title: str | None = None


async def read_page(
    response: FetchedResponse,
    *,
    output_format: OutputFormat,
    part: PagePart,
    drop: tuple[DropKind, ...],
) -> PageContent:
    """Returns an HTML page in the requested part and format, text verbatim, and documents as
    Markdown. Images and other binary bodies return no content.

    Conversion runs in the document worker.

    Raises:
        DocumentConversionError: If the page or document can't be converted.
    """
    kind = content_kind(response)
    if kind == "html":
        page = await render_web_page(
            response.body,
            output_format=output_format,
            part=part,
            drop=drop,
            max_bytes=settings.WEB_FETCH_MAX_BYTES,
        )
        return PageContent(format=output_format, content=page.content, title=page.title)
    if kind == "text":
        return PageContent(
            format="text", content=response.body.decode(_charset(response), "replace")
        )
    if kind == "document":
        converted = await convert_document_to_markdown_result(
            response.body,
            content_type=response.content_type.partition(";")[0],
            filename=page_file_name(response.final_url),
            max_bytes=settings.WEB_FETCH_MAX_BYTES,
        )
        return PageContent(format="markdown", content=converted.markdown)
    return PageContent(format="unsupported", content=None)


def _charset(response: FetchedResponse) -> str:
    for parameter in response.content_type.split(";")[1:]:
        name, _, value = parameter.partition("=")
        if name.strip().lower() == "charset":
            try:
                return codecs.lookup(value.strip().strip("\"'")).name
            except LookupError:
                break
    return "utf-8"
