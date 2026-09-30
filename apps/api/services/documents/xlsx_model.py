# apps/api/services/documents/xlsx_model.py

"""Streaming, paged reads of workbooks. Runs only inside the document worker.

A full openpyxl load needs about 100 times the file size in memory, so reads
open read-only views and stop once a page is full. Read-only worksheets don't
load merged ranges, tables, freeze panes, or drawings, so that metadata comes
from the sheet and relationship parts, parsed with defusedxml.
"""

import posixpath
import re
import zipfile
from collections.abc import Iterator
from contextlib import closing
from typing import Any

from services.documents.reading import (
    DEFAULT_TABLE_ROWS,
    MAX_TABLE_ROWS,
    DocumentRequestError,
    ReadPage,
    compact,
    external_links,
    name,
)

_CHUNK_BYTES = 64 * 1024
_TAG_OVERLAP_BYTES = 256
_MAX_OUTLINE_BYTES = 4 * 1024 * 1024
_MAX_LISTED = 200
_MAX_ROWS = 1_048_576
_MAX_COLUMNS = 16_384
_DATA_START = re.compile(rb"<(?:[A-Za-z_][\w.\-]*:)?sheetData\b")
_DATA_END = re.compile(rb"</(?:[A-Za-z_][\w.\-]*:)?sheetData\s*>")
_R_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_CHART_REL = "/chart"
_IMAGE_REL = "/image"
_TABLE_REL = "/table"
_DRAWING_REL = "/drawing"


def read_workbook(
    formulas: Any, values: Any, archive: zipfile.ZipFile, args: dict[str, Any]
) -> dict[str, Any]:
    """Returns one page of the chosen sheet's cells.

    The first page, without a cursor, also lists the sheets, the chosen sheet's
    outline, and external links.
    """
    page = ReadPage(args)
    sheet_name = _sheet_name(formulas, args.get("sheet"))
    formula_sheet, value_sheet = formulas[sheet_name], values[sheet_name]
    min_col, min_row, max_col, max_row = _bounds(formula_sheet, args.get("range"))
    result: dict[str, Any] = {"sheet": sheet_name}
    if args.get("cursor") is None:
        result.update(_workbook_metadata(formulas, formula_sheet, archive, page))
    start = max(int(args.get("cursor") or min_row), min_row)
    result["rows"] = []
    rows = zip(
        _rows(formula_sheet, start, min_col, max_row, max_col),
        _rows(value_sheet, start, min_col, max_row, max_col),
        strict=True,
    )
    for number, (formula_row, value_row) in enumerate(rows, start=start):
        cells = [
            cell
            for column, (formula_cell, value_cell) in enumerate(
                zip(formula_row, value_row, strict=True), start=min_col
            )
            if (cell := _cell(formula_cell, value_cell, column, number, page)) is not None
        ]
        if not cells:
            continue
        item = {"row": number, "cells": cells}
        too_large = (
            f"Row {number} is larger than one read page. Narrow range to fewer columns, "
            f"or pass cursor {number + 1} to skip it."
        )
        if not page.add(item, first=not result["rows"], too_large=too_large):
            result["next_cursor"] = number
            break
        result["rows"].append(item)
    return result


