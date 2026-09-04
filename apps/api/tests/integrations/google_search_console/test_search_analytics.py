# apps/api/tests/integrations/google_search_console/test_search_analytics.py

"""Search Analytics request compilation, bounds, and response typing."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai import ModelRetry
from pydantic_ai.messages import ModelRequest, ToolReturnPart

from core.exceptions.integration import IntegrationValidationError
from core.settings import settings
from integrations.google_search_console.operations.query_search_analytics import (
    MAX_SEARCH_ANALYTICS_ROWS,
    query_search_analytics,
)
from integrations.google_search_console.tools.query_search_analytics import (
    google_search_console_query_search_analytics,
)
from integrations.google_search_console.tools.schemas import (
    GoogleSearchConsoleFilter,
    GoogleSearchConsoleSearchAnalyticsInput,
)
from integrations.google_search_console.tools.utils.validation import (
    validated_search_analytics_request,
)
from services.agents.runtime.untrusted import (
    UNTRUSTED_CONTENT_START,
    UntrustedNode,
    render_untrusted_frames,
)
from services.integrations.http import IntegrationRequestPolicy

HOSTILE_QUERY = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "prompt_injection"
    / "hostile_search_console_row.txt"
).read_text(encoding="utf-8")
FIXTURE = json.loads(
    (Path(__file__).with_name("fixtures") / "search_analytics.json").read_text(encoding="utf-8")
)


class _Client:
    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def webmasters_post(self, path: str, **kwargs: Any) -> Any:
        self.calls.append((path, kwargs))
        return self.payload


async def test_query_compiles_every_argument_and_types_untrusted_rows() -> None:
    fixture_row = FIXTURE["rows"][0]
    payload = {
        **FIXTURE,
        "rows": [
            {
                **fixture_row,
                "keys": [HOSTILE_QUERY, *fixture_row["keys"][1:]],
                "clicks": 12.5,
                "impressions": 240.5,
            }
        ],
    }
    client = _Client(payload)
    request = GoogleSearchConsoleSearchAnalyticsInput(
        start_date="2026-08-01",
        end_date="2026-08-28",
        dimensions=["query", "page", "country"],
        search_type="image",
        filters=[
            GoogleSearchConsoleFilter(
                dimension="country",
                operator="equals",
                expression="gbr",
            )
        ],
        aggregation_type="byPage",
        row_limit=1,
        start_row=10,
        data_state="all",
    )

    result = await query_search_analytics(
        client,
        site_url="https://example.com/",
        request=request,
        max_rows=1_000,
    )

    path, call = client.calls[0]
    assert path == "sites/https%3A%2F%2Fexample.com%2F/searchAnalytics/query"
    assert call["operation"] == "query_search_analytics"
    assert call["policy"] is IntegrationRequestPolicy.READ
    assert call["json"] == {
        "startDate": "2026-08-01",
        "endDate": "2026-08-28",
        "dimensions": ["query", "page", "country"],
        "type": "image",
        "aggregationType": "byPage",
        "rowLimit": 1,
        "startRow": 10,
        "dataState": "all",
        "dimensionFilterGroups": [
            {
                "groupType": "and",
                "filters": [
                    {
                        "dimension": "country",
                        "operator": "equals",
                        "expression": "gbr",
                    }
                ],
            }
        ],
    }
    row = result["rows"][0]
    assert isinstance(row["keys"]["query"], UntrustedNode)
    assert isinstance(row["keys"]["page"], UntrustedNode)
    assert row["keys"]["country"] == "gbr"
    assert row["clicks"] == 12.5
    assert row["impressions"] == 240.5
    [rendered] = render_untrusted_frames(
        [
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="google_search_console_query_search_analytics",
                        content=result,
                        tool_call_id="call-search-console",
                    )
                ]
            )
        ]
    )
    framed = rendered.parts[0].content["rows"][0]["keys"]["query"]
    assert framed.count(UNTRUSTED_CONTENT_START) == 1
    assert "PRAXIS_UNTRUSTED-CONTENT" in framed
    assert result["truncated"] is True
    assert result["row_count"] == 1


async def test_query_shapes_an_empty_response_without_claiming_truncation() -> None:
    client = _Client({})
    result = await query_search_analytics(
        client,
        site_url="sc-domain:example.com",
        request=GoogleSearchConsoleSearchAnalyticsInput(
            start_date="2026-08-01",
            end_date="2026-08-28",
        ),
        max_rows=1_000,
    )
    assert result["rows"] == []
    assert result["row_count"] == 0
    assert result["truncated"] is False
    assert result["truncation_note"] is None


async def test_query_caps_the_provider_request_at_its_documented_limit() -> None:
    client = _Client({})
    await query_search_analytics(
        client,
        site_url="sc-domain:example.com",
        request=GoogleSearchConsoleSearchAnalyticsInput(
            start_date="2026-08-01",
            end_date="2026-08-28",
            row_limit=MAX_SEARCH_ANALYTICS_ROWS + 1,
        ),
        max_rows=MAX_SEARCH_ANALYTICS_ROWS + 1,
    )

    assert client.calls[0][1]["json"]["rowLimit"] == MAX_SEARCH_ANALYTICS_ROWS


def test_query_validation_handles_dates_near_python_minimum() -> None:
    request = validated_search_analytics_request(
        start_date="0001-01-01",
        end_date="0001-01-01",
        dimensions=[],
        search_type="web",
        filters=None,
        aggregation_type="auto",
        row_limit=100,
        start_row=0,
        data_state="final",
    )

    assert request.start_date == "0001-01-01"


@pytest.mark.parametrize("payload", [[], {"rows": "bad"}, {"rows": [{"keys": []}]}])
async def test_query_rejects_malformed_provider_responses(payload: Any) -> None:
    with pytest.raises(IntegrationValidationError):
        await query_search_analytics(
            _Client(payload),
            site_url="sc-domain:example.com",
            request=GoogleSearchConsoleSearchAnalyticsInput(
                start_date="2026-08-01",
                end_date="2026-08-28",
                dimensions=["query"],
            ),
            max_rows=1_000,
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"start_date": "28daysAgo"}, "YYYY-MM-DD"),
        ({"start_date": "2026-08-29"}, "on or before"),
        ({"start_date": "2025-04-27"}, "within 16 months"),
        ({"dimensions": ["query", "query"]}, "duplicate"),
        ({"dimensions": ["page"], "aggregation_type": "byProperty"}, "grouping"),
        (
            {
                "filters": [GoogleSearchConsoleFilter(dimension="page", expression="example.com")],
                "aggregation_type": "byProperty",
            },
            "filtering",
        ),
        ({"search_type": "discover", "aggregation_type": "byProperty"}, "Discover"),
        ({"row_limit": 1_001}, "1,000"),
    ],
)
async def test_query_validation_returns_actionable_model_retry(
    overrides: dict[str, Any],
    message: str,
) -> None:
    values: dict[str, Any] = {
        "start_date": "2026-08-01",
        "end_date": "2026-08-28",
    }
    values.update(overrides)
    with pytest.raises(ModelRetry, match=message):
        await google_search_console_query_search_analytics(
            _context(),
            **values,
        )


async def test_query_validation_enforces_the_provider_row_limit(monkeypatch) -> None:
    monkeypatch.setattr(settings, "INTEGRATION_REPORT_MAX_ROWS", MAX_SEARCH_ANALYTICS_ROWS + 1)

    with pytest.raises(ModelRetry, match="25,000"):
        await google_search_console_query_search_analytics(
            _context(),
            start_date="2026-08-01",
            end_date="2026-08-28",
            row_limit=MAX_SEARCH_ANALYTICS_ROWS + 1,
        )


def _context() -> Any:
    return type("Context", (), {"deps": type("Deps", (), {"active_context": None})()})()
