"""Report previews bound follow-up requests while native code receives every row."""

import json
from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx2
import pytest
from pydantic import SecretStr
from pydantic_ai.messages import ModelMessagesTypeAdapter, ToolReturnPart

from core.database import set_session_tenant_context
from core.settings import settings
from integrations.google_ads.client import GoogleAdsClient
from integrations.google_ads.tools.run_report import DEFINITION
from models.files import File, FileRevision
from services.agents.runtime.structured_results import result_json
from services.agents.runtime.tools.native import run_code as run_code_tools
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.files.utils import file_revision_ref
from services.integrations.context.domain import ResolvedActiveContext
from services.storage.factory import get_storage_provider
from tests.integrations.google_ads.test_tools_and_audits import _read_entry
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
    monkeypatch.setattr(settings, "INTEGRATION_REPORT_MAX_ROWS", 1_000)
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
        for index in range(1_000)
    ]
    query = "SELECT search_term_view.search_term, metrics.clicks FROM search_term_view"
    requests = []

    def respond(request):
        requests.append(request)
        assert json.loads(request.content)["query"].startswith(query)
        return httpx2.Response(200, json=[{"results": rows}])

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
    assert preview["lists"] == {"results.0.data.rows": {"total": 1_000, "shown": 50}}
    assert preview["data"]["results"][0]["data"]["row_count"] == 1_000
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
        return f"Total clicks: {total} across 1,000 rows.", [], []

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
                            "run_code",
                            {
                                "task": "Sum clicks across every saved search-term row.",
                                "file_ids": [preview["file_reference"]],
                                "model_provider": "openai",
                            },
                        ),
                    )
                ),
                "Total clicks: 499,500.",
            ],
            seen_requests=followup_seen,
        ),
        prompt="Calculate total clicks in the saved report.",
    )
    assert followup.run.status == "completed"
    assert executions == [499_500]
    assert followup.tool_returns(DEFINITION.name)[0]["content"] == preview
    assert "499500" in str(followup.tool_returns("run_code")[0]["content"])
    assert all(
        estimate_tokens(ModelMessagesTypeAdapter.dump_json(messages).decode())
        < settings.AGENT_RUN_TOTAL_TOKENS_LIMIT
        for messages, _info in followup_seen
    )
