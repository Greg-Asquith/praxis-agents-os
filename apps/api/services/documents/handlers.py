# apps/api/services/documents/handlers.py

"""Operations the document worker process runs. Imported only inside the worker."""

from collections.abc import Callable, Iterator
from itertools import islice
from typing import Any

from services.documents.packages import open_package
from services.documents.precheck import PackageLimits

type HandlerResult = tuple[dict[str, Any], bytes | None]
type Handler = Callable[[str, dict[str, Any], bytes, PackageLimits], HandlerResult]

_DESCRIBE_TEXT_CHARS = 2_000


def describe(
    document_format: str, _args: dict[str, Any], data: bytes, limits: PackageLimits
) -> HandlerResult:
    """Opens a file and returns its part count and a short text sample."""
    document = open_package(data, document_format, limits)
    count, texts = _DESCRIBERS[document_format](document)
    text = "\n".join(islice(texts, 200))[:_DESCRIBE_TEXT_CHARS]
    return {"format": document_format, "count": count, "text": text}, None


def _describe_presentation(presentation: Any) -> tuple[int, Iterator[str]]:
    texts = (
        shape.text_frame.text
        for slide in presentation.slides
        for shape in slide.shapes
        if shape.has_text_frame
    )
    return len(presentation.slides), texts


def _describe_workbook(workbook: Any) -> tuple[int, Iterator[str]]:
    texts = (
        str(value)
        for row in workbook.worksheets[0].iter_rows(max_row=50, values_only=True)
        for value in row
        if value is not None
    )
    return len(workbook.worksheets), texts


def _describe_document(document: Any) -> tuple[int, Iterator[str]]:
    return len(document.paragraphs), (paragraph.text for paragraph in document.paragraphs)


_DESCRIBERS = {
    "pptx": _describe_presentation,
    "xlsx": _describe_workbook,
    "docx": _describe_document,
}

HANDLERS: dict[str, Handler] = {"describe": describe}
