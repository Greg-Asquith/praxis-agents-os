# apps/api/tests/integrations/google_search_console/test_tools_and_audits.py

"""Search Console tool fan-out and audit behavior."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from integrations.google_search_console.tools.inspect_url import (
    google_search_console_inspect_url,
)
from integrations.google_search_console.tools.list_sitemaps import (
    google_search_console_list_sitemaps,
)
from integrations.google_search_console.tools.query_search_analytics import (
    google_search_console_query_search_analytics,
)
from services.audit_events import AuditStatus
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
        AsyncMock(return_value="client"),
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
        AsyncMock(return_value="client"),
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


async def test_inspection_targets_each_site_sequentially_and_audits_counts_only(
    monkeypatch,
) -> None:
    prefix = _entry("https://example.com/docs/")
    domain = _entry("sc-domain:example.com")
    audit = AsyncMock(return_value=uuid4())
    operation = AsyncMock(
        side_effect=[
            {
                "url": "https://example.com/docs/start",
                "verdict": "PASS",
                "error_code": None,
            },
            {
                "url": "https://example.com/docs/missing",
                "verdict": "",
                "error_code": "IntegrationNotFoundError",
            },
            {
                "url": "https://blog.example.com/start",
                "verdict": "NEUTRAL",
                "error_code": None,
            },
        ]
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )
    monkeypatch.setattr(
        "integrations.google_search_console.tools.inspect_url.google_search_console_client",
        AsyncMock(side_effect=lambda _ctx, entry: f"client:{entry.external_id}"),
    )
    monkeypatch.setattr(
        "integrations.google_search_console.tools.inspect_url.inspect_url",
        operation,
    )

    result = await google_search_console_inspect_url(
        _ctx(prefix, domain, tool_name="google_search_console_inspect_url"),
        urls=[
            "https://example.com/docs/start",
            "https://example.com/docs/missing",
            "https://blog.example.com/start",
        ],
    )

    assert [item["external_id"] for item in result["results"]] == [
        "https://example.com/docs/",
        "sc-domain:example.com",
    ]
    assert [call.kwargs["url"] for call in operation.await_args_list] == [
        "https://example.com/docs/start",
        "https://example.com/docs/missing",
        "https://blog.example.com/start",
    ]
    details = [
        call.kwargs["operation_detail"].model_dump(mode="json") for call in audit.await_args_list
    ]
    assert [call.kwargs["status"] for call in audit.await_args_list] == [
        AuditStatus.PARTIAL,
        AuditStatus.SUCCESS,
    ]
    assert details[0]["intent_counts"] == {
        "applied": 0,
        "skipped": 0,
        "failed": 1,
        "unverified": 0,
    }
    assert details[0]["effect_counts"] == {
        "applied": 1,
        "skipped": 0,
        "failed": 1,
        "unverified": 0,
    }
    assert details[1]["intent_counts"] == {
        "applied": 1,
        "skipped": 0,
        "failed": 0,
        "unverified": 0,
    }
    fields = [detail["intent_groups"][0]["items"][0]["fields"] for detail in details]
    assert fields == [
        {"url_count": 2, "verdict_counts": {"pass": 1, "provider_error": 1}},
        {"url_count": 1, "verdict_counts": {"neutral": 1}},
    ]
    assert "https://example.com/docs/start" not in str(details)


async def test_inspection_marks_a_site_failed_when_every_url_has_a_provider_error(
    monkeypatch,
) -> None:
    entry = _entry("https://example.com/")
    monkeypatch.setattr(
        "integrations.google_search_console.tools.inspect_url.google_search_console_client",
        AsyncMock(return_value="client"),
    )
    monkeypatch.setattr(
        "integrations.google_search_console.tools.inspect_url.inspect_url",
        AsyncMock(
            return_value={
                "url": "https://example.com/missing",
                "verdict": "",
                "error_code": "IntegrationNotFoundError",
            }
        ),
    )

    result = await google_search_console_inspect_url(
        _ctx(entry, tool_name="google_search_console_inspect_url"),
        urls=["https://example.com/missing"],
    )

    assert result["results"][0]["status"] == "error"
    assert result["results"][0]["error_message"] == (
        "Google Search Console could not inspect any requested URLs for this site."
    )
