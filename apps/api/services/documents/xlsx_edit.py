# apps/api/services/documents/xlsx_edit.py

"""Edits to workbooks. Runs only inside the document worker.

An edit needs a full openpyxl load, which costs about 100 times the file size
in memory, so workbooks above the cell limit are refused before loading.
openpyxl drops drawings, chart sheets, and some extensions when it saves, so
workbooks with them are refused rather than saved without them.
"""

import io
import math
import re
import warnings
import zipfile
from collections.abc import Callable, Iterator
from contextlib import closing
from copy import copy
from typing import Any

from services.documents.editing import EditLog, OperationError, run_operations
from services.documents.packages import open_archive, open_workbook_view, save_package
from services.documents.precheck import PackageLimits
from services.documents.reading import DocumentRequestError, name
from services.documents.xlsx_formulas import (
    WorkbookNames,
    formula_problems,
    referenced_sheets,
    rename_sheet,
)
from services.documents.xlsx_model import parse_range, sheets_with_drawings

_CELL = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c"
_CHUNK_BYTES = 64 * 1024
_WORKSHEET_PART = re.compile(r"^xl/worksheets/[^/]+\.xml$", re.IGNORECASE)
# Parts openpyxl reads and writes back, or drops without losing content (calculation
# chains, printer settings, and thumbnails). Any other part refuses the edit.
_KEPT_PARTS = re.compile(
    r"^(?:\[content_types\]\.xml|_rels/\.rels|docprops/(?:app|core|custom)\.xml"
    r"|docprops/thumbnail\.\w+|xl/workbook\.xml|xl/_rels/workbook\.xml\.rels|xl/styles\.xml"
    r"|xl/sharedstrings\.xml|xl/calcchain\.xml|xl/theme/[^/]+\.xml"
    r"|xl/worksheets/(?:_rels/)?[^/]+\.(?:xml|rels)|xl/tables/[^/]+\.xml"
    r"|xl/comments[^/]*\.xml|xl/comments/[^/]+\.xml|xl/drawings/[^/]+\.vml"
    r"|xl/externallinks/(?:_rels/)?[^/]+\.(?:xml|rels)"
    r"|xl/pivot(?:tables|cache)/(?:_rels/)?[^/]+\.(?:xml|rels)|xl/printersettings/[^/]+)$"
)
# Parts openpyxl doesn't keep when it saves, by the feature a person would recognise.
_DROPPED_PARTS = {
    "xl/charts/": "charts",
    "xl/chartsheets/": "chart sheets",
    "xl/drawings/": "drawings",
    "xl/media/": "images",
    "xl/threadedcomments/": "threaded comments",
    "xl/persons/": "threaded comments",
    "xl/slicers/": "slicers",
    "xl/slicercaches/": "slicers",
    "xl/timelines/": "timelines",
    "xl/model/": "a data model",
    "xl/querytables/": "queries",
    "xl/connections.xml": "data connections",
    "xl/metadata.xml": "dynamic array formulas",
    "xl/richdata/": "pictures in cells",
    "xl/ctrlprops/": "form controls",
    "xl/activex/": "form controls",
    "xl/embeddings/": "embedded objects",
    "customxml/": "custom XML data",
}
_NEW_WORKBOOK = (
    "Build the result in a new workbook with create_workbook, without this one as its template."
)
_MAX_RANGE_CELLS = 100_000
_MAX_STRING_CHARS = 32_767
_MAX_ROWS = 1_048_576
_MAX_COLUMNS = 16_384
_MAX_LISTED = 20
_INVALID_SHEET_CHARACTERS = re.compile(r"[\[\]:*?/\\]")
_DEFINED_NAME = re.compile(r"^[A-Za-z_\\][A-Za-z0-9_.\\]*$")
_CELL_LIKE_NAME = re.compile(r"^([A-Za-z]{1,3}[0-9]+|[Rr][0-9]*[Cc][0-9]*)$")
_CHART_CLASSES = {
    "column": ("BarChart", "col", "clustered"),
    "stacked_column": ("BarChart", "col", "stacked"),
    "bar": ("BarChart", "bar", "clustered"),
    "stacked_bar": ("BarChart", "bar", "stacked"),
    "line": ("LineChart", None, None),
    "pie": ("PieChart", None, None),
    "area": ("AreaChart", None, None),
}


