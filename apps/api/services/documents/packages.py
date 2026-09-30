# apps/api/services/documents/packages.py

"""Open and save helpers per Office format. Run only inside the document worker."""

import io
import zipfile
from typing import Any

from services.documents.precheck import PackageLimits, PackageRejectedError, precheck_package


def require_safe_parsers() -> None:
    """Fails closed unless openpyxl streams worksheets through defusedxml.

    openpyxl parses the other workbook parts with lxml and `resolve_entities=False`.
    """
    import openpyxl

    if openpyxl.DEFUSEDXML is not True:
        raise RuntimeError("openpyxl must use defusedxml in the document worker")


def open_package(data: bytes, document_format: str, limits: PackageLimits) -> Any:
    """Prechecks the archive, then opens it with the library for its format."""
    precheck_package(data, limits)
    stream = io.BytesIO(data)
    if document_format == "pptx":
        from pptx import Presentation

        return Presentation(stream)
    if document_format == "xlsx":
        from openpyxl import load_workbook

        return load_workbook(stream, keep_vba=False)
    if document_format == "docx":
        from docx import Document

        return Document(stream)
    raise PackageRejectedError("The file format isn't supported.")


def open_workbook_view(data: bytes, *, data_only: bool) -> Any:
    """Opens a workbook for streaming reads, with formulas or with cached values.

    Call only with bytes that `open_archive` has prechecked. Read-only worksheets
    parse rows on demand, so memory follows the rows read, not the file size.
    """
    from openpyxl import load_workbook

    return load_workbook(io.BytesIO(data), read_only=True, data_only=data_only, keep_links=False)


def open_archive(data: bytes, limits: PackageLimits) -> zipfile.ZipFile:
    """Prechecks a package and opens it as an archive for part-level reads."""
    precheck_package(data, limits)
    return zipfile.ZipFile(io.BytesIO(data))


def save_package(document: Any, limits: PackageLimits) -> bytes:
    """Saves an opened document and applies the same precheck to the output."""
    output = io.BytesIO()
    document.save(output)
    data = output.getvalue()
    precheck_package(data, limits)
    return data
