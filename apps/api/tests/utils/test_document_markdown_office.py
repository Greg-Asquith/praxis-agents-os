"""Conversion coverage for real modern and legacy Office files."""

from pathlib import Path

import pytest

from utils.document_markdown import convert_document_to_markdown, document_extension

FIXTURES_DIR = Path(__file__).parents[1] / "fixtures" / "files"


@pytest.mark.parametrize(
    ("filename", "content_type", "markers"),
    [
        (
            "sample.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ("Deck Title Slide", "North", "Speaker note for the intro slide"),
        ),
        (
            "sample.doc",
            "application/msword",
            ("Fixture Document", "Wide head", "Footnote after an astral character"),
        ),
        (
            "sample.xls",
            "application/vnd.ms-excel",
            ("Values", "fifteen and a half", "Merged Grid"),
        ),
    ],
)
async def test_convert_document_to_markdown_converts_office_fixture(
    filename: str,
    content_type: str,
    markers: tuple[str, ...],
) -> None:
    fixture = FIXTURES_DIR / filename
    data = fixture.read_bytes()

    assert len(data) < 100_000

    markdown = await convert_document_to_markdown(
        data,
        content_type=content_type,
        filename=filename,
        max_bytes=100_000,
    )

    assert all(marker in markdown for marker in markers)


@pytest.mark.parametrize(
    ("content_type", "expected_extension"),
    [
        ("application/vnd.ms-excel", ".xls"),
    ],
)
def test_document_extension_falls_back_to_legacy_office_content_type(
    content_type: str,
    expected_extension: str,
) -> None:
    assert document_extension("attachment", content_type=content_type) == expected_extension
