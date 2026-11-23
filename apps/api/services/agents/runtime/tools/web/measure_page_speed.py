# apps/api/services/agents/runtime/tools/web/measure_page_speed.py

"""Scores page speed and Core Web Vitals with Google PageSpeed Insights on the deploy's key.

Each page returns a short summary row. Every tested page's reduced report goes into one
internal File, and each row names its byte range, so the agent and the card read the same
test without running it again.
"""

import asyncio
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field
from pydantic_ai import ModelRetry, RunContext

from core.exceptions.general import AppValidationError
from core.settings import settings
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.entity_references.domain import FileReference
from services.agents.runtime.tools import (
    TOOL_EGRESS_ARBITRARY_URL,
    TOOL_POLICY_AUTO,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.agents.runtime.tools.registry import runtime_tool
from services.agents.runtime.tools.web.nodes import untrusted
from services.agents.runtime.untrusted import UntrustedNode
from services.files.save_tool_result import save_tool_result
from services.web.page_speed import (
    PageSpeedCategory,
    PageSpeedError,
    PageSpeedErrorClass,
    PageSpeedStrategy,
    PageSpeedTest,
    Rating,
    report_json,
    run_page_speed_test,
    url_origin,
)
from services.web.utils import configured_blocked_domains

TOOL_NAME = "measure_page_speed"
# Well inside Google's per-minute quota; one test takes 10 to 40 seconds.
_PARALLEL_TESTS = 10

RowError = PageSpeedErrorClass | Literal["not_checked"]


class Scores(BaseModel):
    performance: int | None = None
    accessibility: int | None = None
    best_practices: int | None = None
    seo: int | None = None


class LabMetrics(BaseModel):
    lcp_ms: int | None
    cls: float | None
    tbt_ms: int | None
    fcp_ms: int | None
    speed_index_ms: int | None


class FieldMetric(BaseModel):
    p75: float = Field(description="The 75th percentile over the last 28 days of real visits.")
    rating: Rating | None


class FieldData(BaseModel):
    lcp_ms: FieldMetric | None = None
    inp_ms: FieldMetric | None = None
    cls: FieldMetric | None = None
    ttfb_ms: FieldMetric | None = None
    core_web_vitals: Literal["passed", "failed"] | None


class TopIssue(BaseModel):
    audit: str = Field(description="A Lighthouse audit ID.")
    saving_ms: int
    saving_bytes: int


class ReportRange(BaseModel):
    offset: int
    length: int


class PageSpeedRow(BaseModel):
    requested_url: str
    final_url: UntrustedNode | None = Field(
        description="The tested URL after redirects; null when unchanged or the test failed."
    )
    scores: Scores
    lab: LabMetrics | None
    field: FieldData | None = Field(
        description="Real-visit data for this page, when Google has it."
    )
    top_issues: list[TopIssue]
    report: ReportRange | None = Field(
        description="Where this page's report is in report_file: read_file offset and max_bytes."
    )
    error_class: RowError | None


class MeasurePageSpeedOutput(BaseModel):
    """Model-visible result returned by `measure_page_speed`."""

    strategy: PageSpeedStrategy
    categories: list[PageSpeedCategory]
    tested_at: str
    tested: int
    not_checked: int
    budget_remaining: int = Field(description="Tests this run can still start.")
    report_file: FileReference | None
    origins: dict[str, FieldData] = Field(
        description="Real-visit data for each requested origin, such as https://example.com."
    )
    rows: list[PageSpeedRow]


@runtime_tool(
    name=TOOL_NAME,
    provider="web",
    label="Measure Page Speed",
    code_eligible=True,
    description=(
        f"Score up to {settings.PAGESPEED_MAX_URLS_PER_CALL} public pages with Google PageSpeed "
        "Insights: category scores (0 to 100), lab metrics (LCP, CLS, TBT, FCP, Speed Index), "
        "real-visit Core Web Vitals for each page and its origin (LCP, INP, CLS, and TTFB at "
        "the 75th percentile, rated, or null when Google has no data), and the three audits "
        "with the largest estimated saving. Each test takes 10 to 40 seconds, so test key "
        "pages (the home page, top landing pages, one page per template), never a whole "
        "sitemap. strategy is mobile (default) or desktop; test both with two calls. Pages "
        "the call has no time or run budget left for return error_class='not_checked': send "
        "them again while budget_remaining is above 0. Only for a page the task depends on, "
        "read its full report (failed audits with their resources and elements, the LCP "
        "element, third parties) with read_file on report_file, offset=report.offset, and "
        "max_bytes=report.length. Never test the same page again to see its detail."
    ),
    supports_approval=True,
    supports_auto=True,
    default_policy=TOOL_POLICY_AUTO,
    egress=TOOL_EGRESS_ARBITRARY_URL,
    takes_ctx=True,
    timeout=None,
    output_model=MeasurePageSpeedOutput,
    preview_list_path="rows",
    availability_check=lambda: settings.PAGESPEED_API_KEY is not None,
    presentation=ToolPresentation(
        icon="chart",
        running_label="Measuring Page Speed",
        completed_label="Measured Page Speed",
        failed_label="Couldn't Measure Page Speed",
        approval_title="Measure Page Speed",
        approval_prompt="The agent wants Google PageSpeed Insights to test these pages.",
        approve_label="Approve & Test",
        arg_fields=(
            ToolFieldPresentation(key="urls", label="Pages", format="list", editable=True),
            ToolFieldPresentation(key="strategy", label="Device"),
            ToolFieldPresentation(key="categories", label="Categories", secondary=True),
        ),
    ),
)
async def measure_page_speed(
    ctx: RunContext[RuntimeDeps],
    urls: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=2_048)]],
        Field(
            min_length=1,
            max_length=settings.PAGESPEED_MAX_URLS_PER_CALL,
            description="HTTP(S) page URLs. Duplicates are tested once.",
        ),
    ],
    strategy: Annotated[
        PageSpeedStrategy, Field(description="mobile (default) or desktop.")
    ] = "mobile",
    categories: Annotated[
        list[PageSpeedCategory] | None,
        Field(
            min_length=1,
            description=(
                "Any of performance, accessibility, best_practices, and seo. Omit for performance."
            ),
        ),
    ] = None,
) -> dict[str, Any]:
    """Tests each page once, ten at a time, within one deadline."""
    if settings.PAGESPEED_API_KEY is None:
        raise ModelRetry("Page speed testing isn't set up on this deploy.")
    unique = list(dict.fromkeys(urls))
    chosen: list[PageSpeedCategory] = list(dict.fromkeys(categories or ["performance"]))
    budget = ctx.deps.page_speed_budget
    if budget.remaining < 1:
        raise ModelRetry(f"This run has started its limit of {budget.max_urls} page speed tests.")
    # A partial batch still returns its rows, so a script doesn't lose the work it has done.
    batch, over_budget = unique[: budget.remaining], unique[budget.remaining :]
    budget.take(len(batch))
    outcomes = await _test_all(
        batch,
        api_key=settings.PAGESPEED_API_KEY.get_secret_value(),
        strategy=strategy,
        categories=chosen,
    )
    outcomes += ["not_checked"] * len(over_budget)
    tested = {
        url: outcome
        for url, outcome in zip(unique, outcomes, strict=True)
        if isinstance(outcome, PageSpeedTest)
    }
    report_file, ranges = await _save_reports(ctx, tested)
    rows = [
        _row(url, outcome, ranges.get(url))
        if isinstance(outcome, PageSpeedTest)
        else _failed_row(url, outcome)
        for url, outcome in zip(unique, outcomes, strict=True)
    ]
    return {
        "strategy": strategy,
        "categories": chosen,
        "tested_at": datetime.now(UTC).isoformat(),
        "tested": len(tested),
        "not_checked": sum(1 for outcome in outcomes if outcome == "not_checked"),
        "budget_remaining": budget.remaining,
        "report_file": report_file,
        "origins": _origins(unique, outcomes),
        "rows": rows,
    }


