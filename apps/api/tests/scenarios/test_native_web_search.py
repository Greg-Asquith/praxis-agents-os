"""Search approval edits and grounded results reach the continuing agent."""

import json

import httpx2 as httpx
from pydantic_ai import DeferredToolResults, ToolApproved
from pydantic_ai.messages import ToolReturnPart

from core.settings import settings
from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL
from services.agents.runtime.approval_state import load_suspended_run_state
from tests.support.google_native import mock_google_native
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)


async def test_vertex_search_approval_edit_and_result_reach_next_model_request(
    db_session_factory, monkeypatch
):
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", None)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", "search-test")
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_LOCATION", "auto")
    query = "Giants 2026 opening game"
    answer = "The 2026 opening opponent is Dallas."
    source = {"uri": "https://example.com/schedule", "title": "Schedule"}

    def respond(request):
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"role": "model", "parts": [{"text": answer}]},
                        "finishReason": "STOP",
                        "groundingMetadata": {
                            "webSearchQueries": [query],
                            "groundingChunks": [{"web": source}],
                        },
                    }
                ],
                "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
                "modelVersion": "gemini-3.8-flash",
            },
        )

    seen = []
    async with mock_google_native(monkeypatch, respond, vertex=True) as requests:
        context = await build_scenario_agent(
            db_session_factory,
            tool_names=["web_search"],
            tool_policies={"web_search": "approval"},
        )
        model = scripted_model(
            turns=[
                ToolTurn(
                    (
                        ToolCall(
                            "web_search",
                            {"query": "Giants 2024 opening game", "model_provider": "google"},
                            "search-edit",
                        ),
                    )
                ),
                answer,
            ],
            seen_requests=seen,
        )
        suspended = await run_scenario(db_session_factory, context, model=model)
        state = load_suspended_run_state(suspended.run)
        assert requests == []
        resumed = await run_scenario(
            db_session_factory,
            context,
            model=model,
            prompt=None,
            expected_status=RUN_STATUS_AWAITING_APPROVAL,
            message_history=state.message_history,
            deferred_tool_results=DeferredToolResults(
                approvals={
                    state.pending_tool_call_ids[0]: ToolApproved(
                        override_args={
                            "query": query,
                            "model_provider": "google",
                        }
                    ),
                }
            ),
        )

    assert resumed.run.status == "completed"
    [request] = requests
    assert request.url.host == "aiplatform.eu.rep.googleapis.com"
    assert request.url.path.endswith("/models/gemini-3.8-flash:generateContent")
    assert request.headers["authorization"] == "Bearer test-adc"
    body = json.loads(request.content)
    assert body["tools"] == [{"googleSearch": {}}]
    assert query in json.dumps(body["contents"])
    assert "2024" not in json.dumps(body["contents"])
    returns = [
        part
        for message in seen[-1][0]
        for part in message.parts
        if isinstance(part, ToolReturnPart) and part.tool_name == "web_search"
    ]
    [returned] = returns
    assert returned.content["query"] == query
    assert returned.content["answer"] == answer
    assert returned.content["sources"] == [{"url": source["uri"], "title": source["title"]}]
    assert returned.content["model"] == "gemini-3.8-flash"
