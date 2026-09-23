"""Report previews bound follow-up requests while native code receives every row."""

import json
from dataclasses import replace
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx2
import pytest
from pydantic import SecretStr
from pydantic_ai.messages import ModelMessagesTypeAdapter, ToolReturnPart
from sqlalchemy import select

from core.database import set_session_tenant_context
from core.settings import settings
from integrations.google_ads.client import GoogleAdsClient
from integrations.google_ads.tools.run_report import DEFINITION
from models.files import File, FileRevision
from services.agents.runtime.structured_results import result_json
from services.agents.runtime.tools.code_mode import RUN_WORKFLOW_TOOL_NAME
from services.agents.runtime.tools.native import run_code as run_code_tools
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.files.utils import file_revision_ref
from services.integrations.context.domain import ResolvedActiveContext
from services.storage.factory import get_storage_provider
from tests.integrations.bigquery.test_bigquery_tools import _dry_run, _entry as bigquery_entry
from tests.integrations.google_ads.test_tools_and_audits import _read_entry
from tests.integrations.google_analytics.test_tools_and_audits import _entry as analytics_entry
from tests.integrations.google_search_console.test_tools_and_audits import _entry as search_entry
from tests.integrations.test_complete_reports import analytics_page, query_page, search_page
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    next_scenario_run,
    run_scenario,
    scripted_model,
)
from tests.support.storage import reset_storage_provider_cache
from utils.tokens import estimate_tokens


@pytest.fixture
def report_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    reset_storage_provider_cache()
    yield
    reset_storage_provider_cache()


