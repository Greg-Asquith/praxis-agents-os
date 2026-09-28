"""Required file citations and optional listing metadata."""

import logging
import traceback
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx2
import pytest

from core.exceptions.integration import IntegrationValidationError
from integrations.sharepoint.operations.download_item import download_item
from integrations.sharepoint.references import SharePointDriveItemReference
from integrations.sharepoint.tools.read_file import sharepoint_read_file
from integrations.sharepoint.tools.schemas import SharePointFileOutput
from tests.integrations.sharepoint.support import context, entry, file_metadata, graph


@pytest.mark.parametrize(
    "citation",
    [
        None,
        "javascript:PRIVATE_CITATION_SECRET",
        "https://PRIVATE_CITATION_SECRET@example.com/notes.txt",
    ],
)
@pytest.mark.parametrize("operation", ["read_file", "find_in_file"])
async def test_unusable_citation_fails_before_download(monkeypatch, citation, caplog, operation):
    caplog.set_level(logging.DEBUG)
    async with graph(lambda _: httpx2.Response(200, json=file_metadata(webUrl=citation))) as client:
        download = AsyncMock(return_value=b"notes")
        monkeypatch.setattr(client, "get_bytes", download)
        with pytest.raises(IntegrationValidationError) as caught:
            await download_item(client, drive_id="drive", item_id="file", operation=operation)
        download.assert_not_awaited()
    assert caught.value.operation == operation
    assert caught.value.original_error is None
    evidence = "".join(traceback.format_exception(caught.value)) + caplog.text
    assert "PRIVATE_CITATION_SECRET" not in evidence
    assert "PRIVATE_DOWNLOAD_SECRET" not in evidence


async def test_rejected_citation_is_absent_from_public_failure_and_audit(monkeypatch, caplog):
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    citation = "https://PRIVATE_CITATION_SECRET@example.com/notes.txt"
    async with graph(lambda _: httpx2.Response(200, json=file_metadata(webUrl=citation))) as client:
        download = AsyncMock(return_value=b"notes")
        monkeypatch.setattr(client, "get_bytes", download)
        monkeypatch.setattr(
            "integrations.sharepoint.tools.read_file.drive_client", AsyncMock(return_value=client)
        )
        ctx = context(entry())
        ctx.tool_name = "sharepoint_read_file"
        result = await sharepoint_read_file(
            ctx, SharePointDriveItemReference(drive_id="drive", item_id="file")
        )
        download.assert_not_awaited()
    typed = SharePointFileOutput.model_validate(result)
    assert typed.results[0].status == "error"
    assert audit.await_count == 1
    assert audit.call_args.kwargs["external_ref"] is None
    evidence = typed.model_dump_json() + str(audit.call_args) + caplog.text
    assert "PRIVATE_CITATION_SECRET" not in evidence
    assert "PRIVATE_DOWNLOAD_SECRET" not in evidence
