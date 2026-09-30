# apps/api/services/documents/operations/presentation.py

"""Edit operations for PowerPoint decks."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.agents.runtime.entity_references.domain import FileReference
from services.documents.operations.common import (
    ChartCategories,
    ChartSeries,
    ChartType,
    Operation,
    Paragraphs,
    Points,
    ShapeId,
    SlideId,
    TableRows,
    Text,
)

Position = Annotated[int, Field(ge=1, description="Slide number to place it at, starting at 1.")]


class PlaceholderText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idx: Annotated[int, Field(ge=0, description="Placeholder idx from the layout.")]
    paragraphs: Paragraphs


class AddSlide(Operation):
    """Adds a slide from a layout, optionally filling its placeholders."""

    op: Literal["add_slide"]
    layout: Annotated[str, Field(max_length=100, description="A layout name from the read.")]
    position: Position | None = None
    placeholders: Annotated[list[PlaceholderText], Field(max_length=20)] | None = None
    notes: Text | None = None


class DuplicateSlide(Operation):
    """Copies a slide, placing the copy after it unless position is given."""

    op: Literal["duplicate_slide"]
    slide_id: SlideId
    position: Position | None = None


class DeleteSlide(Operation):
    op: Literal["delete_slide"]
    slide_id: SlideId


class MoveSlide(Operation):
    op: Literal["move_slide"]
    slide_id: SlideId
    position: Position


class SetText(Operation):
    """Replaces a shape's text. New text keeps the first run's formatting unless a run overrides it."""

    op: Literal["set_text"]
    slide_id: SlideId
    shape_id: ShapeId
    paragraphs: Paragraphs


class ReplaceText(Operation):
    """Replaces every match, keeping run formatting. Fails when nothing matches."""

    op: Literal["replace_text"]
    find: Annotated[str, Field(min_length=1, max_length=1_000)]
    replace: Annotated[str, Field(max_length=10_000)]
    slide_id: SlideId | None = Field(default=None, description="Limit to one slide.")
    shape_id: ShapeId | None = Field(
        default=None, description="Limit to one shape; needs slide_id."
    )
    match_case: bool = True

    @model_validator(mode="after")
    def _shape_needs_slide(self) -> "ReplaceText":
        if self.shape_id is not None and self.slide_id is None:
            raise ValueError("shape_id needs slide_id")
        return self


class AddTextBox(Operation):
    op: Literal["add_text_box"]
    slide_id: SlideId
    left: Points
    top: Points
    width: Points
    height: Points
    paragraphs: Paragraphs


class SetTable(Operation):
    """Sets a table's cell text. Extra rows copy the last row's formatting; columns must fit."""

    op: Literal["set_table"]
    slide_id: SlideId
    shape_id: ShapeId
    rows: TableRows


class AddTable(Operation):
    op: Literal["add_table"]
    slide_id: SlideId
    rows: TableRows
    left: Points
    top: Points
    width: Points
    height: Points


class AddImage(Operation):
    """Adds an image File. With neither width nor height, it keeps its size, scaled to fit."""

    op: Literal["add_image"]
    slide_id: SlideId
    image_file_id: FileReference
    left: Points
    top: Points
    width: Points | None = None
    height: Points | None = None


class ReplaceImage(Operation):
    """Swaps a picture's image, keeping its position and size."""

    op: Literal["replace_image"]
    slide_id: SlideId
    shape_id: ShapeId
    image_file_id: FileReference


class AddChart(Operation):
    """Adds a native chart. Each series needs one value per category."""

    op: Literal["add_chart"]
    slide_id: SlideId
    chart_type: ChartType
    categories: ChartCategories
    series: Annotated[list[ChartSeries], Field(min_length=1, max_length=50)]
    title: Annotated[str, Field(max_length=255)] | None = None
    left: Points
    top: Points
    width: Points
    height: Points


class SetChartData(Operation):
    """Replaces a category chart's data, keeping its formatting."""

    op: Literal["set_chart_data"]
    slide_id: SlideId
    shape_id: ShapeId
    categories: ChartCategories
    series: Annotated[list[ChartSeries], Field(min_length=1, max_length=50)]


class SetNotes(Operation):
    op: Literal["set_notes"]
    slide_id: SlideId
    text: Text


class SetGeometry(Operation):
    op: Literal["set_geometry"]
    slide_id: SlideId
    shape_id: ShapeId
    left: Points | None = None
    top: Points | None = None
    width: Points | None = None
    height: Points | None = None


class DeleteShape(Operation):
    op: Literal["delete_shape"]
    slide_id: SlideId
    shape_id: ShapeId


PresentationOperation = Annotated[
    AddSlide
    | DuplicateSlide
    | DeleteSlide
    | MoveSlide
    | SetText
    | ReplaceText
    | AddTextBox
    | SetTable
    | AddTable
    | AddImage
    | ReplaceImage
    | AddChart
    | SetChartData
    | SetNotes
    | SetGeometry
    | DeleteShape,
    Field(discriminator="op"),
]