async def test_search_term_report_retains_every_row_for_followup_code(
    db_session_factory, monkeypatch, report_storage
):
    monkeypatch.setattr(settings, "AGENT_STRUCTURED_RESULT_MAX_CHARS", 48_000)
    monkeypatch.setattr(settings, "AGENT_RESULT_PREVIEW_ROWS", 50)
    monkeypatch.setattr(settings, "AGENT_RUN_TOTAL_TOKENS_LIMIT", 100_000)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("sk-test"))
    monkeypatch.setitem(
        RUNTIME_TOOL_CATALOG,
        DEFINITION.name,
        replace(
            DEFINITION,
            availability_check=lambda: True,
            max_public_result_chars=settings.AGENT_STRUCTURED_RESULT_MAX_CHARS,
        ),
    )
    monkeypatch.setattr(
        "services.agents.runtime.execute.setup.resolve_active_context",
        AsyncMock(return_value=ResolvedActiveContext(entries=(_read_entry(),))),
    )
    rows = [
        {
            "searchTermView": {"searchTerm": f"term-{index}: " + "example search " * 30},
            "metrics": {"clicks": str(index)},
        }
        for index in range(1_500)
    ]
    query = "SELECT search_term_view.search_term, metrics.clicks FROM search_term_view"
    requests = []

    def respond(request):
        requests.append(request)
        assert json.loads(request.content)["query"] == query
        return httpx2.Response(200, json=[{"results": rows[:800]}, {"results": rows[800:]}])

    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[DEFINITION.name, "run_code"],
        tool_policies={"run_code": "auto"},
    )
    seen = []
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:
        client = GoogleAdsClient(
            AsyncMock(return_value="test-token"),
            developer_token=SecretStr("test-developer"),
            client=http,
        )
        monkeypatch.setattr(
            "integrations.google_ads.tools.run_report.google_ads_client",
            AsyncMock(return_value=client),
        )
        result = await run_scenario(
            db_session_factory,
            context,
            model=scripted_model(
                turns=[ToolTurn((ToolCall(DEFINITION.name, {"query": query}),)), "Report ready."],
                seen_requests=seen,
            ),
        )

    assert result.run.status == "completed"
    assert len(requests) == 1
    [returned] = result.tool_returns(DEFINITION.name)
    preview = returned["content"]
    assert preview["preview"] is True
    assert preview["lists"] == {"results.0.data.rows": {"total": 1_500, "shown": 50}}
    assert preview["data"]["results"][0]["data"]["row_count"] == 1_500
    assert preview["data"]["results"][0]["data"]["truncated"] is False
    assert "Read the full saved result through file_reference" in preview["hint"]
    assert "Do not repeat or split the source query" in preview["hint"]
    assert len(result_json(preview)) <= settings.AGENT_STRUCTURED_RESULT_MAX_CHARS
    assert returned["metadata"]["result_preview"] == preview
    assert "public_result" not in returned["metadata"]
    assert len(seen) == 2
    [model_return] = [
        part for message in seen[1][0] for part in message.parts if isinstance(part, ToolReturnPart)
    ]
    assert model_return.content == preview
    # Include instructions and tool definitions in the deterministic request estimate.
    messages, info = seen[1]
    report_definition = next(tool for tool in info.function_tools if tool.name == DEFINITION.name)
    assert "file_ids=[file_reference]" in report_definition.description
    assert "read_file with file_id=file_reference" in report_definition.description
    assert "tool card" not in report_definition.description
    assert "Open complete result" not in report_definition.description
    assert "no automatic row cap is added" in report_definition.description
    request_text = (
        ModelMessagesTypeAdapter.dump_json(messages).decode()
        + (info.instructions or "")
        + result_json(
            [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "schema": tool.parameters_json_schema,
                }
                for tool in info.function_tools
            ]
        )
    )
    assert estimate_tokens(request_text) < settings.AGENT_RUN_TOTAL_TOKENS_LIMIT
    assert rows[-1]["searchTermView"]["searchTerm"] not in request_text

    async with db_session_factory() as db:
        await set_session_tenant_context(
            db, workspace_id=context.workspace_id, user_id=context.user_id
        )
        file = await db.get(File, UUID(preview["file_id"]))
        assert file.is_tool_result and file.folder_id is None
        revision = await db.get(FileRevision, file.current_revision_id)
        retained = json.loads(await get_storage_provider().get_object(file_revision_ref(revision)))
    assert retained["results"][0]["data"]["rows"] == rows
    assert len(result_json(retained)) > settings.AGENT_STRUCTURED_RESULT_MAX_CHARS
    executions = []

    async def execute(*, inputs, model_spec, **kwargs):
        assert model_spec.provider == "openai"
        [source] = inputs
        assert str(source.file_id) == preview["file_id"]
        assert source.revision_id == revision.id
        assert json.loads(source.content) == retained
        total = sum(
            int(row["metrics"]["clicks"])
            for row in json.loads(source.content)["results"][0]["data"]["rows"]
        )
        executions.append(total)
        return f"Total clicks: {total} across 1,500 rows.", [], []

    monkeypatch.setattr(run_code_tools, "run_native_code_execution", execute)
    followup_seen = []
    followup = await run_scenario(
        db_session_factory,
        await next_scenario_run(db_session_factory, context),
        model=scripted_model(
            turns=[
                ToolTurn(
                    (
                        ToolCall(
                            "read_file",
                            {
                                "file_id": preview["file_reference"],
                                "offset": len(result_json(retained)) - 700,
                                "max_bytes": 700,
                            },
                        ),
                    )
                ),
                ToolTurn(
                    (
                        ToolCall(
                            "run_code",
                            {
                                "task": "Sum clicks across every saved search-term row.",
                                "file_ids": [preview["file_reference"]],
                                "model_provider": "openai",
                            },
                        ),
                    )
                ),
                "Total clicks: 1,124,250.",
            ],
            seen_requests=followup_seen,
        ),
        prompt="Inspect the final row and calculate total clicks in the saved report.",
    )
    assert followup.run.status == "completed"
    assert executions == [1_124_250]
    assert "term-1499" in str(followup.tool_returns("read_file")[0]["content"])
    assert followup.tool_returns(DEFINITION.name)[0]["content"] == preview
    assert "1124250" in str(followup.tool_returns("run_code")[0]["content"])
    assert all(
        estimate_tokens(ModelMessagesTypeAdapter.dump_json(messages).decode())
        < settings.AGENT_RUN_TOTAL_TOKENS_LIMIT
        for messages, _info in followup_seen
    )


