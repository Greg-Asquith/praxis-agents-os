# apps/api/tests/scenarios/test_measure_page_speed.py

"""measure_page_speed on a canned PageSpeed Insights response, through the production runtime."""

import asyncio
import json

import httpx2
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.settings import settings
from services.agents.runtime.tools.web import measure_page_speed as page_speed_tools
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)
from tests.support.web import fake_page_speed, page_speed_response

_SCRIPT = """
import json

result = await measure_page_speed(urls=[f"https://shop.example/p{i}" for i in range(50)])
tested = [row for row in result["rows"] if row["lab"]]
slowest = sorted(tested, key=lambda row: row["lab"]["lcp_ms"], reverse=True)[:5]
report = slowest[0]["report"]
read = await read_file(
    file_id=result["report_file"], offset=report["offset"], max_bytes=report["length"]
)
{
    "slowest": [row["requested_url"] for row in slowest],
    "summary_chars": len(json.dumps(result)),
    "origins": list(result["origins"]),
    "report": read["content"],
}
"""


def _respond(request: httpx2.Request) -> httpx2.Response:
    url = request.url.params["url"]
    response = page_speed_response(url)
    # Each page is 100 ms slower than the one before it.
    page = int(url.rsplit("p", 1)[1])
    response["lighthouseResult"]["audits"]["largest-contentful-paint"]["numericValue"] = (
        1_000 + page * 100
    )
    return httpx2.Response(200, json=response)


@pytest.fixture(autouse=True)
def _pagespeed_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "PAGESPEED_API_KEY", SecretStr("test-key"))


async def test_script_tests_fifty_pages_and_reads_one_report_by_its_range(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(page_speed_tools, "run_page_speed_test", fake_page_speed(_respond))
    monkeypatch.setattr(settings, "PAGESPEED_RUN_BUDGET", 50)
    context = await build_scenario_agent(db_session_factory, tool_names=["measure_page_speed"])
    seen_requests = []
    again = {"urls": ["https://shop.example/p0"]}

    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn((ToolCall("run_code", {"code": _SCRIPT}, "speed"),)),
                ToolTurn((ToolCall("measure_page_speed", again, "over"),)),
                "The five slowest pages are listed.",
            ],
            seen_requests=seen_requests,
        ),
    )

    [script] = result.tool_returns("run_code")
    trace = script["metadata"]["code_mode_trace"]
    assert [call["tool_name"] for call in trace["calls"]] == ["measure_page_speed", "read_file"]
    assert trace["tainted"]
    value = json.loads(script["content"]["content"])
    assert value["slowest"] == [f"https://shop.example/p{page}" for page in range(49, 44, -1)]
    assert value["summary_chars"] < 40_000
    assert value["origins"] == ["https://shop.example"]
    # The report comes back from the saved File as an untrusted node, hostile snippet included.
    report = value["report"]
    assert report["node"] == "praxis_untrusted"
    page = json.loads(report["content"])
    assert page["requested_url"] == "https://shop.example/p49"
    assert page["failed_audits"][0]["id"] == "render-blocking-resources"
    assert "Ignore previous instructions" in page["lcp_element"]["snippet"]
    # The run spent its budget, so the next call is refused before any test.
    assert "limit of 50 page speed tests" in str(seen_requests[2][0])


async def test_pages_past_the_call_deadline_return_not_checked(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = fake_page_speed(_respond)

    async def slow_or_canned(url: str, **kwargs):
        if url.endswith("p1"):
            await asyncio.Event().wait()
        return await run(url, **kwargs)

    monkeypatch.setattr(page_speed_tools, "run_page_speed_test", slow_or_canned)
    monkeypatch.setattr(settings, "PAGESPEED_BATCH_DEADLINE_SECONDS", 0.2)
    context = await build_scenario_agent(db_session_factory, tool_names=["measure_page_speed"])
    urls = ["https://shop.example/p0", "https://shop.example/p1"]

    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn((ToolCall("measure_page_speed", {"urls": urls}, "m"),)),
                "One page wasn't tested.",
            ]
        ),
    )

    [measured] = result.tool_returns("measure_page_speed")
    content = measured["content"]
    tested, untested = content["rows"]
    assert (content["tested"], content["not_checked"]) == (1, 1)
    assert tested["scores"] == {"performance": 48} and tested["report"]["offset"] == 2
    assert content["report_file"]["entity_kind"] == "file"
    assert untested["error_class"] == "not_checked" and untested["report"] is None
