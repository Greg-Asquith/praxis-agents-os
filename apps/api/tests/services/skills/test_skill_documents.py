# apps/api/tests/services/skills/test_skill_documents.py

"""Unit tests for skill document conversion and validation helpers."""

import sys
from types import SimpleNamespace

import pytest

from core.exceptions.general import AppValidationError
from core.settings import settings
from services.skills.documents.domain import SkillDocumentUploadRequest
from services.skills.documents.utils import (
    TRUNCATION_MARKER,
    convert_document_to_markdown,
    truncate_markdown,
    validate_document_upload,
)


@pytest.mark.asyncio
async def test_convert_document_to_markdown_passthrough_text_types() -> None:
    markdown = await convert_document_to_markdown(
        b"# Heading\nBody",
        content_type="text/markdown",
        filename="guide.md",
    )
    plain = await convert_document_to_markdown(
        "café".encode(),
        content_type="text/plain",
        filename="notes.txt",
    )

    assert markdown == "# Heading\nBody"
    assert plain == "café"


@pytest.mark.asyncio
async def test_convert_document_to_markdown_truncates_at_utf8_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MAX_SKILL_DOC_MARKDOWN_BYTES", 90)

    result = await convert_document_to_markdown(
        ("é" * 100).encode(),
        content_type="text/plain",
        filename="notes.txt",
    )

    assert result.endswith(TRUNCATION_MARKER)
    assert len(result.encode("utf-8")) <= 90


@pytest.mark.asyncio
async def test_convert_document_to_markdown_uses_markitdown_for_binary_docs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResult:
        text_content = "# Converted"

    class FakeMarkItDown:
        def convert_stream(self, stream, *, file_extension=None, **_kwargs):
            assert stream.read() == b"fake-pdf"
            assert file_extension == ".pdf"
            return FakeResult()

    monkeypatch.setitem(
        sys.modules,
        "markitdown",
        SimpleNamespace(MarkItDown=FakeMarkItDown),
    )

    result = await convert_document_to_markdown(
        b"fake-pdf",
        content_type="application/pdf",
        filename="guide.pdf",
    )

    assert result == "# Converted"


def test_truncate_markdown_leaves_short_content_unchanged() -> None:
    assert truncate_markdown("short", max_bytes=10) == "short"


def test_validate_document_upload_enforces_cap_and_allows_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MAX_SKILL_DOCUMENTS_PER_SKILL", 1)
    existing_manifest = {"quick_start": {"status": "ready"}}

    replacement = SkillDocumentUploadRequest(
        document_name="quick_start",
        filename="guide.md",
        content_type="text/markdown",
        size_bytes=10,
    )
    assert (
        validate_document_upload(replacement, existing_manifest=existing_manifest)
        == "text/markdown"
    )

    new_document = SkillDocumentUploadRequest(
        document_name="api_reference",
        filename="api.md",
        content_type="text/markdown",
        size_bytes=10,
    )
    with pytest.raises(AppValidationError) as exc_info:
        validate_document_upload(new_document, existing_manifest=existing_manifest)

    assert exc_info.value.field == "document_name"


def test_validate_document_upload_rejects_bad_name_and_type() -> None:
    with pytest.raises(AppValidationError) as name_error:
        validate_document_upload(
            SimpleNamespace(
                document_name="Bad Name",
                filename="guide.md",
                content_type="text/markdown",
                size_bytes=10,
            ),
            existing_manifest={},
        )
    assert name_error.value.field == "document_name"

    with pytest.raises(AppValidationError) as type_error:
        validate_document_upload(
            SimpleNamespace(
                document_name="quick_start",
                filename="guide.exe",
                content_type="application/octet-stream",
                size_bytes=10,
            ),
            existing_manifest={},
        )
    assert type_error.value.field == "content_type"
