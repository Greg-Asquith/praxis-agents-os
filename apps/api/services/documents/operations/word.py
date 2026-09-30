# apps/api/services/documents/operations/word.py

"""Edit operations for Word documents.

Paragraph and table indexes count only paragraphs and tables directly in the
body, as reads number them, and refer to the document as the earlier
operations in the same call left it.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.agents.runtime.entity_references.domain import FileReference
from services.documents.operations.common import Operation, Points, RunInput, TableRows, Text

Index = Annotated[int, Field(ge=0, description="A paragraph index from the read.")]
ExpectText = Annotated[
    str,
    Field(
        max_length=1_000,
        description="The start of the paragraph's current text, or empty for an empty paragraph.",
    ),
]
StyleName = Annotated[str, Field(max_length=100, description="A style name from the read.")]


class WordParagraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runs: Annotated[list[RunInput], Field(min_length=1, max_length=200)]
    style: StyleName | None = None


class _Placed(Operation):
    """Places new content before or after a paragraph, or at the end without an index."""

    index: Index | None = None
    expect_text: ExpectText | None = None
    position: Literal["before", "after"] = "after"

    @model_validator(mode="after")
    def _anchor_is_complete(self) -> "_Placed":
        if (self.index is None) != (self.expect_text is None):
            raise ValueError("index and expect_text go together")
        return self


class ReplaceText(Operation):
    """Replaces every match in body paragraphs and tables. A match across runs takes the first run's formatting."""

    op: Literal["replace_text"]
    find: Annotated[str, Field(min_length=1, max_length=1_000)]
    replace: Annotated[str, Field(max_length=10_000)]
    match_case: bool = True


class InsertParagraphs(_Placed):
    """Inserts paragraphs. Without a style they use the document's default paragraph style."""

    op: Literal["insert_paragraphs"]
    paragraphs: Annotated[list[WordParagraph | Text], Field(min_length=1, max_length=500)]


class SetParagraph(Operation):
    """Replaces a paragraph's text, its style, or both. New text keeps the first run's formatting."""

    op: Literal["set_paragraph"]
    index: Index
    expect_text: ExpectText
    runs: Annotated[list[RunInput], Field(min_length=1, max_length=200)] | None = None
    style: StyleName | None = None

    @model_validator(mode="after")
    def _changes_something(self) -> "SetParagraph":
        if self.runs is None and self.style is None:
            raise ValueError("set runs, style, or both")
        return self


class DeleteParagraphs(Operation):
    """Deletes count paragraphs starting at index."""

    op: Literal["delete_paragraphs"]
    index: Index
    expect_text: ExpectText
    count: Annotated[int, Field(ge=1, le=500)] = 1


class InsertTable(_Placed):
    op: Literal["insert_table"]
    rows: TableRows
    style: StyleName | None = None


class SetTableCells(Operation):
    """Writes a block of cell text from a starting cell. Extra rows copy the last row's formatting.

    A merged cell takes text at its first position; pass "" for the positions it covers.
    """

    op: Literal["set_table_cells"]
    table_index: Annotated[int, Field(ge=0, description="A table index from the read.")]
    start_row: Annotated[int, Field(ge=0)] = 0
    start_column: Annotated[int, Field(ge=0)] = 0
    values: TableRows


class AddImage(_Placed):
    """Adds an image File in its own paragraph, scaled to fit the page width."""

    op: Literal["add_image"]
    image_file_id: FileReference
    width: Points | None = None


class PageBreak(_Placed):
    op: Literal["page_break"]


class _Story(Operation):
    section: Annotated[int, Field(ge=1, description="Section number, starting at 1.")] = 1
    variant: Literal["primary", "first_page", "even_page"] = "primary"
    text: Annotated[str, Field(max_length=5_000, description="Lines become paragraphs.")]


class SetHeader(_Story):
    """Replaces a header's text. Paragraphs with images, fields, or page numbers stay."""

    op: Literal["set_header"]


class SetFooter(_Story):
    """Replaces a footer's text. Paragraphs with images, fields, or page numbers stay."""

    op: Literal["set_footer"]


class AddComment(Operation):
    """Adds a comment on a whole paragraph."""

    op: Literal["add_comment"]
    index: Index
    expect_text: ExpectText
    text: Annotated[str, Field(min_length=1, max_length=5_000)]


WordOperation = Annotated[
    ReplaceText
    | InsertParagraphs
    | SetParagraph
    | DeleteParagraphs
    | InsertTable
    | SetTableCells
    | AddImage
    | PageBreak
    | SetHeader
    | SetFooter
    | AddComment,
    Field(discriminator="op"),
]
