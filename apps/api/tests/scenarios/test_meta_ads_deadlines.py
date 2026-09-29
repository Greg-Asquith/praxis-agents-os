"""Characterises enclosing Code Mode cancellation of Meta background reports."""

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import httpx2
from pydantic_ai.messages import RetryPromptPart

from core.settings import settings
from integrations.meta_ads import throttle
from integrations.meta_ads.client import META_GRAPH_API_VERSION, MetaAdsClient
from integrations.meta_ads.settings import meta_ads_settings
from integrations.meta_ads.tools.run_insights import DEFINITION
from services.agents.runtime.code_mode.executor import MontyExecutor
from services.agents.runtime.tools.code_mode import RUN_WORKFLOW_TOOL_NAME
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.meta_ads.support import context_entry, static_token
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)


async def test_code_mode_deadline_cancels_background_report_without_partial_delivery(
    db_session_factory, monkeypatch
):
    monkeypatch.setattr(settings, "AGENT_RUN_TOTAL_TOKENS_LIMIT", 100_000)
    monkeypatch.setattr(settings, "AGENT_CODE_MODE_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(meta_ads_settings, "META_ADS_INSIGHTS_POLL_SECONDS", 10)
    monkeypatch.setattr("integrations.meta_ads.tools.run_insights._EXECUTION_SECONDS", 10)
    monkeypatch.setitem(
        RUNTIME_TOOL_CATALOG,
        DEFINITION.name,
        replace(DEFINITION, availability_check=lambda: True),
    )
    monkeypatch.setattr(
        "services.agents.runtime.execute.setup.resolve_active_context",
        AsyncMock(
            return_value=ResolvedActiveContext(entries=(context_entry("111"), context_entry("222")))
        ),
    )
    monkeypatch.setattr(throttle, "_accounts", {})
    executor = MontyExecutor.from_settings()
    monkeypatch.setattr(
        "services.agents.runtime.code_mode.bridge.get_code_mode_executor",
        AsyncMock(return_value=executor),
    )
    today = datetime.now(UTC).date().isoformat()
    requests = []
    cancelled = asyncio.Event()

    async def respond(request):
        path = request.url.path.removeprefix(f"/{META_GRAPH_API_VERSION}/")
        requests.append((request.method, path))
        if path in {"act_111/insights", "act_222/insights"}:
            if request.method == "POST":
                return httpx2.Response(
                    200, json={"report_run_id": "901" if path.startswith("act_111") else "902"}
                )
            return httpx2.Response(
                400,
                json={"error": {"code": 100, "error_subcode": 1487534, "message": "Use async"}},
            )
        if path == "901":
            return httpx2.Response(
                200, json={"async_status": "Job Completed", "async_percent_completion": 100}
            )
        if path == "901/insights":
            return httpx2.Response(
                200,
                json={"data": [{"date_start": today, "date_stop": today, "spend": "2.50"}]},
            )
        assert path == "902"
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    context = await build_scenario_agent(db_session_factory, tool_names=[DEFINITION.name])
    code = (
        f"report = await meta_ads_run_insights(fields=['spend'], since={today!r}, until={today!r})\n"
        "report"
    )
    seen = []
    try:
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:
            provider = MetaAdsClient(static_token, client=http)
            monkeypatch.setattr(
                "integrations.meta_ads.tools.run_insights.meta_ads_client",
                AsyncMock(return_value=provider),
            )
            result = await run_scenario(
                db_session_factory,
                context,
                model=scripted_model(
                    turns=[
                        ToolTurn((ToolCall(RUN_WORKFLOW_TOOL_NAME, {"code": code}),)),
                        "The workflow timed out.",
                    ],
                    seen_requests=seen,
                ),
            )
    finally:
        await executor.close()

    assert result.run.status == "completed"
    assert cancelled.is_set()
    assert requests == [
        ("GET", "act_111/insights"),
        ("POST", "act_111/insights"),
        ("GET", "901"),
        ("GET", "901/insights"),
        ("GET", "act_222/insights"),
        ("POST", "act_222/insights"),
        ("GET", "902"),
    ]
    assert result.tool_returns(RUN_WORKFLOW_TOOL_NAME) == []
    assert result.tool_returns(DEFINITION.name) == []
    retries = [
        part
        for message in seen[-1][0]
        for part in message.parts
        if isinstance(part, RetryPromptPart)
    ]
    assert len(retries) == 1
    assert retries[0].tool_name == RUN_WORKFLOW_TOOL_NAME
    assert "The sandboxed workflow failed" in str(retries[0].content)
    operations = [row for row in result.audit_rows if row.resource_type == "integration_resource"]
    assert len(operations) == 2
    by_account = {row.details["external_id"]: row for row in operations}
    assert by_account["111"].status == "success"
    assert by_account["222"].status == "failure"
    assert by_account["222"].details["error_code"] == "CancelledError"
    assert "meta-test-access-token" not in json.dumps([row.details for row in result.audit_rows])
