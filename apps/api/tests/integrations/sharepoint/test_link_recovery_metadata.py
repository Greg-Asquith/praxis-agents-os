"""Library selection recovery for optional provider URL metadata."""

from unittest.mock import AsyncMock
from uuid import uuid4

import httpx2
import pytest

from integrations.sharepoint.operations.link_utils import library_not_selected
from integrations.sharepoint.tools.open_link import DEFINITION, sharepoint_open_link
from integrations.sharepoint.tools.schemas import SharePointLinkOutput
from services.agents.runtime.untrusted import UntrustedNode
from tests.integrations.sharepoint.support import DOWNLOAD_URL, context, entry, file_metadata, graph

SITE = "https://example.sharepoint.com/sites/Finance"
MISSING = object()
VALID = object()


@pytest.mark.parametrize("field", ["siteUrl", "webUrl"])
@pytest.mark.parametrize(
    "value",
    [
        pytest.param(MISSING, id="missing"),
        pytest.param(None, id="null"),
        pytest.param("", id="empty"),
        pytest.param(42, id="numeric"),
        pytest.param(True, id="boolean"),
        pytest.param([], id="list"),
        pytest.param({}, id="dictionary"),
        pytest.param("PRIVATE_PROVIDER_VALUE", id="invalid-string"),
        pytest.param(VALID, id="valid-string"),
    ],
)
async def test_optional_recovery_urls_preserve_public_failure_and_audit(monkeypatch, field, value):
    item = file_metadata(
        parentReference={"driveId": "outside"},
        sharepointIds={"siteUrl": SITE},
        webUrl=SITE + "/Documents/notes.txt",
    )
    metadata = item["sharepointIds"] if field == "siteUrl" else item
    if value is MISSING:
        metadata.pop(field)
    elif value is not VALID:
        metadata[field] = value
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    ctx = context(entry())
    ctx.tool_name = DEFINITION.name
    requests = []

    def handler(request):
        requests.append(request)
        return httpx2.Response(200, json=item)

    async with graph(handler) as client:
        monkeypatch.setattr(
            "integrations.sharepoint.tools.open_link.drive_client", AsyncMock(return_value=client)
        )
        output = await sharepoint_open_link(ctx, "https://example.sharepoint.com/:w:/s/opaque")
    [result] = SharePointLinkOutput.model_validate(output).results
    assert result.status == "error"
    assert result.error_code == "library_not_selected"
    assert "Active Context" in result.error_message
    assert "Refresh discovery" in result.error_message
    assert "PRIVATE_PROVIDER_VALUE" not in result.error_message
    assert "decode" not in result.error_message
    hint = result.data.library
    assert isinstance(hint, UntrustedNode)
    assert hint.source_kind == "sharepoint_drive_item"
    assert hint.source_ref == "outside:file"
    assert hint.content == (
        "Finance / Documents" if value is VALID else "the linked site / the linked library"
    )
    assert len(hint.content) <= 160
    assert len(hint.source_ref) <= 160
    assert set(result.data.model_dump()) == {"library"}
    assert len(requests) == audit.await_count == 1
    assert audit.call_args.kwargs["status"] == "failure"
    assert audit.call_args.kwargs["error_code"] == "library_not_selected"
    assert DOWNLOAD_URL not in str((output, audit.call_args))


def test_library_recovery_bounds_valid_labels_and_fallback_provenance():
    site = "https://example.sharepoint.com/sites/" + "s" * 500
    item = file_metadata(
        id="i" * 500,
        parentReference={"driveId": "d" * 500},
        sharepointIds={"siteUrl": site},
        webUrl=site + "/" + "l" * 500 + "/notes.txt",
    )
    error = library_not_selected(item)
    assert len(error.library.content) == 160
    assert len(error.library.source_ref) == 160
    item["webUrl"] = 42
    fallback = library_not_selected(item)
    assert fallback.library.content == "the linked site / the linked library"
    assert len(fallback.library.source_ref) == 160
