# apps/api/services/documents/operations/common.py

"""Text, run, and geometry shapes shared by the presentation and Word operations."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Colour = Annotated[
    str,
    Field(
        pattern=r"^(#[0-9A-Fa-f]{6}|theme:[a-z0-9_]{1,40})$",
        description="#RRGGBB, or theme:<name> as reads return it.",
    ),
]
HexColour = Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$", description="#RRGGBB.")]
Points = Annotated[float, Field(ge=0, le=20_000, description="Points (1/72 inch).")]
SlideId = Annotated[int, Field(ge=1, description="A slide_id from a read, not the slide number.")]
ShapeId = Annotated[int, Field(ge=1, description="A shape_id from a read.")]
Text = Annotated[str, Field(max_length=10_000)]
TableRows = Annotated[
    list[Annotated[list[Annotated[str, Field(max_length=5_000)]], Field(max_length=50)]],
    Field(
        min_length=1, max_length=200, description="Rows of cell text; the first row is the header."
    ),
]
ChartType = Literal[
    "column",
    "stacked_column",
    "bar",
    "stacked_bar",
    "line",
    "line_markers",
    "pie",
    "doughnut",
    "area",
]


class Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Run(BaseModel):
    """Text with optional formatting. Unset fields keep the formatting the text inherits."""

    model_config = ConfigDict(extra="forbid")

    text: Text
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None
    size: Annotated[float, Field(ge=1, le=400, description="Points.")] | None = None
    color: Colour | None = None


RunInput = Annotated[Run | Text, Field(description="A run, or plain text.")]


class Paragraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runs: Annotated[list[RunInput], Field(min_length=1, max_length=200)]
    level: Annotated[int, Field(ge=0, le=8, description="Bullet or outline level.")] | None = None


ParagraphInput = Annotated[Paragraph | Text, Field(description="A paragraph, or plain text.")]
Paragraphs = Annotated[list[ParagraphInput], Field(min_length=1, max_length=500)]


class ChartSeries(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(max_length=255)]
    values: Annotated[list[float | None], Field(min_length=1, max_length=1_000)]


ChartCategories = Annotated[
    list[Annotated[str, Field(max_length=255)] | float],
    Field(min_length=1, max_length=1_000),
]