def edit_workbook(
    data: bytes, args: dict[str, Any], limits: PackageLimits
) -> tuple[dict[str, Any], bytes]:
    """Applies operations to a workbook and returns the result and the saved bytes."""
    with closing(open_archive(data, limits)) as archive:
        _check_editable(data, archive, int(args["max_cells"]))
    workbook = _load(data)
    log = EditLog(args)
    editor = _WorkbookEditor(workbook)
    run_operations(args["operations"], editor.handlers(), log)
    editor.check_deleted_sheets()
    editor.check_table_headers()
    editor.check_formulas()
    if editor.has_formulas():
        log.warn(
            "Formula cells have no saved values until the workbook is opened in Excel. "
            "Compute any figure you report from source values."
        )
    if workbook.calculation is None:
        from openpyxl.workbook.properties import CalcProperties

        workbook.calculation = CalcProperties()
    workbook.calculation.fullCalcOnLoad = True
    result = log.result(lambda: editor.readback(log))
    return result, save_package(workbook, limits)


def _check_editable(data: bytes, archive: zipfile.ZipFile, max_cells: int) -> None:
    cells = 0
    for part in archive.namelist():
        if _WORKSHEET_PART.match(part) and cells <= max_cells:
            cells += _count_cells(archive, part, max_cells - cells)
    if cells > max_cells:
        raise DocumentRequestError(
            f"The workbook has more than the {max_cells:,} cells that edits support. "
            f"{_NEW_WORKBOOK}"
        )
    features = sorted(
        {
            _dropped_feature(part.lower())
            for part in archive.namelist()
            if not part.endswith("/") and not _KEPT_PARTS.match(part.lower())
        }
    )
    if not features:
        return
    view = open_workbook_view(data, data_only=False)
    try:
        sheets = sheets_with_drawings(view, archive)
    finally:
        view.close()
    where = f" Sheets with drawings: {', '.join(sheets[:_MAX_LISTED])}." if sheets else ""
    raise DocumentRequestError(
        f"The workbook has {', '.join(features)}, which editing would remove.{where} "
        f"{_NEW_WORKBOOK}"
    )


def _dropped_feature(part: str) -> str:
    return next(
        (feature for prefix, feature in _DROPPED_PARTS.items() if part.startswith(prefix)),
        "other content editing can't keep",
    )


class _CellCounter:
    """Parser target that counts cell elements without building a tree."""

    def __init__(self) -> None:
        self.count = 0

    def start(self, tag: str, attrib: dict[str, str]) -> None:
        if tag == _CELL:
            self.count += 1

    def close(self) -> None:
        return None


def _count_cells(archive: zipfile.ZipFile, part: str, limit: int) -> int:
    """Counts cell elements in a sheet part in any XML encoding, stopping once past `limit`."""
    from xml.etree.ElementTree import ParseError

    from defusedxml import DefusedXmlException
    from defusedxml.ElementTree import DefusedXMLParser

    counter = _CellCounter()
    parser = DefusedXMLParser(target=counter)
    try:
        with archive.open(part) as stream:
            while counter.count <= limit and (chunk := stream.read(_CHUNK_BYTES)):
                parser.feed(chunk)
    except (ParseError, DefusedXmlException):
        raise DocumentRequestError("A worksheet in the workbook isn't valid XML.") from None
    return counter.count


def _load(data: bytes) -> Any:
    from openpyxl import load_workbook

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        workbook = load_workbook(io.BytesIO(data), keep_vba=False, keep_links=True, rich_text=True)
    dropped = sorted(
        {
            str(warning.message).split(" extension", 1)[0]
            for warning in caught
            if "will be removed" in str(warning.message)
        }
    )
    if dropped:
        raise DocumentRequestError(
            "The workbook uses features that editing would remove: "
            f"{', '.join(dropped[:_MAX_LISTED])}. {_NEW_WORKBOOK}"
        )
    return workbook


