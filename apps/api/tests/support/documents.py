"""Small dependency-free document fixtures for conversion tests."""

import io
import zipfile


def tiny_pdf(text: str | None) -> bytes:
    stream = b""
    if text is not None:
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 50 100 Td ({escaped}) Tj ET".encode()
    objects = (
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Count 1/Kids[3 0 R]>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 200]"
        b"/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
        f"<</Length {len(stream)}>>stream\n".encode() + stream + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    )
    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, body in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf.extend(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(offsets)}\n".encode())
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend(
        f"trailer\n<</Size {len(offsets)}/Root 1 0 R>>\nstartxref\n{xref_offset}\n%%EOF\n".encode()
    )
    return bytes(pdf)


def tiny_docx() -> bytes:
    rows = "".join(
        f"<w:tr><w:tc><w:p><w:r><w:t>{left}</w:t></w:r></w:p></w:tc>"
        f"<w:tc><w:p><w:r><w:t>{right}</w:t></w:r></w:p></w:tc></w:tr>"
        for left, right in (("Region", "Revenue"), ("North", "1250"))
    )
    return _package(
        overrides=(
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        ),
        target="word/document.xml",
        parts={
            "word/document.xml": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                "<w:body><w:p><w:r><w:t>Quarterly Results</w:t></w:r></w:p>"
                f"<w:tbl>{rows}</w:tbl><w:sectPr/></w:body></w:document>"
            )
        },
    )


def tiny_xlsx() -> bytes:
    overrides = (
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/worksheets/sheet2.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
    )
    return _package(
        overrides=overrides,
        target="xl/workbook.xml",
        parts={
            "xl/workbook.xml": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<sheets><sheet name="Summary" sheetId="1" r:id="rId1"/>'
                '<sheet name="Regions" sheetId="2" r:id="rId2"/></sheets></workbook>'
            ),
            "xl/_rels/workbook.xml.rels": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>'
                "</Relationships>"
            ),
            "xl/worksheets/sheet1.xml": _sheet(("Metric", "Value"), ("Revenue", "2230")),
            "xl/worksheets/sheet2.xml": _sheet(("Region", "Revenue"), ("North", "1250")),
        },
    )


def tiny_pptx() -> bytes:
    overrides = (
        '<Override PartName="/ppt/presentation.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
        '<Override PartName="/ppt/slides/slide1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
    )
    return _package(
        overrides=overrides,
        target="ppt/presentation.xml",
        parts={
            "ppt/presentation.xml": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<p:presentation xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
                'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
                '<p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst></p:presentation>'
            ),
            "ppt/_rels/presentation.xml.rels": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/>'
                "</Relationships>"
            ),
            "ppt/slides/slide1.xml": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
                'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
                "<p:cSld><p:spTree><p:nvGrpSpPr/><p:grpSpPr/><p:sp><p:nvSpPr/><p:spPr/>"
                "<p:txBody><a:bodyPr/><a:lstStyle/>"
                "<a:p><a:r><a:t>Launch Review</a:t></a:r></a:p>"
                "<a:p><a:r><a:t>Ship pilot</a:t></a:r></a:p>"
                "</p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
            ),
        },
    )


def _package(*, overrides: str, target: str, parts: dict[str, str]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            f"{overrides}</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            f'Target="{target}"/></Relationships>',
        )
        for name, content in parts.items():
            archive.writestr(name, content)
    return output.getvalue()


def _sheet(*rows: tuple[str, str]) -> str:
    xml_rows = []
    for row_number, values in enumerate(rows, 1):
        cells = "".join(
            f'<c r="{column}{row_number}" t="inlineStr"><is><t>{value}</t></is></c>'
            for column, value in zip(("A", "B"), values, strict=True)
        )
        xml_rows.append(f'<row r="{row_number}">{cells}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(xml_rows)}</sheetData></worksheet>"
    )
