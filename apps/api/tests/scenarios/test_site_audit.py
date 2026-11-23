# apps/api/tests/scenarios/test_site_audit.py

"""The site audit skill's example script, run against the real web tools."""

import json
import re

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.agents.runtime.skills import load_internal_skills
from services.agents.runtime.tools.web import (
    check_urls as check_urls_tools,
    inspect_page as inspect_page_tools,
)
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)
from tests.support.web import fake_web, html_page


def _xml(body: str) -> httpx2.Response:
    return httpx2.Response(200, text=body, headers={"content-type": "application/xml"})


def _site() -> dict[str, httpx2.Response]:
    return {
        "shop.example/robots.txt": httpx2.Response(
            200,
            text="User-agent: *\nDisallow: /cart\nSitemap: https://shop.example/sitemap_index.xml\n",
            headers={"content-type": "text/plain"},
        ),
        "shop.example/sitemap_index.xml": _xml(
            '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<sitemap><loc>https://shop.example/pages.xml</loc></sitemap></sitemapindex>"
        ),
        "shop.example/pages.xml": _xml(
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + "".join(
                f"<url><loc>https://shop.example/{path}</loc></url>"
                for path in ("", "pricing", "old-sale", "blog")
            )
            + "</urlset>"
        ),
        "shop.example/": html_page("<title>Shop</title>"),
        "shop.example/pricing": html_page("<title>Pricing</title>"),
        # /blog redirects twice; /old-sale isn't served, so it answers 404.
        "shop.example/blog": httpx2.Response(301, headers={"location": "/journal"}),
        "shop.example/journal": httpx2.Response(301, headers={"location": "/journal/"}),
        "shop.example/journal/": html_page("<title>Journal</title>"),
    }


def _skill_script() -> str:
    skill = next(skill for skill in load_internal_skills() if skill.name == "site-audit")
    [script] = re.findall(r"```python\n(.*?)```", skill.instructions, re.DOTALL)
    return script


async def test_skill_script_reports_a_broken_page_and_a_redirect_chain_from_one_script(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    web = fake_web(_site())
    monkeypatch.setattr(check_urls_tools, "fetch_public_url", web)
    monkeypatch.setattr(inspect_page_tools, "fetch_public_url", web)
    context = await build_scenario_agent(
        db_session_factory, tool_names=["inspect_page", "check_urls"]
    )

    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn((ToolCall("run_code", {"code": _skill_script()}, "audit"),)),
                "One page is broken and one redirects twice.",
            ]
        ),
    )

    [script] = result.tool_returns("run_code")
    assert len(script["metadata"]["code_mode_trace"]["calls"]) == 4
    audit = json.loads(script["content"]["content"])
    assert audit["sitemap_pages"] == 4
    assert audit["not_checked"] == []
    problems = {problem["url"]: problem for problem in audit["problems"]}
    assert set(problems) == {"https://shop.example/old-sale", "https://shop.example/blog"}
    assert problems["https://shop.example/old-sale"]["status"] == 404
    assert problems["https://shop.example/blog"]["hops"] == [
        [301, "https://shop.example/journal"],
        [301, "https://shop.example/journal/"],
    ]