class _WorkbookEditor:
    def __init__(self, workbook: Any) -> None:
        self.workbook = workbook
        # Worksheet, bounds, and operation of each block written, for checks and the read-back.
        self.written: list[tuple[Any, tuple[int, int, int, int], int]] = []
        # Formula cells written, with the operation that wrote them.
        self.formulas: dict[tuple[Any, str], int] = {}
        # Names defined, conditional format rules, and charts added, with their operations.
        self.names: dict[str, int] = {}
        self.rules: list[tuple[int, Any, Any]] = []
        self.charts: list[tuple[int, Any, Any]] = []
        self.deleted: dict[str, int] = {}

    def handlers(self) -> dict[str, Any]:
        return {
            "set_cells": self.set_cells,
            "set_number_format": self.set_number_format,
            "set_style": self.set_style,
            "add_sheet": self.add_sheet,
            "rename_sheet": self.rename_sheet,
            "delete_sheet": self.delete_sheet,
            "append_rows": self.append_rows,
            "merge_cells": self.merge_cells,
            "set_column_width": self.set_column_width,
            "freeze_panes": self.freeze_panes,
            "add_table": self.add_table,
            "add_conditional_format": self.add_conditional_format,
            "add_data_validation": self.add_data_validation,
            "add_chart": self.add_chart,
            "define_name": self.define_name,
        }

    def set_cells(self, operation: dict[str, Any], log: EditLog) -> None:
        from openpyxl.utils.cell import column_index_from_string, coordinate_from_string

        sheet = self._sheet(operation["sheet"])
        column, row = coordinate_from_string(operation["anchor"].replace("$", ""))
        written = self._write_block(
            sheet, row, column_index_from_string(column), operation["values"], log
        )
        log.change(f"Wrote {written} cells in {_title(sheet)}.", sheet=_title(sheet))

    def append_rows(self, operation: dict[str, Any], log: EditLog) -> None:
        from openpyxl.utils.cell import range_boundaries

        sheet = self._sheet(operation["sheet"])
        last = max(
            (row for (row, _), cell in sheet._cells.items() if cell.value is not None), default=0
        )
        rows = operation["rows"]
        tables = []
        for table in sheet.tables.values():
            min_col, min_row, max_col, max_row = range_boundaries(table.ref)
            if max_row == last and last > min_row:
                if table.totalsRowCount:
                    # Rows would land below the totals row, which can't move in this version.
                    raise OperationError(
                        f"Table {name(table.displayName)!r} ends with a totals row, so rows can't "
                        "be appended to it. Write the rows with set_cells above the totals row "
                        "instead, or build the table in a new workbook."
                    )
                tables.append((table, min_col, min_row, max_col))
        self._write_block(sheet, last + 1, 1, rows, log)
        for table, min_col, min_row, max_col in tables:
            table.ref = _range(min_col, min_row, max_col, last + len(rows))
            if table.autoFilter is not None:
                table.autoFilter.ref = table.ref
        summary = f"Appended {len(rows)} rows to {_title(sheet)} from row {last + 1}."
        if tables:
            summary += f" Extended {len(tables)} {'table' if len(tables) == 1 else 'tables'}."
        log.change(
            summary,
            sheet=_title(sheet),
            first_row=last + 1,
            **({"tables": [name(table.displayName) for table, *_ in tables]} if tables else {}),
        )

    def set_number_format(self, operation: dict[str, Any], log: EditLog) -> None:
        sheet = self._sheet(operation["sheet"])
        for cell in self._cells(sheet, operation["range"]):
            cell.number_format = operation["format"]
        log.change(f"Set the number format of {_title(sheet)}!{operation['range']}.")

    def set_style(self, operation: dict[str, Any], log: EditLog) -> None:
        from openpyxl.styles import Border, PatternFill, Side

        sheet = self._sheet(operation["sheet"])
        font, alignment = operation.get("font"), operation.get("alignment")
        fill = operation.get("fill")
        border = operation.get("border")
        side = Side(style=None if border == "none" else border)
        for cell in self._cells(sheet, operation["range"]):
            if font:
                cell.font = _font(cell.font, font)
            if fill:
                cell.fill = PatternFill(fill_type="solid", start_color=fill[1:], end_color=fill[1:])
            if border:
                cell.border = Border(left=side, right=side, top=side, bottom=side)
            if alignment:
                cell.alignment = _alignment(cell.alignment, alignment)
        log.change(f"Formatted {_title(sheet)}!{operation['range']}.")

    def add_sheet(self, operation: dict[str, Any], log: EditLog) -> None:
        title = self._new_sheet_name(operation["name"])
        position = operation.get("position")
        count = len(self.workbook.sheetnames)
        if position is not None and not 1 <= position <= count + 1:
            raise OperationError(f"position must be between 1 and {count + 1}.")
        self.workbook.create_sheet(title, None if position is None else position - 1)
        self.deleted.pop(title.casefold(), None)
        log.change(f"Added sheet {title}.", sheet=title)

    def rename_sheet(self, operation: dict[str, Any], log: EditLog) -> None:
        sheet = self._sheet(operation["sheet"])
        old = sheet.title
        new = self._new_sheet_name(operation["name"], renaming=sheet)
        if new != old and new.casefold() == old.casefold():
            # openpyxl numbers a title that matches any sheet's, this one's included.
            sheet.title = "Sheet"
        sheet.title = new
        new = sheet.title
        self.deleted.pop(new.casefold(), None)
        for _, _, text, update in self._stored_formulas():
            renamed = rename_sheet(text, old, new)
            if renamed != text:
                update(renamed)
        log.change(f"Renamed sheet {name(old)} to {new}.", sheet=new)

    def delete_sheet(self, operation: dict[str, Any], log: EditLog) -> None:
        sheet = self._sheet(operation["sheet"])
        visible = [item for item in self.workbook.worksheets if item.sheet_state == "visible"]
        if visible == [sheet]:
            raise OperationError("A workbook needs at least one visible sheet.")
        self.workbook.remove(sheet)
        self.deleted[sheet.title.casefold()] = log.index
        self.written = [written for written in self.written if written[0] is not sheet]
        log.change(f"Deleted sheet {_title(sheet)}.", sheet=_title(sheet))

    def merge_cells(self, operation: dict[str, Any], log: EditLog) -> None:
        from openpyxl.worksheet.cell_range import CellRange

        sheet = self._sheet(operation["sheet"])
        target = CellRange(_range(*self._bounds(sheet, operation["range"])))
        for merged in sheet.merged_cells.ranges:
            if not merged.isdisjoint(target):
                raise OperationError(f"{target.coord} overlaps the merged range {merged.coord}.")
        for row, column in target.cells:
            cell = sheet._cells.get((row, column))
            if (row, column) == (target.min_row, target.min_col) or cell is None:
                continue
            if cell.value is not None or cell.comment is not None or cell.hyperlink is not None:
                # Merging clears every cell but the top-left one.
                raise OperationError(
                    f"{cell.coordinate} has content that merging would remove. Clear it or "
                    "move it to the top-left cell first."
                )
        sheet.merge_cells(target.coord)
        log.change(f"Merged {_title(sheet)}!{target.coord}.")

    def set_column_width(self, operation: dict[str, Any], log: EditLog) -> None:
        from openpyxl.utils.cell import column_index_from_string, get_column_letter

        sheet = self._sheet(operation["sheet"])
        first, _, last = operation["columns"].upper().partition(":")
        start, end = column_index_from_string(first), column_index_from_string(last or first)
        if not 1 <= start <= end <= _MAX_COLUMNS:
            raise OperationError(f"{operation['columns']!r} isn't a column range.")
        for index in range(start, end + 1):
            sheet.column_dimensions[get_column_letter(index)].width = operation["width"]
        log.change(f"Set the width of {_title(sheet)} columns {operation['columns'].upper()}.")

    def freeze_panes(self, operation: dict[str, Any], log: EditLog) -> None:
        sheet = self._sheet(operation["sheet"])
        cell = operation.get("cell")
        sheet.freeze_panes = _grid_cell(cell) if cell else None
        log.change(f"Set frozen panes on {_title(sheet)}." if cell else f"Unfroze {_title(sheet)}.")

    def add_table(self, operation: dict[str, Any], log: EditLog) -> None:
        from openpyxl.worksheet.cell_range import CellRange
        from openpyxl.worksheet.table import Table, TableStyleInfo

        sheet = self._sheet(operation["sheet"])
        table_name = operation["name"]
        if not _DEFINED_NAME.match(table_name) or _CELL_LIKE_NAME.match(table_name):
            raise OperationError(f"{table_name!r} isn't a valid table name.")
        if table_name.casefold() in self._known().tables | self._known().names:
            raise OperationError(f"The workbook already has a table or name {table_name!r}.")
        min_col, min_row, max_col, max_row = self._bounds(sheet, operation["range"])
        if max_row <= min_row:
            raise OperationError("A table needs a header row and at least one data row.")
        target = CellRange(_range(min_col, min_row, max_col, max_row))
        for existing in sheet.tables.values():
            if not CellRange(existing.ref).isdisjoint(target):
                raise OperationError(f"The range overlaps table {name(existing.displayName)!r}.")
        headers = [sheet.cell(min_row, column).value for column in range(min_col, max_col + 1)]
        if not all(isinstance(header, str) and header.strip() for header in headers):
            raise OperationError("Every cell in the table's first row must hold header text.")
        if len({header.casefold() for header in headers}) != len(headers):
            raise OperationError("The table's header texts must differ.")
        table = Table(displayName=table_name, ref=target.coord)
        table.tableStyleInfo = TableStyleInfo(name=operation["style"], showRowStripes=True)
        sheet.add_table(table)
        log.change(f"Added table {table_name} at {_title(sheet)}!{target.coord}.")

    def add_conditional_format(self, operation: dict[str, Any], log: EditLog) -> None:
        from openpyxl.formatting.rule import CellIsRule, ColorScaleRule
        from openpyxl.styles import Font, PatternFill

        sheet = self._sheet(operation["sheet"])
        target = _range(*self._bounds(sheet, operation["range"]))
        rule = operation["rule"]
        if rule["kind"] == "color_scale":
            middle = (
                {"mid_type": "percentile", "mid_value": 50, "mid_color": rule["mid_color"][1:]}
                if rule.get("mid_color")
                else {}
            )
            formatting = ColorScaleRule(
                start_type="min",
                start_color=rule["start_color"][1:],
                end_type="max",
                end_color=rule["end_color"][1:],
                **middle,
            )
        else:
            expected = 2 if rule["operator"] == "between" else 1
            if len(rule["values"]) != expected:
                raise OperationError(f"{rule['operator']} takes {expected} values.")
            fill = rule.get("fill_color")
            font_color = rule.get("font_color")
            formatting = CellIsRule(
                operator=rule["operator"],
                formula=[_rule_value(value) for value in rule["values"]],
                fill=PatternFill(fill_type="solid", start_color=fill[1:], end_color=fill[1:])
                if fill
                else None,
                font=Font(color=font_color[1:]) if font_color else None,
            )
        sheet.conditional_formatting.add(target, formatting)
        if formatting.formula:
            self.rules.append((log.index, sheet, formatting))
        log.change(f"Added conditional formatting to {_title(sheet)}!{target}.")

    def add_data_validation(self, operation: dict[str, Any], log: EditLog) -> None:
        from openpyxl.worksheet.datavalidation import DataValidation

        sheet = self._sheet(operation["sheet"])
        target = _range(*self._bounds(sheet, operation["range"]))
        options = operation["options"]
        if any("," in option or '"' in option for option in options):
            raise OperationError("Dropdown options can't contain commas or double quotes.")
        joined = ",".join(options)
        if len(joined) > 255:
            raise OperationError("Dropdown options can hold at most 255 characters together.")
        validation = DataValidation(
            type="list",
            formula1=f'"{joined}"',
            allow_blank=operation["allow_blank"],
            showErrorMessage=True,
            errorStyle="stop",
        )
        validation.add(target)
        sheet.add_data_validation(validation)
        log.change(f"Added a dropdown to {_title(sheet)}!{target}.")

    def add_chart(self, operation: dict[str, Any], log: EditLog) -> None:
        from openpyxl import chart as charts
        from openpyxl.chart import Reference

        sheet = self._sheet(operation["sheet"])
        class_name, direction, grouping = _CHART_CLASSES[operation["chart_type"]]
        chart = getattr(charts, class_name)()
        if direction is not None:
            chart.type = direction
            chart.grouping = grouping
            if grouping == "stacked":
                chart.overlap = 100
        min_col, min_row, max_col, max_row = self._bounds(sheet, operation["data"])
        if max_row <= min_row:
            raise OperationError(
                "The chart data needs a row of series names and at least one row of values."
            )
        chart.add_data(Reference(sheet, min_col, min_row, max_col, max_row), titles_from_data=True)
        if operation.get("categories"):
            cat_col, cat_min, cat_max_col, cat_max = self._bounds(sheet, operation["categories"])
            chart.set_categories(Reference(sheet, cat_col, cat_min, cat_max_col, cat_max))
        chart.title = operation.get("title")
        if operation.get("x_title") and hasattr(chart, "x_axis"):
            chart.x_axis.title = operation["x_title"]
        if operation.get("y_title") and hasattr(chart, "y_axis"):
            chart.y_axis.title = operation["y_title"]
        sheet.add_chart(chart, _grid_cell(operation["anchor"]))
        self.charts.append((log.index, sheet, chart))
        log.warn(
            "The workbook now has a chart, so edit_workbook can't change it again. "
            "Make other changes before adding charts."
        )
        log.change(f"Added a {operation['chart_type']} chart to {_title(sheet)}.")

    def define_name(self, operation: dict[str, Any], log: EditLog) -> None:
        from openpyxl.workbook.defined_name import DefinedName

        defined = operation["name"]
        if not _DEFINED_NAME.match(defined) or _CELL_LIKE_NAME.match(defined):
            raise OperationError(f"{defined!r} isn't a valid name.")
        if defined.casefold() in self._known().tables:
            raise OperationError(f"{defined!r} is already a table name.")
        refers_to = operation["refers_to"].removeprefix("=")
        existing = next(
            (key for key in self.workbook.defined_names if key.casefold() == defined.casefold()),
            None,
        )
        if existing is not None:
            del self.workbook.defined_names[existing]
        self.workbook.defined_names[defined] = DefinedName(defined, attr_text=refers_to)
        # The final definition is checked, so later renames and redefinitions count.
        self.names[defined.casefold()] = log.index
        log.change(f"{'Updated' if existing else 'Defined'} the name {defined}.")

    def check_deleted_sheets(self) -> None:
        """Fails the edit when anything left in the workbook refers to a sheet the edit deleted."""
        if not self.deleted:
            return
        for label, _, text, _ in self._stored_formulas():
            hits = referenced_sheets(text) & self.deleted.keys()
            if hits:
                raise DocumentRequestError(
                    f"operations[{self.deleted[min(hits)]}] (delete_sheet): {label} still refers "
                    "to the deleted sheet. Nothing was saved."
                )

    def check_table_headers(self) -> None:
        """Fails the edit when a write leaves a table header Excel would have to repair.

        Excel keeps each table column's name in step with its header cell and
        structured references use that name, so changing a saved header is refused.
        """
        # The last write to a header decides what it holds.
        for sheet, bounds, index in reversed(self.written):
            for table in sheet.tables.values():
                problem = _header_problem(sheet, table, bounds)
                if problem:
                    raise DocumentRequestError(
                        f"operations[{index}]: {problem} in table {name(table.displayName)!r}. "
                        "Nothing was saved."
                    )

    def check_formulas(self) -> None:
        """Fails the edit when a formula, name, rule, or chart it added refers to something missing.

        Each is checked as it stands after every operation, from the sheet it lives on.
        """
        known = self._known()
        for index, label, sheet, text in self._added_formulas():
            problems = formula_problems(text, known, sheet=sheet)
            if problems:
                raise DocumentRequestError(
                    f"operations[{index}]: {label} {problems[0]}. Nothing was saved."
                )

    def has_formulas(self) -> bool:
        return next(self._formula_cells(), None) is not None

    def readback(self, log: EditLog) -> dict[str, Any]:
        blocks = []
        for sheet, (min_col, min_row, max_col, max_row), _ in self.written:
            cells = []
            for row in sheet.iter_rows(
                min_row=min_row, max_row=max_row, min_col=min_col, max_col=max_col
            ):
                cells.extend(_readback_cell(cell, log) for cell in row)
            block = {
                "sheet": _title(sheet),
                "range": _range(min_col, min_row, max_col, max_row),
                "cells": cells,
            }
            if not log.page.fits(block):
                return {"blocks": blocks, "blocks_truncated": True}
            blocks.append(block)
        return {"blocks": blocks}

    def _write_block(
        self, sheet: Any, row: int, column: int, values: list[list[Any]], log: EditLog
    ) -> int:
        from openpyxl.cell.cell import MergedCell

        width = max((len(row_values) for row_values in values), default=0)
        if row + len(values) - 1 > _MAX_ROWS or column + max(width, 1) - 1 > _MAX_COLUMNS:
            raise OperationError("The values run past the edge of the sheet.")
        written = 0
        for row_offset, row_values in enumerate(values):
            for column_offset, value in enumerate(row_values):
                cell = sheet.cell(row=row + row_offset, column=column + column_offset)
                if isinstance(cell, MergedCell):
                    raise OperationError(
                        f"{cell.coordinate} is inside a merged range. Write to its top-left cell."
                    )
                _check_value(value, cell.coordinate)
                try:
                    cell.value = value
                except ValueError:
                    raise OperationError(
                        f"{cell.coordinate} has characters Excel can't store."
                    ) from None
                if isinstance(value, str) and value.startswith("="):
                    self.formulas[(sheet, cell.coordinate)] = log.index
                else:
                    self.formulas.pop((sheet, cell.coordinate), None)
                written += 1
        if width:
            bounds = (column, row, column + width - 1, row + len(values) - 1)
            self.written.append((sheet, bounds, log.index))
        return written

    def _sheet(self, sheet_name: str) -> Any:
        for matches in (
            lambda title: title == sheet_name,
            lambda title: title.casefold() == sheet_name.casefold(),
        ):
            for sheet in self.workbook.worksheets:
                if matches(sheet.title):
                    return sheet
        if any(
            sheet.title.casefold() == sheet_name.casefold() for sheet in self.workbook.chartsheets
        ):
            raise OperationError(f"{sheet_name!r} is a chart sheet and has no cells.")
        names = ", ".join(repr(name(title)) for title in self.workbook.sheetnames[:50])
        raise OperationError(f"The workbook has no sheet {sheet_name!r}. Its sheets are: {names}.")

    def _new_sheet_name(self, title: str, renaming: Any = None) -> str:
        title = title.strip()
        if (
            not title
            or _INVALID_SHEET_CHARACTERS.search(title)
            or title.startswith("'")
            or title.endswith("'")
        ):
            raise OperationError(
                f"{title!r} isn't a valid sheet name. Names can't contain [ ] : * ? / \\ or start or "
                "end with an apostrophe."
            )
        for sheet in self.workbook.worksheets + self.workbook.chartsheets:
            if sheet is not renaming and sheet.title.casefold() == title.casefold():
                raise OperationError(f"The workbook already has a sheet named {title!r}.")
        return title

    def _bounds(self, sheet: Any, cell_range: str) -> tuple[int, int, int, int]:
        """Returns a bounded range. Whole rows and columns stop at the sheet's used area."""
        try:
            min_col, min_row, max_col, max_row = parse_range(cell_range)
        except DocumentRequestError as exc:
            raise OperationError(str(exc)) from None
        min_col, min_row = min_col or 1, min_row or 1
        max_col = max_col or max(sheet.max_column, min_col)
        max_row = max_row or max(sheet.max_row, min_row)
        if (max_col - min_col + 1) * (max_row - min_row + 1) > _MAX_RANGE_CELLS:
            raise OperationError(f"The range covers more than {_MAX_RANGE_CELLS:,} cells.")
        return min_col, min_row, max_col, max_row

    def _cells(self, sheet: Any, cell_range: str) -> Iterator[Any]:
        from openpyxl.cell.cell import MergedCell

        min_col, min_row, max_col, max_row = self._bounds(sheet, cell_range)
        for row in sheet.iter_rows(
            min_row=min_row, max_row=max_row, min_col=min_col, max_col=max_col
        ):
            for cell in row:
                if not isinstance(cell, MergedCell):
                    yield cell

    def _formula_cells(self) -> Iterator[Any]:
        for sheet in self.workbook.worksheets:
            for cell in list(sheet._cells.values()):
                if cell.data_type == "f":
                    yield cell

    def _added_formulas(self) -> Iterator[tuple[int, str, str | None, str]]:
        """Yields (operation, label, owning sheet, formula) for what this edit added."""
        live = set(map(id, self.workbook.worksheets))
        for (sheet, coordinate), index in self.formulas.items():
            if id(sheet) in live:
                label = f"{_title(sheet)}!{coordinate}"
                yield index, label, sheet.title, _formula(sheet[coordinate])
        for defined in self.workbook.defined_names.values():
            index = self.names.get(defined.name.casefold())
            if index is not None:
                yield index, f"the name {defined.name}", None, f"={defined.attr_text}"
        added = [
            (index, "conditional format", sheet, rule.formula) for index, sheet, rule in self.rules
        ]
        added += [
            (index, "chart", sheet, [holder.f for holder in _chart_references(chart)])
            for index, sheet, chart in self.charts
        ]
        for index, kind, sheet, texts in added:
            if id(sheet) in live:
                for text in texts:
                    yield index, f"the {kind} on {_title(sheet)}", sheet.title, f"={text}"

    def _stored_formulas(self) -> Iterator[tuple[str, Any, str, Callable[[str], None]]]:
        """Yields (label, owning sheet, formula, setter) for every expression a sheet change affects.

        Covers formula cells, defined names, conditional formats, data validations,
        and charts this edit added. Setters take the formula with its "=".
        """
        for cell in self._formula_cells():
            yield (
                f"{_title(cell.parent)}!{cell.coordinate}",
                cell.parent,
                _formula(cell),
                lambda text, cell=cell: _set_formula(cell, text),
            )
        for sheet, defined in self._defined_names():
            yield (
                f"the name {name(defined.name)}",
                sheet,
                f"={defined.attr_text}",
                lambda text, defined=defined: setattr(defined, "attr_text", text[1:]),
            )
        for sheet in self.workbook.worksheets:
            yield from _rule_formulas(sheet)
        live = set(map(id, self.workbook.worksheets))
        for _, sheet, chart in self.charts:
            if id(sheet) not in live:
                continue
            for holder in _chart_references(chart):
                yield (
                    f"the chart on {_title(sheet)}",
                    sheet,
                    f"={holder.f}",
                    lambda new, holder=holder: setattr(holder, "f", new[1:]),
                )

    def _defined_names(self) -> Iterator[tuple[Any, Any]]:
        """Yields (owning sheet or None, defined name) for workbook and sheet-local names."""
        for defined in self.workbook.defined_names.values():
            yield None, defined
        for sheet in self.workbook.worksheets:
            for defined in sheet.defined_names.values():
                yield sheet, defined

    def _known(self) -> WorkbookNames:
        local_names: dict[str, set[str]] = {}
        for sheet in self.workbook.worksheets:
            local_names[sheet.title.casefold()] = {
                defined.casefold() for defined in sheet.defined_names
            }
        tables = {
            table_name.casefold()
            for sheet in self.workbook.worksheets
            for table_name in sheet.tables
        }
        return WorkbookNames(
            sheets=frozenset(title.casefold() for title in self.workbook.sheetnames),
            names=frozenset(defined.casefold() for defined in self.workbook.defined_names),
            local_names={key: frozenset(value) for key, value in local_names.items()},
            tables=frozenset(tables),
        )


