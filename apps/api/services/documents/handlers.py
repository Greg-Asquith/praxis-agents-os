# apps/api/services/documents/handlers.py

"""Operations the document worker process runs. Imported only inside the worker."""

import posixpath
from collections.abc import Callable, Iterator
from contextlib import closing
from itertools import islice
from typing import Any

from services.documents.docx_model import read_document
from services.documents.packages import open_archive, open_package, open_workbook_view
from services.documents.pptx_model import read_presentation
from services.documents.precheck import PackageLimits
from services.documents.reading import DocumentRequestError, name
from services.documents.tables import read_delimited_table, read_saved_list
from services.documents.xlsx_model import read_sheet_table, read_workbook

type HandlerResult = tuple[dict[str, Any], bytes | None]
type Handler = Callable[[str, dict[str, Any], bytes, PackageLimits], HandlerResult]

_DESCRIBE_TEXT_CHARS = 2_000
_MEDIA_DIRECTORIES = {"pptx": "ppt/media/", "xlsx": "xl/media/", "docx": "word/media/"}
_IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
_MAX_IMAGE_BYTES = 20 * 1024 * 1024
_DELIMITERS = {"csv": ",", "tsv": "\t"}


def describe(
    document_format: str, _args: dict[str, Any], data: bytes, limits: PackageLimits
) -> HandlerResult:
    """Opens a file and returns its part count and a short text sample."""
    document = open_package(data, document_format, limits)
    count, texts = _DESCRIBERS[document_format](document)
    text = "\n".join(islice(texts, 200))[:_DESCRIBE_TEXT_CHARS]
    return {"format": document_format, "count": count, "text": text}, None


def read(
    document_format: str, args: dict[str, Any], data: bytes, limits: PackageLimits
) -> HandlerResult:
    """Returns one bounded page of a file's structure and text."""
    if document_format == "xlsx":
        with closing(open_archive(data, limits)) as archive:
            formulas = open_workbook_view(data, data_only=False)
            values = open_workbook_view(data, data_only=True)
            try:
                return read_workbook(formulas, values, archive, args), None
            finally:
                formulas.close()
                values.close()
    document = open_package(data, document_format, limits)
    if document_format == "pptx":
        return read_presentation(document, args), None
    return read_document(document, args), None


def read_table(
    document_format: str, args: dict[str, Any], data: bytes, limits: PackageLimits
) -> HandlerResult:
    """Returns rows of a workbook sheet, delimited text, or a JSON list as dictionaries."""
    if document_format in _DELIMITERS:
        return read_delimited_table(data, delimiter=_DELIMITERS[document_format], args=args), None
    if document_format == "json":
        return read_saved_list(data, args), None
    if document_format != "xlsx":
        raise DocumentRequestError("Tables can only be read from workbooks, CSV, and JSON.")
    open_archive(data, limits).close()
    formulas = open_workbook_view(data, data_only=False)
    values = open_workbook_view(data, data_only=True)
    try:
        return read_sheet_table(formulas, values, args), None
    finally:
        formulas.close()
        values.close()


def extract_image(
    document_format: str, args: dict[str, Any], data: bytes, limits: PackageLimits
) -> HandlerResult:
    """Returns the bytes of one embedded image part."""
    ref = str(args.get("image_ref", ""))
    media_type = _IMAGE_TYPES.get(posixpath.splitext(ref)[1].lower())
    if not ref.startswith(_MEDIA_DIRECTORIES[document_format]) or media_type is None:
        raise DocumentRequestError(
            f"{name(ref)!r} isn't an image in this file. Use an image reference from a read."
        )
    with closing(open_archive(data, limits)) as archive:
        try:
            info = archive.getinfo(ref)
        except KeyError:
            raise DocumentRequestError(f"The file has no image {name(ref)!r}.") from None
        if info.file_size > _MAX_IMAGE_BYTES:
            raise DocumentRequestError("The image is too large to view.")
        return {"media_type": media_type}, archive.read(info)


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

HANDLERS: dict[str, Handler] = {
    "describe": describe,
    "read": read,
    "read_table": read_table,
    "extract_image": extract_image,
}