async def _test_all(
    urls: list[str],
    *,
    api_key: str,
    strategy: PageSpeedStrategy,
    categories: list[PageSpeedCategory],
) -> list[PageSpeedTest | RowError]:
    blocked_domains = configured_blocked_domains()
    slots = asyncio.Semaphore(_PARALLEL_TESTS)

    async def test(url: str) -> PageSpeedTest | RowError:
        async with slots:
            try:
                return await run_page_speed_test(
                    url,
                    strategy=strategy,
                    categories=categories,
                    api_key=api_key,
                    timeout_seconds=settings.PAGESPEED_TIMEOUT_SECONDS,
                    blocked_domains=blocked_domains,
                )
            except PageSpeedError as exc:
                return exc.error_class

    tasks = [asyncio.create_task(test(url)) for url in urls]
    try:
        _, pending = await asyncio.wait(tasks, timeout=settings.PAGESPEED_BATCH_DEADLINE_SECONDS)
    finally:
        # Also runs when the run itself is cancelled, so no test outlives the call.
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return ["not_checked" if task in pending else task.result() for task in tasks]


async def _save_reports(
    ctx: RunContext[RuntimeDeps], tests: dict[str, PageSpeedTest]
) -> tuple[dict[str, Any] | None, dict[str, dict[str, int]]]:
    """Saves every report as one JSON array with a page per line, returning each byte range."""
    if not tests:
        return None, {}
    lines = {url: report_json(test.report) for url, test in tests.items()}
    ranges: dict[str, dict[str, int]] = {}
    offset = len("[\n")
    for url, line in lines.items():
        ranges[url] = {"offset": offset, "length": len(line)}
        offset += len(line) + len(",\n")
    content = "[\n" + ",\n".join(lines.values()) + "\n]\n"
    name = f"{TOOL_NAME}-{datetime.now(UTC):%Y%m%dT%H%M%S%f}.json"
    try:
        # A report that can't be saved rolls back alone, and the summary rows still return.
        async with ctx.deps.db.begin_nested():
            saved = await save_tool_result(
                ctx.deps,
                tool_name=TOOL_NAME,
                tool_call_id=ctx.tool_call_id or TOOL_NAME,
                name=name,
                content=content.encode("ascii"),
            )
    except AppValidationError:
        return None, {}
    reference = FileReference(entity_id=saved.file.id, label=saved.file.name)
    return reference.model_dump(mode="json"), ranges


def _origins(urls: list[str], outcomes: list[PageSpeedTest | RowError]) -> dict[str, Any]:
    origins: dict[str, Any] = {}
    for url, outcome in zip(urls, outcomes, strict=True):
        if isinstance(outcome, PageSpeedTest) and outcome.origin_field is not None:
            origins.setdefault(url_origin(url), outcome.origin_field)
    return origins


def _row(url: str, test: PageSpeedTest, report: dict[str, int] | None) -> dict[str, Any]:
    summary = test.summary
    final_url = summary["final_url"]
    return {
        **summary,
        "final_url": untrusted(url, final_url) if final_url else None,
        "report": report,
        "error_class": None,
    }


def _failed_row(url: str, error_class: RowError) -> dict[str, Any]:
    return {
        "requested_url": url,
        "final_url": None,
        "scores": {},
        "lab": None,
        "field": None,
        "top_issues": [],
        "report": None,
        "error_class": error_class,
    }
