"""Real and hostile Office files built in the test process."""

import io
import zipfile

MARKER = "Fixture text"
_MAIN_TEXT_PARTS = {
    "pptx": "ppt/slides/slide1.xml",
    "xlsx": "xl/worksheets/sheet1.xml",
    "docx": "word/document.xml",
}
_LAUGHS = "".join(f'<!ENTITY lol{level} "{f"&lol{level - 1};" * 10}">' for level in range(1, 10))


def office_file(document_format: str) -> bytes:
    """Builds a one-page file whose main text part contains MARKER."""
    output = io.BytesIO()
    if document_format == "pptx":
        from pptx import Presentation

        presentation = Presentation()
        slide = presentation.slides.add_slide(presentation.slide_layouts[0])
        slide.shapes.title.text = MARKER
        presentation.save(output)
    elif document_format == "xlsx":
        from openpyxl import Workbook

        workbook = Workbook()
        workbook.active["A1"] = MARKER
        workbook.save(output)
    else:
        from docx import Document

        document = Document()
        document.add_paragraph(MARKER)
        document.save(output)
    return output.getvalue()


def with_entity_expansion(document_format: str) -> bytes:
    """Replaces MARKER with a billion-laughs entity reference."""
    doctype = f'<!DOCTYPE x [<!ENTITY lol0 "lol">{_LAUGHS}]>'
    return _with_entity(document_format, doctype, "&lol9;")


def with_external_entity(document_format: str, target: str) -> bytes:
    """Replaces MARKER with a reference to an external file entity."""
    doctype = f'<!DOCTYPE x [<!ENTITY ext SYSTEM "file://{target}">]>'
    return _with_entity(document_format, doctype, "&ext;")


def _with_entity(document_format: str, doctype: str, reference: str) -> bytes:
    part = _MAIN_TEXT_PARTS[document_format]

    def rewrite(name: str, content: bytes) -> bytes:
        if name != part:
            return content
        text = content.decode()
        assert MARKER in text, f"{part} no longer holds the fixture text"
        text = text.replace(MARKER, reference)
        declaration_end = text.index("?>") + 2 if text.startswith("<?xml") else 0
        return (text[:declaration_end] + doctype + text[declaration_end:]).encode()

    return rewrite_package(office_file(document_format), rewrite)


def rewrite_package(data: bytes, rewrite, extra: dict[str, bytes] | None = None) -> bytes:
    """Copies a package through rewrite(name, content) and appends extra parts."""
    output = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(data)) as source,
        zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        for entry in source.infolist():
            target.writestr(entry.filename, rewrite(entry.filename, source.read(entry)))
        for name, content in (extra or {}).items():
            target.writestr(name, content)
    return output.getvalue()
