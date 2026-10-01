# apps/api/services/documents/packages.py

"""Open, save, and relationship helpers per Office format. Run only inside the document worker."""

import io
import zipfile
from collections.abc import Iterator
from typing import Any

from services.documents.precheck import PackageLimits, PackageRejectedError, precheck_package

_BLIP_NAMESPACES = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


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


def external_relationships(document: Any) -> Iterator[tuple[str, str]]:
    """Yields the type and target of every external relationship in a deck or Word document."""
    for relationship in document.part.package.iter_rels():
        if relationship.is_external:
            yield relationship.reltype, relationship.target_ref


def image_parts(element: Any, part: Any) -> list[str]:
    """Returns part names of images embedded in an element, resolved through its part."""
    from lxml import etree

    refs = []
    # Word content controls are plain lxml elements, so the namespaces are passed explicitly.
    for rel_id in etree.XPath(".//a:blip/@r:embed", namespaces=_BLIP_NAMESPACES)(element):
        relationship = part.rels.get(rel_id)
        if relationship is None or relationship.is_external:
            continue
        ref = str(relationship.target_part.partname).lstrip("/")
        if ref not in refs:
            refs.append(ref)
    return refs
