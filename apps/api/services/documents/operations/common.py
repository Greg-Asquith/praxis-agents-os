# apps/api/services/documents/operations/common.py

"""Text, run, and geometry shapes shared by the presentation and Word operations."""

import re
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

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
        min_length=1,
        max_length=200,
        description=(
            "Rows of cell text; the first row is the header. A full http or https address in a "
            "cell becomes a link."
        ),
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


LINK_SCHEMES = frozenset({"http", "https", "mailto"})
_LINK_MAX_LENGTH = 2_000
_UNSAFE_LINK_CHARACTERS = re.compile(r"[\s\x00-\x1f\x7f<>\"\\]")


def link_or_none(value: str) -> str | None:
    """Returns the address when it's a web or email link that is safe to write, otherwise None.

    Office apps open a link's target when someone clicks it, so only http,
    https, and mailto addresses are written. Others, such as file or
    javascript addresses, could open local files or run code.
    """
    if len(value) > _LINK_MAX_LENGTH or _UNSAFE_LINK_CHARACTERS.search(value):
        return None
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if parts.scheme.lower() not in LINK_SCHEMES:
        return None
    if parts.scheme.lower() == "mailto":
        return value if "@" in parts.path else None
    return value if parts.hostname else None


def _check_link(value: str) -> str:
    if link_or_none(value) is None:
        raise ValueError("Use a full http, https, or mailto address, such as https://example.com.")
    return value


Link = Annotated[
    str,
    Field(
        max_length=_LINK_MAX_LENGTH,
        description="A full http, https, or mailto address the text links to.",
    ),
    AfterValidator(_check_link),
]


class Run(BaseModel):
    """Text with optional formatting. Unset fields keep the formatting the text inherits."""

    model_config = ConfigDict(extra="forbid")

    text: Text
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None
    size: Annotated[float, Field(ge=1, le=400, description="Points.")] | None = None
    color: Colour | None = None
    link: Link | None = None


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
