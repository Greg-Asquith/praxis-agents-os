# apps/api/services/documents/handlers.py

"""Operations the document worker process runs. Imported only inside the worker."""

import posixpath
from collections.abc import Callable
from contextlib import closing
from typing import Any

from services.documents.docx_edit import edit_document
from services.documents.docx_model import read_document
from services.documents.editing import split_attachments
from services.documents.packages import (
    open_archive,
    open_package,
    open_workbook_view,
    save_package,
)
from services.documents.pptx_edit import edit_presentation
from services.documents.pptx_model import read_presentation
from services.documents.precheck import PackageLimits
from services.documents.reading import MAX_IMAGE_BYTES, DocumentRequestError, name
from services.documents.tables import read_delimited_table, read_saved_list
from services.documents.xlsx_edit import edit_workbook
from services.documents.xlsx_model import read_sheet_table, read_workbook

type HandlerResult = tuple[dict[str, Any], bytes | None]
type Handler = Callable[[str, dict[str, Any], bytes, PackageLimits], HandlerResult]

_MEDIA_DIRECTORIES = {"pptx": "ppt/media/", "xlsx": "xl/media/", "docx": "word/media/"}
_IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
_DELIMITERS = {"csv": ",", "tsv": "\t"}


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
        if info.file_size > MAX_IMAGE_BYTES:
            raise DocumentRequestError("The image is too large to view.")
        return {"media_type": media_type}, archive.read(info)


def edit(
    document_format: str, args: dict[str, Any], data: bytes, limits: PackageLimits
) -> HandlerResult:
    """Applies edit operations and returns the result with the saved file.

    Image Files for the operations arrive packed after the document bytes.
    """
    source, images = split_attachments(data, args)
    if document_format == "xlsx":
        return edit_workbook(source, args, limits)
    document = open_package(source, document_format, limits)
    if document_format == "pptx":
        result = edit_presentation(document, args, images)
    else:
        result = edit_document(document, args, images)
    return result, save_package(document, limits)


HANDLERS: dict[str, Handler] = {
    "read": read,
    "read_table": read_table,
    "extract_image": extract_image,
    "edit": edit,
}