@pytest.mark.parametrize(
    "provider,operation",
    [
        ("google_ads", "list_report_fields"),
        ("google_analytics", "run_report"),
        ("google_analytics", "run_realtime_report"),
        ("google_analytics", "list_report_fields"),
        ("google_search_console", "query_search_analytics"),
        ("bigquery", "run_query"),
    ],
)
async def test_provider_reports_save_complete_data_before_previewing(
    db_session_factory, monkeypatch, report_storage, provider, operation
):
    monkeypatch.setattr(settings, "AGENT_STRUCTURED_RESULT_MAX_CHARS", 12_000)
    monkeypatch.setattr(settings, "AGENT_RESULT_PREVIEW_ROWS", 50)
    monkeypatch.setattr(settings, "AGENT_RUN_TOTAL_TOKENS_LIMIT", 100_000)
    module = import_module(f"integrations.{provider}.tools.{operation}")
    definition = replace(
        module.DEFINITION, availability_check=lambda: True, max_public_result_chars=12_000
    )
    monkeypatch.setitem(RUNTIME_TOOL_CATALOG, definition.name, definition)
    if provider == "google_ads":
        entry = _read_entry()
        args = {"resource": "campaign"}
        client = SimpleNamespace(
            get=AsyncMock(
                return_value={
                    "name": "campaign",
                    "category": "RESOURCE",
                    "dataType": "MESSAGE",
                    "metrics": [f"metrics.value_{index:04}" for index in range(1500)],
                    "segments": [f"segments.value_{index:04}" for index in range(1500)],
                    "attributeResources": [f"resource_{index:04}" for index in range(1500)],
                }
            ),
            post=AsyncMock(
                return_value={
                    "results": [
                        {
                            "name": f"campaign.field_{index:04}",
                            "category": "ATTRIBUTE",
                            "dataType": "STRING",
                        }
                        for index in range(1500)
                    ]
                }
            ),
        )
        monkeypatch.setattr(module, "google_ads_client", AsyncMock(return_value=client))
    elif provider == "google_analytics":
        entry = analytics_entry("123")
        args = {"metrics": ["activeUsers"], "dimensions": ["country"]}
        payload = analytics_page(0, 1500, 1500)
        if operation == "run_report":
            args["date_ranges"] = [{"start_date": "28daysAgo", "end_date": "yesterday"}]
        elif operation == "list_report_fields":
            args = {}
            fields = [
                {"apiName": f"field{index}", "description": "Report field " * 20}
                for index in range(1500)
            ]
            payload = {"dimensions": fields, "metrics": fields}
        client = SimpleNamespace(
            data_post=AsyncMock(return_value=payload), data_get=AsyncMock(return_value=payload)
        )
        monkeypatch.setattr(module, "google_analytics_client", AsyncMock(return_value=client))
    elif provider == "google_search_console":
        entry = search_entry("sc-domain:example.com")
        args = {"start_date": "2026-08-01", "end_date": "2026-08-28", "dimensions": ["country"]}
        client = SimpleNamespace(webmasters_post=AsyncMock(return_value=search_page(0, 1500)))
        monkeypatch.setattr(module, "google_search_console_client", AsyncMock(return_value=client))
    else:
        entry = bigquery_entry()
        args = {"query": "SELECT * FROM `analytics.marketing.campaign_daily`"}
        client = SimpleNamespace(post=AsyncMock(side_effect=[_dry_run(), query_page(0, 1500)]))
        monkeypatch.setattr(
            module, "bigquery_query_client", AsyncMock(return_value=(client, "analytics"))
        )
    monkeypatch.setattr(
        "services.agents.runtime.execute.setup.resolve_active_context",
        AsyncMock(return_value=ResolvedActiveContext(entries=(entry,))),
    )
    context = await build_scenario_agent(db_session_factory, tool_names=[definition.name])
    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(turns=[ToolTurn((ToolCall(definition.name, args),)), "Report ready."]),
    )
    assert result.run.status == "completed"
    [returned] = result.tool_returns(definition.name)
    preview = returned["content"]
    assert preview["preview"] is True
    assert all(
        count["total"] == 1500 and count["shown"] <= 50 for count in preview["lists"].values()
    )
    async with db_session_factory() as db:
        await set_session_tenant_context(
            db, workspace_id=context.workspace_id, user_id=context.user_id
        )
        file = await db.get(File, UUID(preview["file_id"]))
        revision = await db.get(FileRevision, file.current_revision_id)
        saved = await get_storage_provider().get_object(file_revision_ref(revision))
    full = json.loads(saved)
    data = full if provider in {"bigquery", "google_ads"} else full["results"][0]["data"]
    lists = ("dimensions", "metrics") if operation == "list_report_fields" else ("rows",)
    if provider == "google_ads":
        lists = ("fields", "metrics", "segments", "attribute_resources")
    assert all(len(data[key]) == 1500 for key in lists)
    followup = await run_scenario(
        db_session_factory,
        await next_scenario_run(db_session_factory, context),
        model=scripted_model(
            turns=[
                ToolTurn(
                    (
                        ToolCall(
                            "read_file",
                            {
                                "file_id": preview["file_reference"],
                                "offset": len(saved) - 1000,
                                "max_bytes": 1000,
                            },
                        ),
                    )
                ),
                "Final rows inspected.",
            ]
        ),
        prompt="Inspect the end of the saved report.",
    )
    assert followup.run.status == "completed"
    assert "1499" in str(followup.tool_returns("read_file")[0]["content"])


