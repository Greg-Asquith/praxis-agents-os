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


def report_presentation() -> bytes:
    """Builds a deck with formatted text, a table, a native chart, notes, and an image."""
    from pptx import Presentation
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.util import Inches, Pt

    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = "Quarterly review"
    body = slide.placeholders[1].text_frame
    body.text = "Revenue up"
    run = body.paragraphs[0].add_run()
    run.text = " 12%"
    run.font.bold = True
    run.font.size = Pt(20)
    table = slide.shapes.add_table(2, 1, Inches(1), Inches(4), Inches(2), Inches(1)).table
    table.cell(0, 0).text = "Region"
    table.cell(1, 0).text = "EMEA"
    chart_data = CategoryChartData()
    chart_data.categories = ["Q1", "Q2"]
    chart_data.add_series("Sales", (1.5, 2.5))
    slide.shapes.add_chart(
        XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(5), Inches(1), Inches(4), Inches(3), chart_data
    )
    slide.notes_slide.notes_text_frame.text = "Speaker note"
    slide.shapes.add_picture(io.BytesIO(PNG_PIXEL), Inches(0), Inches(0))
    presentation.slides.add_slide(presentation.slide_layouts[5]).shapes.title.text = "Next steps"
    output = io.BytesIO()
    presentation.save(output)
    return output.getvalue()


def sales_workbook(rows: int = 3) -> bytes:
    """Builds a Sales sheet with a header, numeric rows, a formula total, and sheet metadata."""
    from openpyxl import Workbook
    from openpyxl.worksheet.table import Table

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sales"
    sheet.append(["Region", "Amount"])
    for index in range(rows):
        sheet.append([f"Region {index + 1}", index + 1])
    sheet.cell(row=rows + 2, column=2, value=f"=SUM(B2:B{rows + 1})")
    sheet.merge_cells("D1:E1")
    sheet.freeze_panes = "A2"
    sheet.add_table(Table(displayName="SalesTable", ref=f"A1:B{rows + 1}"))
    workbook.create_sheet("Notes")
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def large_workbook(rows: int, columns: int = 10) -> bytes:
    """Builds a dense numeric workbook without holding it in memory."""
    from openpyxl import Workbook

    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("Data")
    sheet.append([f"Column {index}" for index in range(columns)])
    for row in range(rows):
        sheet.append([row * columns + index for index in range(columns)])
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def memo_document(body_text: str = "Plain ") -> bytes:
    """Builds a document with a heading, formatted runs, a list, a table, a header, and a comment."""
    from docx import Document

    document = Document()
    document.add_heading("Title", 1)
    paragraph = document.add_paragraph(body_text)
    paragraph.add_run("bold").bold = True
    document.add_table(rows=1, cols=1).cell(0, 0).text = "Cell"
    document.add_paragraph("Item", style="List Bullet")
    document.sections[0].header.paragraphs[0].text = "Header text"
    document.add_comment(paragraph.runs[0], text="Check this", author="Kai")
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def rich_document() -> bytes:
    """Builds a document with a hyperlink, style overrides, a table image, and header variants.

    It also has a formatting-only tracked change and an external hyperlink target.
    """
    from docx import Document
    from docx.enum.dml import MSO_THEME_COLOR
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Inches

    document = Document()
    paragraph = document.add_paragraph("Before ")
    relationship_id = document.part.relate_to(EXTERNAL_LINK, _HYPERLINK, is_external=True)
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), relationship_id)
    link_run = OxmlElement("w:r")
    link_text = OxmlElement("w:t")
    link_text.text = "link"
    link_run.append(link_text)
    hyperlink.append(link_run)
    paragraph._p.append(hyperlink)
    bold = paragraph.add_run(" bold")
    bold.bold = True
    revision = OxmlElement("w:rPrChange")
    revision.set(qn("w:id"), "1")
    revision.set(qn("w:author"), "Kai")
    revision.append(OxmlElement("w:rPr"))
    bold._r.get_or_add_rPr().append(revision)
    overrides = document.add_paragraph(style="Intense Quote")
    overrides.add_run("plain").bold = False
    overrides.add_run("accent").font.color.theme_color = MSO_THEME_COLOR.ACCENT_1
    cell = document.add_table(rows=1, cols=1).cell(0, 0)
    cell.paragraphs[0].add_run().add_picture(io.BytesIO(PNG_PIXEL))
    section = document.sections[0]
    section.different_first_page_header_footer = True
    section.first_page_header.paragraphs[0].text = "Cover header"
    section.header.add_table(1, 1, Inches(4)).cell(0, 0).text = "Header cell"
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def rich_presentation() -> bytes:
    """Builds a slide with a soft line break, a style override, a bubble chart, and deep groups."""
    from pptx import Presentation
    from pptx.chart.data import BubbleChartData
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.util import Inches

    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    paragraph = slide.shapes.add_textbox(0, 0, Inches(3), Inches(1)).text_frame.paragraphs[0]
    paragraph.add_run().text = "before"
    paragraph.add_line_break()
    after = paragraph.add_run()
    after.text = "after"
    after.font.bold = True
    upright = paragraph.add_run()
    upright.text = "!"
    upright.font.italic = False
    chart_data = BubbleChartData()
    chart_data.add_series("Deals").add_data_point(10, 20, 30)
    slide.shapes.add_chart(
        XL_CHART_TYPE.BUBBLE, Inches(1), Inches(1), Inches(4), Inches(3), chart_data
    )
    group = slide.shapes.add_group_shape()
    for _ in range(6):
        group = group.shapes.add_group_shape()
    group.shapes.add_textbox(0, 0, Inches(1), Inches(1)).text = "Deep"
    output = io.BytesIO()
    presentation.save(output)
    return output.getvalue()


EXTERNAL_LINK = "https://example.com/brief"
_HYPERLINK = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
PNG_PIXEL = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000b49444154789c6360000200000500017a5eab3f0000000049454e44ae426082"
)