def read_sheet_table(formulas: Any, values: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Returns rows of a sheet as dictionaries keyed by its first non-empty row.

    Formulas without a saved value come back as None and are listed by cell.
    """
    page = ReadPage(args)
    sheet_name = _sheet_name(values, args.get("sheet"))
    min_col, min_row, max_col, max_row = _bounds(formulas[sheet_name], args.get("range"))
    offset = int(args.get("offset") or 0)
    limit = min(int(args.get("limit") or DEFAULT_TABLE_ROWS), MAX_TABLE_ROWS)
    columns: list[str] | None = None
    rows: list[dict[str, Any]] = []
    uncalculated: list[str] = []
    total = 0
    next_offset = None
    source = zip(
        _rows(formulas[sheet_name], min_row, min_col, max_row, max_col),
        _rows(values[sheet_name], min_row, min_col, max_row, max_col),
        strict=True,
    )
    for number, (formula_row, value_row) in enumerate(source, start=min_row):
        row_values = [
            _table_value(formula, value)
            for formula, value in zip(formula_row, value_row, strict=True)
        ]
        if all(value is None and not formula for value, formula in row_values):
            continue
        if columns is None:
            columns = column_names(_trim_trailing_empty(value for value, _ in row_values))
            page.reserve(
                columns, too_large="The sheet has more columns than one read page can hold."
            )
            continue
        index = total
        total += 1
        if index < offset or next_offset is not None or len(rows) >= limit:
            continue
        extra = _trim_trailing_empty(value for value, _ in row_values[len(columns) :])
        if extra:
            columns = column_names([*columns, *([None] * len(extra))])
        row = {
            column: page.value(value)
            for column, (value, _) in zip(columns, row_values, strict=False)
        }
        too_large = f"Row {index} is larger than one read page. Pass offset {index + 1} to skip it."
        if not page.add(row, first=not rows, too_large=too_large):
            next_offset = index
            continue
        rows.append(row)
        uncalculated.extend(
            _ref(min_col + position, number)
            for position, (value, formula) in enumerate(row_values)
            if formula and value is None
        )
    return _table_result(sheet_name, columns or [], rows, total, offset, next_offset, uncalculated)


def _table_value(formula_cell: Any, value_cell: Any) -> tuple[Any, bool]:
    """Returns a cell's saved value and whether it holds a formula."""
    is_formula = getattr(formula_cell, "data_type", None) == "f"
    value = getattr(value_cell, "value", None)
    return value, is_formula


def _table_result(
    sheet_name: str,
    columns: list[str],
    rows: list[dict[str, Any]],
    total: int,
    offset: int,
    next_offset: int | None,
    uncalculated: list[str],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "sheet": sheet_name,
        "columns": columns,
        "rows": rows,
        "total_rows": total,
    }
    if uncalculated:
        result["uncalculated_cells"] = uncalculated[:_MAX_LISTED]
        result["uncalculated_count"] = len(uncalculated)
    end = offset + len(rows)
    if next_offset is None and end < total:
        next_offset = end
    if next_offset is not None:
        result["next_offset"] = next_offset
    return result


def _workbook_metadata(
    workbook: Any, sheet: Any, archive: zipfile.ZipFile, page: ReadPage
) -> dict[str, Any]:
    metadata: dict[str, Any] = {"sheets": []}
    for item in workbook.worksheets + workbook.chartsheets:
        entry = compact(
            {
                "name": name(item.title),
                "kind": "worksheet" if getattr(item, "_worksheet_path", None) else "chart_sheet",
                "hidden": getattr(item, "sheet_state", "visible") != "visible",
            }
        )
        if not page.fits(entry):
            metadata["sheets_truncated"] = True
            break
        metadata["sheets"].append(entry)
    outline = _sheet_outline(sheet, archive)
    if page.fits(outline):
        metadata["outline"] = outline
    else:
        metadata["outline_truncated"] = True
    metadata.update(external_links(_external_relationships(archive), page))
    return metadata


def column_names(values: Any) -> list[str]:
    """Returns unique, capped column names for a header row."""
    names: list[str] = []
    for index, value in enumerate(values, start=1):
        base = name(value).strip() or f"column_{index}"
        candidate, suffix = base, 2
        while candidate in names:
            candidate, suffix = f"{base}_{suffix}", suffix + 1
        names.append(candidate)
    return names


def _trim_trailing_empty(values: Any) -> tuple[Any, ...]:
    values = tuple(values)
    end = len(values)
    while end and values[end - 1] is None:
        end -= 1
    return values[:end]


def _sheet_name(workbook: Any, requested: str | None) -> str:
    if requested is not None:
        if requested not in workbook.sheetnames:
            raise DocumentRequestError(
                f"The workbook has no sheet named {name(requested)!r}. "
                f"Its sheets are: {', '.join(name(sheet) for sheet in workbook.sheetnames[:50])}."
            )
        if requested not in [sheet.title for sheet in workbook.worksheets]:
            raise DocumentRequestError(f"{name(requested)!r} is a chart sheet and has no cells.")
        return requested
    if not workbook.worksheets:
        raise DocumentRequestError("The workbook has no worksheets.")
    return workbook.worksheets[0].title


def _bounds(sheet: Any, cell_range: str | None) -> tuple[int, int, int | None, int | None]:
    if not cell_range:
        return sheet.min_column or 1, sheet.min_row or 1, sheet.max_column, sheet.max_row
    from openpyxl.utils.cell import range_boundaries

    try:
        bounds = range_boundaries(cell_range.replace("$", ""))
    except (TypeError, ValueError):
        bounds = None
    if bounds is None or not _valid_bounds(*bounds):
        raise DocumentRequestError(
            f"{name(cell_range)!r} isn't a cell range. Use A1 notation, such as A1:D20."
        )
    min_col, min_row, max_col, max_row = bounds
    return min_col or 1, min_row or 1, max_col, max_row


def _valid_bounds(
    min_col: int | None, min_row: int | None, max_col: int | None, max_row: int | None
) -> bool:
    """Checks that a range is ordered and inside the sheet. Whole rows and columns omit a pair."""
    for low, high, limit in ((min_col, max_col, _MAX_COLUMNS), (min_row, max_row, _MAX_ROWS)):
        if (low is None) != (high is None):
            return False
        if low is not None and not 1 <= low <= high <= limit:
            return False
    return min_col is not None or min_row is not None


def _rows(
    sheet: Any, min_row: int, min_col: int, max_row: int | None, max_col: int | None
) -> Iterator[tuple[Any, ...]]:
    with closing(
        sheet.iter_rows(min_row=min_row, max_row=max_row, min_col=min_col, max_col=max_col)
    ) as rows:
        yield from rows


def _ref(column: int, row: int) -> str:
    from openpyxl.utils import get_column_letter

    return f"{get_column_letter(column)}{row}"


def _cell(
    formula_cell: Any, value_cell: Any, column: int, row: int, page: ReadPage
) -> dict[str, Any] | None:
    formula = None
    if getattr(formula_cell, "data_type", None) == "f":
        formula = str(getattr(formula_cell.value, "text", formula_cell.value))
    value = getattr(value_cell, "value", None)
    if value is None and formula is None:
        return None
    item: dict[str, Any] = {"ref": _ref(column, row), "value": page.value(value)}
    if formula is not None:
        item["formula"] = page.text(formula)
        item["calculated"] = value is not None
    number_format = getattr(formula_cell, "number_format", None)
    if number_format and number_format != "General":
        item["number_format"] = name(number_format)
    return item


def _sheet_outline(sheet: Any, archive: zipfile.ZipFile) -> dict[str, Any]:
    part = getattr(sheet, "_worksheet_path", None)
    outline: dict[str, Any] = {
        "name": name(sheet.title),
        "kind": "worksheet" if part is not None else "chart_sheet",
        "hidden": getattr(sheet, "sheet_state", "visible") != "visible",
    }
    if part is None:
        return compact(outline)
    root = _parse(_without_cell_data(archive, part))
    if root is None:
        outline["metadata_incomplete"] = True
        return compact(outline)
    relationships = _relationships(archive, part)
    merged = [name(cell.get("ref", "")) for cell in _find_all(root, "mergeCell")]
    drawing = _drawing_contents(archive, root, relationships)
    outline.update(
        {
            "dimensions": _attribute(root, "dimension", "ref"),
            "freeze_panes": _freeze_panes(root),
            "merged_ranges": merged[:_MAX_LISTED],
            "merged_range_count": len(merged) if len(merged) > _MAX_LISTED else None,
            "tables": _tables(archive, root, relationships)[:_MAX_LISTED],
            "has_charts": drawing["charts"],
            "images": drawing["images"][:_MAX_LISTED],
        }
    )
    return compact(outline)


def _without_cell_data(archive: zipfile.ZipFile, part: str) -> bytes | None:
    """Returns a sheet part with its cell data cut out, streaming past the rows.

    Sheet metadata sits before and after `sheetData`, which holds nearly all of
    the part, so this stays small without parsing every cell.
    """
    kept = bytearray()
    buffer = b""
    state = "head"
    try:
        stream = archive.open(part)
    except KeyError:
        return None
    with stream:
        while True:
            chunk = stream.read(_CHUNK_BYTES)
            buffer += chunk
            if state == "head":
                buffer, state = _scan_head(buffer, kept, final=not chunk)
            if state == "data":
                match = _DATA_END.search(buffer)
                if match is None:
                    buffer = buffer[-_TAG_OVERLAP_BYTES:]
                else:
                    buffer, state = buffer[match.end() :], "tail"
            if state == "tail":
                kept += buffer
                buffer = b""
            if len(kept) + len(buffer) > _MAX_OUTLINE_BYTES or state == "invalid":
                return None
            if not chunk:
                break
    return bytes(kept + buffer) if state in {"head", "tail"} else None


def _scan_head(buffer: bytes, kept: bytearray, *, final: bool) -> tuple[bytes, str]:
    match = _DATA_START.search(buffer)
    if match is None:
        split = len(buffer) if final else max(len(buffer) - _TAG_OVERLAP_BYTES, 0)
        kept += buffer[:split]
        return buffer[split:], "head"
    close = buffer.find(b">", match.end())
    if close < 0:
        return (buffer, "invalid") if final else (buffer, "head")
    kept += buffer[: match.start()]
    state = "tail" if buffer[close - 1 : close] == b"/" else "data"
    return buffer[close + 1 :], state


def _parse(content: bytes | None) -> Any:
    if content is None:
        return None
    from xml.etree.ElementTree import ParseError

    from defusedxml import DefusedXmlException
    from defusedxml.ElementTree import fromstring

    try:
        return fromstring(content, forbid_dtd=True)
    except (ParseError, DefusedXmlException):
        return None


def _read_part(archive: zipfile.ZipFile, part: str) -> Any:
    try:
        info = archive.getinfo(part)
    except KeyError:
        return None
    if info.file_size > _MAX_OUTLINE_BYTES:
        return None
    return _parse(archive.read(info))


def _local(tag: Any) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _find_all(root: Any, local_name: str) -> list[Any]:
    return [element for element in root.iter() if _local(element.tag) == local_name]


def _attribute(root: Any, local_name: str, attribute: str) -> str | None:
    for element in _find_all(root, local_name):
        return name(element.get(attribute)) or None
    return None


def _freeze_panes(root: Any) -> str | None:
    for pane in _find_all(root, "pane"):
        if pane.get("state") in {"frozen", "frozenSplit"}:
            return name(pane.get("topLeftCell")) or None
    return None


def _relationships(archive: zipfile.ZipFile, part: str) -> dict[str, tuple[str, str]]:
    """Returns internal relationships of a part as id to (type, target part)."""
    directory, filename = posixpath.split(part)
    root = _read_part(archive, posixpath.join(directory, "_rels", f"{filename}.rels"))
    if root is None:
        return {}
    relationships = {}
    for element in _find_all(root, "Relationship"):
        target = element.get("Target", "")
        if element.get("TargetMode") == "External" or not target:
            continue
        resolved = (
            target.lstrip("/")
            if target.startswith("/")
            else posixpath.normpath(posixpath.join(directory, target))
        )
        relationships[element.get("Id", "")] = (element.get("Type", ""), resolved)
    return relationships


def _external_relationships(archive: zipfile.ZipFile) -> Iterator[tuple[str, str]]:
    for part in archive.namelist():
        if not part.endswith(".rels"):
            continue
        root = _read_part(archive, part)
        for element in _find_all(root, "Relationship") if root is not None else ():
            if element.get("TargetMode") == "External" and element.get("Target"):
                yield element.get("Type", ""), element.get("Target", "")


def _tables(
    archive: zipfile.ZipFile, root: Any, relationships: dict[str, tuple[str, str]]
) -> list[dict[str, Any]]:
    tables = []
    for element in _find_all(root, "tablePart"):
        kind, target = relationships.get(element.get(_R_ID, ""), ("", ""))
        table = _read_part(archive, target) if kind.endswith(_TABLE_REL) else None
        if table is not None:
            tables.append(
                {
                    "name": name(table.get("displayName") or table.get("name")),
                    "range": name(table.get("ref")),
                }
            )
    return tables


def _drawing_contents(
    archive: zipfile.ZipFile, root: Any, relationships: dict[str, tuple[str, str]]
) -> dict[str, Any]:
    charts = False
    images: list[str] = []
    for element in _find_all(root, "drawing"):
        kind, target = relationships.get(element.get(_R_ID, ""), ("", ""))
        if not kind.endswith(_DRAWING_REL):
            continue
        for drawing_kind, drawing_target in _relationships(archive, target).values():
            charts = charts or drawing_kind.endswith(_CHART_REL)
            if drawing_kind.endswith(_IMAGE_REL) and drawing_target not in images:
                images.append(drawing_target)
    return {"charts": charts, "images": images}