@pytest.mark.parametrize("nested", [False, True])
async def test_combined_report_limit_fails_direct_and_nested_calls_without_partial_results(
    db_session_factory, monkeypatch, report_storage, nested
):
    monkeypatch.setattr(settings, "MAX_FILE_SIZE_AGENT_FILE", 3_000)
    monkeypatch.setattr(settings, "AGENT_RUN_TOTAL_TOKENS_LIMIT", 100_000)
    monkeypatch.setitem(
        RUNTIME_TOOL_CATALOG, DEFINITION.name, replace(DEFINITION, availability_check=lambda: True)
    )
    monkeypatch.setattr(
        "services.agents.runtime.execute.setup.resolve_active_context",
        AsyncMock(
            return_value=ResolvedActiveContext(
                entries=tuple(_read_entry(str(index)) for index in (111, 222, 333))
            )
        ),
    )
    query = "SELECT campaign.name FROM campaign"
    marker = "complete-report-row-"
    requests = []

    def respond(request):
        requests.append(request)
        return httpx2.Response(
            200, json=[{"results": [{"campaign": {"name": marker + "x" * 1_800}}]}]
        )

    context = await build_scenario_agent(
        db_session_factory, tool_names=[DEFINITION.name], code_mode_enabled=nested
    )
    call = (
        ToolCall(RUN_WORKFLOW_TOOL_NAME, {"code": f"await google_ads_run_report(query={query!r})"})
        if nested
        else ToolCall(DEFINITION.name, {"query": query})
    )
    seen = []
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:
        client = GoogleAdsClient(
            AsyncMock(return_value="test-token"), developer_token=SecretStr("test"), client=http
        )
        monkeypatch.setattr(
            "integrations.google_ads.tools.run_report.google_ads_client",
            AsyncMock(return_value=client),
        )
        result = await run_scenario(
            db_session_factory,
            context,
            model=scripted_model(
                turns=[ToolTurn((call,)), "The combined report exceeds the file size limit."],
                seen_requests=seen,
            ),
        )

    assert result.run.status == "completed"
    assert [request.url.path.split("/")[3] for request in requests] == ["111", "222"]
    history = ModelMessagesTypeAdapter.dump_json(seen[-1][0]).decode()
    assert "No partial report was returned" in history
    assert marker not in history
    assert any(
        row.tool_name == DEFINITION.name
        and row.details.get("error_code") == "IntegrationReportTooLargeError"
        for row in result.audit_rows
    )
    async with db_session_factory() as db:
        await set_session_tenant_context(
            db, workspace_id=context.workspace_id, user_id=context.user_id
        )
        assert not (await db.execute(select(File.id).where(File.is_tool_result.is_(True)))).all()
