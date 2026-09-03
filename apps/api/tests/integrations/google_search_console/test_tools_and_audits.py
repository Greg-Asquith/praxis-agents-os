# apps/api/tests/integrations/google_search_console/test_tools_and_audits.py

"""Search Console tool fan-out and audit behavior."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from integrations.google_search_console.tools.list_sitemaps import (
    google_search_console_list_sitemaps,
)
from integrations.google_search_console.tools.query_search_analytics import (
    google_search_console_query_search_analytics,
)
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry


def _entry(external_id: str) -> ResolvedContextEntry:
    return ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="google_search_console",
        resource_type="google_search_console_site",
        external_id=external_id,
        display_name=external_id,
        connection_id=uuid4(),
        connection_label="Search Console",
        connection_status="active",
        write_allowed=False,
    )


def _ctx(*entries: ResolvedContextEntry, tool_name: str) -> SimpleNamespace:
    return SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=entries),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4(), name="Search Agent"),
            run=SimpleNamespace(id=uuid4(), user_id=uuid4()),
        ),
        tool_name=tool_name,
        tool_call_id="call-search-console",
    )


async def test_search_analytics_fans_out_with_counts_only_audit(monkeypatch) -> None:
    entry = _entry("sc-domain:example.com")
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )
    monkeypatch.setattr(
        "integrations.google_search_console.tools.query_search_analytics.google_search_console_client",
        lambda _ctx, _entry: _async_value("client"),
    )
    monkeypatch.setattr(
        "integrations.google_search_console.tools.query_search_analytics.query_search_analytics",
        AsyncMock(
            return_value={
                "rows": [],
                "row_count": 0,
                "truncated": False,
                "truncation_note": None,
                "response_aggregation_type": "auto",
                "start_date": "2026-08-01",
                "end_date": "2026-08-28",
                "search_type": "web",
            }
        ),
    )

    result = await google_search_console_query_search_analytics(
        _ctx(entry, tool_name="google_search_console_query_search_analytics"),
        start_date="2026-08-01",
        end_date="2026-08-28",
        dimensions=["query"],
        filters=None,
    )

    assert result["results"][0]["status"] == "success"
    assert str(entry.connection_id) not in str(result)
    detail = audit.await_args.kwargs["operation_detail"].model_dump(mode="json")
    fields = detail["intent_groups"][0]["items"][0]["fields"]
    assert fields == {
        "start_date": "2026-08-01",
        "end_date": "2026-08-28",
        "dimensions": ["query"],
        "search_type": "web",
        "filter_count": 0,
        "row_count": 0,
    }
    assert "rows" not in str(detail)


async def test_sitemaps_fans_out_with_count_only_audit(monkeypatch) -> None:
    entry = _entry("https://example.com/")
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )
    monkeypatch.setattr(
        "integrations.google_search_console.tools.list_sitemaps.google_search_console_client",
        lambda _ctx, _entry: _async_value("client"),
    )
    monkeypatch.setattr(
        "integrations.google_search_console.tools.list_sitemaps.list_sitemaps",
        AsyncMock(return_value={"sitemaps": [], "sitemap_count": 0}),
    )

    result = await google_search_console_list_sitemaps(
        _ctx(entry, tool_name="google_search_console_list_sitemaps")
    )

    assert result["results"][0]["status"] == "success"
    detail = audit.await_args.kwargs["operation_detail"].model_dump(mode="json")
    fields = detail["intent_groups"][0]["items"][0]["fields"]
    assert fields == {"sitemap_count": 0}
    assert "path" not in str(detail)


async def _async_value(value):
    return value
