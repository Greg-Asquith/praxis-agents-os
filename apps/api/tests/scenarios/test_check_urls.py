# apps/api/tests/scenarios/test_check_urls.py

"""check_urls on the shared Praxis transport, through the production runtime."""

import asyncio
import json

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.settings import settings
from services.agents.runtime.tools.web import check_urls as check_urls_tools
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)
from tests.support.web import fake_web, html_page

_SCRIPT = """
result = await check_urls(urls=[f"https://site.example/p{i}" for i in range(100)])
[
    {
        "url": row["requested_url"],
        "status": row["status"],
        "error": row["error_class"],
        "hops": row["redirects"],
    }
    for row in result["rows"]
    if row["status"] is None or row["status"] >= 400
]
"""


def _site() -> dict[str, httpx2.Response]:
    pages = {f"site.example/p{i}": html_page("<title>Page</title>") for i in range(97)}
    # p97 redirects twice to a missing page, p98 is missing, and p99 redirects to a live page.
    pages["site.example/p97"] = httpx2.Response(301, headers={"location": "/moved"})
    pages["site.example/moved"] = httpx2.Response(302, headers={"location": "/gone"})
    pages["site.example/p99"] = httpx2.Response(308, headers={"location": "/p0"})
    return pages


async def test_script_checks_a_batch_in_one_call_and_keeps_its_rows_past_the_run_budget(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(check_urls_tools, "fetch_public_url", fake_web(_site()))
    monkeypatch.setattr(settings, "WEB_FETCH_RUN_URL_BUDGET", 99)
    context = await build_scenario_agent(db_session_factory, tool_names=["check_urls"])
    seen_requests = []

    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn((ToolCall("run_code", {"code": _SCRIPT}, "audit"),)),
                ToolTurn((ToolCall("check_urls", {"urls": ["https://site.example/p0"]}, "over"),)),
                "Two URLs are broken.",
            ],
            seen_requests=seen_requests,
        ),
    )

    [script] = result.tool_returns("run_code")
    trace = script["metadata"]["code_mode_trace"]
    assert len(trace["calls"]) == 1
    assert trace["tainted"]
    # A tainted script returns its value as one untrusted node.
    broken = json.loads(script["content"]["content"])
    # The budget covers 99 URLs: the batch still returns them, and the last isn't checked.
    assert [(row["url"], row["status"], row["error"]) for row in broken] == [
        ("https://site.example/p97", 404, None),
        ("https://site.example/p98", 404, None),
        ("https://site.example/p99", None, "not_checked"),
    ]
    assert [(hop["status"], hop["location"]["content"]) for hop in broken[0]["hops"]] == [
        (301, "https://site.example/moved"),
        (302, "https://site.example/gone"),
    ]
    # The run spent its budget, so the next call is refused before any request.
    assert "limit of 99 URLs" in str(seen_requests[2][0])


async def test_urls_past_the_call_deadline_return_not_checked(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    web = fake_web({"fast.example/": html_page("<title>Fast</title>")})

    async def fetch(url: str, **kwargs):
        if "slow.example" in url:
            await asyncio.Event().wait()
        return await web(url, **kwargs)

    monkeypatch.setattr(check_urls_tools, "fetch_public_url", fetch)
    monkeypatch.setattr(settings, "WEB_FETCH_BATCH_DEADLINE_SECONDS", 0.05)
    context = await build_scenario_agent(db_session_factory, tool_names=["check_urls"])
    urls = ["https://fast.example/", "https://slow.example/"]

    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn((ToolCall("check_urls", {"urls": urls}, "c"),)),
                "One URL wasn't checked.",
            ]
        ),
    )

    [checked] = result.tool_returns("check_urls")
    fast, slow = checked["content"]["rows"]
    assert (checked["content"]["checked"], checked["content"]["not_checked"]) == (1, 1)
    assert fast["status"] == 200 and fast["final_url"]["node"] == "praxis_untrusted"
    assert slow["status"] is None and slow["error_class"] == "not_checked"
