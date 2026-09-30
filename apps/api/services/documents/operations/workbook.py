# apps/api/services/documents/operations/workbook.py

"""Edit operations for Excel workbooks."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from services.documents.operations.common import HexColour, Operation

SheetName = Annotated[str, Field(min_length=1, max_length=31, description="A sheet name.")]
Cell = Annotated[
    str, Field(max_length=12, pattern=r"^\$?[A-Za-z]{1,3}\$?[0-9]{1,7}$", description="Such as B2.")
]
CellRange = Annotated[str, Field(max_length=40, description="A1 notation, such as B2:D20.")]
CellValue = Annotated[
    bool | int | float | Annotated[str, Field(max_length=32_767)] | None,
    Field(description="A string starting with = is a formula. None clears the cell."),
]
Block = Annotated[
    list[Annotated[list[CellValue], Field(max_length=200)]],
    Field(min_length=1, max_length=10_000),
]


class SetCells(Operation):
    """Writes a block of rows starting at anchor."""

    op: Literal["set_cells"]
    sheet: SheetName
    anchor: Cell
    values: Block


class SetNumberFormat(Operation):
    op: Literal["set_number_format"]
    sheet: SheetName
    range: CellRange
    format: Annotated[str, Field(max_length=255, description="Such as #,##0.00 or 0%.")]


class Font(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None
    size: Annotated[float, Field(ge=1, le=409)] | None = None
    color: HexColour | None = None
    name: Annotated[str, Field(max_length=100)] | None = None


class Alignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    horizontal: Literal["left", "center", "right", "justify"] | None = None
    vertical: Literal["top", "center", "bottom"] | None = None
    wrap: bool | None = None


class SetStyle(Operation):
    """Sets formatting over a range. Unset fields keep each cell's current formatting."""

    op: Literal["set_style"]
    sheet: SheetName
    range: CellRange
    font: Font | None = None
    fill: HexColour | None = None
    border: Literal["none", "thin", "medium", "thick"] | None = None
    alignment: Alignment | None = None


class AddSheet(Operation):
    op: Literal["add_sheet"]
    name: SheetName
    position: Annotated[int, Field(ge=1)] | None = None


class RenameSheet(Operation):
    """Renames a sheet and updates formulas and names that refer to it."""

    op: Literal["rename_sheet"]
    sheet: SheetName
    name: SheetName


class DeleteSheet(Operation):
    op: Literal["delete_sheet"]
    sheet: SheetName


class AppendRows(Operation):
    """Writes rows after the last row with a value, extending a table that ends there.

    A table that ends with a totals row can't be extended.
    """

    op: Literal["append_rows"]
    sheet: SheetName
    rows: Block


class MergeCells(Operation):
    """Merges a range. Every cell but the top-left one must be empty."""

    op: Literal["merge_cells"]
    sheet: SheetName
    range: CellRange


class SetColumnWidth(Operation):
    op: Literal["set_column_width"]
    sheet: SheetName
    columns: Annotated[
        str, Field(pattern=r"^[A-Za-z]{1,3}(:[A-Za-z]{1,3})?$", description="Such as C or A:D.")
    ]
    width: Annotated[float, Field(ge=0, le=255, description="Characters.")]


class FreezePanes(Operation):
    """Freezes rows above and columns left of cell. None unfreezes."""

    op: Literal["freeze_panes"]
    sheet: SheetName
    cell: Cell | None


class AddTable(Operation):
    """Formats a range as a table. Its first row must hold distinct text headers."""

    op: Literal["add_table"]
    sheet: SheetName
    range: CellRange
    name: Annotated[str, Field(min_length=1, max_length=255)]
    style: Annotated[str, Field(pattern=r"^TableStyle(Light|Medium|Dark)[0-9]{1,2}$")] = (
        "TableStyleMedium2"
    )


class ColorScale(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["color_scale"]
    start_color: HexColour
    end_color: HexColour
    mid_color: HexColour | None = None


class CellRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["cell_is"]
    operator: Literal[
        "greaterThan",
        "greaterThanOrEqual",
        "lessThan",
        "lessThanOrEqual",
        "equal",
        "notEqual",
        "between",
    ]
    values: Annotated[
        list[float | Annotated[str, Field(max_length=255)]],
        Field(
            min_length=1,
            max_length=2,
            description="Two for between. A string starting with = is a formula.",
        ),
    ]
    fill_color: HexColour | None = None
    font_color: HexColour | None = None


class AddConditionalFormat(Operation):
    op: Literal["add_conditional_format"]
    sheet: SheetName
    range: CellRange
    rule: Annotated[ColorScale | CellRule, Field(discriminator="kind")]


class AddDataValidation(Operation):
    """Restricts cells to a dropdown list."""

    op: Literal["add_data_validation"]
    sheet: SheetName
    range: CellRange
    options: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=100)]],
        Field(min_length=1, max_length=100),
    ]
    allow_blank: bool = True


class AddChart(Operation):
    """Adds a native chart from a range whose first row holds series names.

    A workbook with a chart can't be edited again, so add charts in the last edit.
    """

    op: Literal["add_chart"]
    sheet: SheetName
    anchor: Cell
    chart_type: Literal["column", "stacked_column", "bar", "stacked_bar", "line", "pie", "area"]
    data: Annotated[CellRange, Field(description="Series in columns, names in the first row.")]
    categories: (
        Annotated[CellRange, Field(description="One column of labels, no header.")] | None
    ) = None
    title: Annotated[str, Field(max_length=255)] | None = None
    x_title: Annotated[str, Field(max_length=255)] | None = None
    y_title: Annotated[str, Field(max_length=255)] | None = None


class DefineName(Operation):
    """Defines or replaces a workbook-level name."""

    op: Literal["define_name"]
    name: Annotated[str, Field(min_length=1, max_length=255)]
    refers_to: Annotated[str, Field(max_length=1_000, description="Such as Sales!$B$2:$B$20.")]


WorkbookOperation = Annotated[
    SetCells
    | SetNumberFormat
    | SetStyle
    | AddSheet
    | RenameSheet
    | DeleteSheet
    | AppendRows
    | MergeCells
    | SetColumnWidth
    | FreezePanes
    | AddTable
    | AddConditionalFormat
    | AddDataValidation
    | AddChart
    | DefineName,
    Field(discriminator="op"),
]