def _header_problem(sheet: Any, table: Any, written: tuple[int, int, int, int]) -> str | None:
    from openpyxl.utils.cell import range_boundaries

    min_col, min_row, max_col, _ = range_boundaries(table.ref)
    first_col, first_row, last_col, last_row = written
    if not table.headerRowCount or not (
        first_row <= min_row <= last_row and first_col <= max_col and min_col <= last_col
    ):
        return None
    cells = [sheet.cell(min_row, column) for column in range(min_col, max_col + 1)]
    headers = [cell.value if isinstance(cell.value, str) else _text(cell.value) for cell in cells]
    if not all(
        isinstance(header, str) and header.strip() and cell.data_type == "s"
        for header, cell in zip(headers, cells, strict=True)
    ):
        return "a header cell needs text"
    if len({header.casefold() for header in headers}) != len(headers):
        return "header texts must differ"
    columns = [column.name for column in table.tableColumns]
    if columns and columns != headers:
        return "the header changes a column name, which this edit can't carry into formulas"
    return None


def _text(value: Any) -> str | None:
    from openpyxl.cell.rich_text import CellRichText

    return str(value) if isinstance(value, CellRichText) else None


def _grid_cell(reference: str) -> str:
    """Returns a cell reference inside the sheet's grid, in upper case without $ signs."""
    cell = reference.replace("$", "").upper()
    try:
        parse_range(cell)
    except DocumentRequestError:
        raise OperationError(f"{reference!r} is outside the sheet.") from None
    return cell


