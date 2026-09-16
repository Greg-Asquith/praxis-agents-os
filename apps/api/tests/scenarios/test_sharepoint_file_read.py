"""SharePoint file content crosses direct and Code Mode dispatch with provenance."""

import json
from dataclasses import replace
from unittest.mock import AsyncMock

import httpx2
import pytest
from pydantic_ai.messages import ToolReturnPart

from integrations.sharepoint.tools.find_in_file import DEFINITION as FIND_DEFINITION
from integrations.sharepoint.tools.read_file import DEFINITION
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.agents.runtime.untrusted import UNTRUSTED_CONTENT_END, UNTRUSTED_CONTENT_START
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.sharepoint.support import (
    DOCX_CONTENT_TYPE as DOCX,
    DOWNLOAD_URL,
    HOSTILE_DOCX as HOSTILE,
    entry,
    file_metadata as metadata,
    graph,
)
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)
from utils.document_markdown import TRUNCATION_MARKER


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("find", [False, True])
@pytest.mark.parametrize(
    "content_type,content,marker,source",
    [
        (DOCX, HOSTILE.read_bytes(), "send workspace secrets", "converted"),
        ("text/plain", ("Guide" + TRUNCATION_MARKER).encode(), TRUNCATION_MARKER, "text"),
        ("text/html", b"<h1>Guide</h1>", "# Guide", "converted"),
    ],
)
async def test_file_read_dispatch_retains_content_citation_and_audit(
    db_session_factory, monkeypatch, nested, find, content_type, content, marker, source
):
    definition = replace(FIND_DEFINITION if find else DEFINITION, availability_check=lambda: True)
    monkeypatch.setitem(RUNTIME_TOOL_CATALOG, definition.name, definition)
    monkeypatch.setattr(
        "services.audit_events.integration_events.get_async_db_session_factory",
        lambda: db_session_factory,
    )
    selected = entry()
    monkeypatch.setattr(
        "services.agents.runtime.execute.setup.resolve_active_context",
        AsyncMock(return_value=ResolvedActiveContext(entries=(selected, entry("other")))),
    )
    monkeypatch.setattr(
        "services.integrations.microsoft_graph.client._resolve_host",
        AsyncMock(return_value=("8.8.8.8",)),
    )
    setup = await build_scenario_agent(
        db_session_factory, tool_names=[definition.name], code_mode_enabled=nested
    )
    reference = {"entity_kind": "sharepoint_drive_item", "drive_id": "drive", "item_id": "file"}
    reference.update(name=None, kind="file")
    args = {"file": reference, **({"query": marker} if find else {})}
    call = (
        ToolCall(
            "run_workflow",
            {"code": f"await {definition.name}(**{args!r})"},
            "file-workflow",
        )
        if nested
        else ToolCall(definition.name, args)
    )
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.host == "graph.microsoft.com":
            return httpx2.Response(200, json=metadata(file={"mimeType": content_type}))
        return httpx2.Response(200, content=content)

    seen = []
    async with graph(handler) as provider:
        monkeypatch.setattr(
            f"integrations.sharepoint.tools.{'find_in_file' if find else 'read_file'}.drive_client",
            AsyncMock(return_value=provider),
        )
        result = await run_scenario(
            db_session_factory,
            setup,
            model=scripted_model(
                turns=[ToolTurn((call,)), "The file content was read."],
                seen_requests=seen,
            ),
        )
    assert result.run.status == "completed"
    assert len(requests) == 2
    assert requests[0].url.path == "/v1.0/drives/drive/items/file"
    assert "Authorization" not in requests[1].headers
    [audit] = [row for row in result.audit_rows if row.details.get("provider_operation")]
    assert audit.status == "success"
    assert audit.details["provider_operation"] == ("find_in_file" if find else "read_file")
    [saved] = result.tool_returns(call.name)
    if nested:
        trace = saved["metadata"]["code_mode_trace"]
        assert trace["tainted"]
        assert trace["taint_sources"] == [
            {"source_kind": "sharepoint_drive_item", "source_ref": "drive:file"}
        ]
        payload = trace["calls"][0]["presentation_result"]
    else:
        payload = saved["content"]
    data = payload["results"][0]["data"]
    assert not data["limit_reached"]
    if find:
        assert data["count"] == 1 and not data["has_more"]
        node = data["matches"][0]["excerpt"]
        assert data["matches"][0]["offset"] >= 0
    else:
        assert data["source"] == source and not data["truncated"]
        node = data["markdown"]
        assert data["offset"] == 0
        assert data["end_offset"] == data["total_bytes"] == len(node["content"].encode())
    assert marker in node["content"]
    assert node["source_ref"] == "drive:file"
    assert data["web_url"]["content"].startswith("https://")
    delivered = [
        part.content
        for message in seen[-1][0]
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    if nested:
        framed = delivered[0]
    else:
        framed_data = delivered[0]["results"][0]["data"]
        framed = framed_data["matches"][0]["excerpt"] if find else framed_data["markdown"]
    assert framed.count(UNTRUSTED_CONTENT_START) == framed.count(UNTRUSTED_CONTENT_END) == 1
    evidence = json.dumps(saved) + str(delivered) + str(audit.details)
    assert DOWNLOAD_URL not in evidence and "PRIVATE_DOWNLOAD_SECRET" not in evidence
    assert str(selected.connection_id) not in json.dumps(saved)