def _check_value(value: Any, coordinate: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise OperationError(f"{coordinate} needs a finite number.")
    if isinstance(value, str) and len(value) > _MAX_STRING_CHARS:
        raise OperationError(f"{coordinate} has more than {_MAX_STRING_CHARS:,} characters.")


def _rule_value(value: Any) -> str:
    if isinstance(value, str):
        if value.startswith("="):
            return value[1:]
        return '"' + value.replace('"', '""') + '"'
    if not math.isfinite(value):
        raise OperationError("Rule values must be finite numbers.")
    return repr(value)


def _rule_formulas(sheet: Any) -> Iterator[tuple[str, Any, str, Callable[[str], None]]]:
    """Yields the formulas of a sheet's conditional formats and dropdowns, with setters."""
    for formatting in sheet.conditional_formatting:
        for rule in formatting.rules:
            for position, text in enumerate(rule.formula or []):
                yield (
                    f"a conditional format on {_title(sheet)}",
                    sheet,
                    f"={text}",
                    lambda new, rule=rule, position=position: rule.formula.__setitem__(
                        position, new[1:]
                    ),
                )
    for validation in sheet.data_validations.dataValidation:
        for attribute in ("formula1", "formula2"):
            if getattr(validation, attribute):
                yield (
                    f"a dropdown on {_title(sheet)}",
                    sheet,
                    f"={getattr(validation, attribute)}",
                    lambda new, item=validation, key=attribute: setattr(item, key, new[1:]),
                )


def _chart_references(chart: Any) -> Iterator[Any]:
    """Yields the chart's series title, category, and value references, each with an `f`."""
    for series in chart.series:
        sources = (series.tx, series.cat, series.val, series.xVal, series.yVal)
        for source in sources:
            for attribute in ("strRef", "numRef"):
                reference = getattr(source, attribute, None)
                if reference is not None and reference.f:
                    yield reference


def _title(sheet: Any) -> str:
    return name(sheet.title)


def _formula(cell: Any) -> str:
    return str(getattr(cell.value, "text", cell.value))


def _set_formula(cell: Any, text: str) -> None:
    if hasattr(cell.value, "text"):
        cell.value.text = text
    else:
        cell.value = text


def _readback_cell(cell: Any, log: EditLog) -> dict[str, Any]:
    if cell.data_type == "f":
        return {
            "ref": cell.coordinate,
            "value": None,
            "formula": log.page.text(_formula(cell)),
            "calculated": False,
        }
    return {"ref": cell.coordinate, "value": log.page.value(cell.value)}


def _font(current: Any, changes: dict[str, Any]) -> Any:
    font = copy(current)
    for key in ("bold", "italic", "size", "name"):
        if changes.get(key) is not None:
            setattr(font, key, changes[key])
    if changes.get("underline") is not None:
        font.underline = "single" if changes["underline"] else None
    if changes.get("color"):
        font.color = "FF" + changes["color"][1:].upper()
    return font


def _alignment(current: Any, changes: dict[str, Any]) -> Any:
    alignment = copy(current)
    if changes.get("horizontal"):
        alignment.horizontal = changes["horizontal"]
    if changes.get("vertical"):
        alignment.vertical = changes["vertical"]
    if changes.get("wrap") is not None:
        alignment.wrap_text = changes["wrap"]
    return alignment


def _range(min_col: int, min_row: int, max_col: int, max_row: int) -> str:
    from openpyxl.utils.cell import get_column_letter

    start = f"{get_column_letter(min_col)}{min_row}"
    end = f"{get_column_letter(max_col)}{max_row}"
    return start if start == end else f"{start}:{end}"
