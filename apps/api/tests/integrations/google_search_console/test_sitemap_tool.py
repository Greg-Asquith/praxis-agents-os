# apps/api/tests/integrations/google_search_console/test_sitemap_tool.py

"""Search Console sitemap write-tool behavior."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry

from core.exceptions.integration import (
    IntegrationFailureDisposition,
    IntegrationTimeoutError,
)
from integrations.google_search_console.tools.submit_sitemap import (
    _approval_display_args,
    google_search_console_submit_sitemap,
)
from services.audit_events import AuditStatus
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry


def _entry(
    external_id: str = "https://example.com/",
    *,
    write_allowed: bool = True,
) -> ResolvedContextEntry:
    return ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="google_search_console",
        resource_type="google_search_console_site",
        external_id=external_id,
        display_name=external_id,
        connection_id=uuid4(),
        connection_label="Search Console",
        connection_status="active",
        write_allowed=write_allowed,
    )


def _ctx(*entries: ResolvedContextEntry) -> SimpleNamespace:
    return SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=entries),
            db=object(),
            user=SimpleNamespace(id=uuid4()),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4(), name="Search Agent"),
            run=SimpleNamespace(id=uuid4(), user_id=uuid4()),
        ),
        tool_name="google_search_console_submit_sitemap",
        tool_call_id="call-submit-sitemap",
    )


async def test_submit_sitemaps_records_pending_and_terminal_readback(monkeypatch) -> None:
    entry = _entry()
    audit = AsyncMock(return_value=uuid4())
    submit = AsyncMock()
    get = AsyncMock(
        side_effect=[
            {
                "path": "one",
                "last_submitted": "old",
                "is_pending": False,
                "warnings": 0,
                "errors": 0,
            },
            None,
            {
                "path": "one",
                "last_submitted": "2026-09-03T12:00:00Z",
                "is_pending": True,
                "warnings": 1,
                "errors": 0,
            },
            {
                "path": "two",
                "last_submitted": "2026-09-03T12:01:00Z",
                "is_pending": True,
                "warnings": 0,
                "errors": 0,
            },
        ]
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )
    monkeypatch.setattr(
        "integrations.google_search_console.tools.submit_sitemap.google_search_console_client",
        lambda _ctx, _entry: _async_value("client"),
    )
    monkeypatch.setattr(
        "integrations.google_search_console.tools.submit_sitemap.get_sitemap",
        get,
    )
    monkeypatch.setattr(
        "integrations.google_search_console.tools.submit_sitemap.submit_sitemap",
        submit,
    )

    result = await google_search_console_submit_sitemap(
        _ctx(entry),
        sitemap_urls=[
            "https://example.com/one.xml",
            "https://example.com/two.xml",
        ],
    )

    assert [call.kwargs["sitemap_url"] for call in submit.await_args_list] == [
        "https://example.com/one.xml",
        "https://example.com/two.xml",
    ]
    assert result.return_value["results"][0]["data"] == {
        "sitemaps": [
            {
                "sitemap_url": "https://example.com/one.xml",
                "outcome": "submitted",
                "previously_submitted": True,
                "status_read": True,
                "error_code": None,
            },
            {
                "sitemap_url": "https://example.com/two.xml",
                "outcome": "submitted",
                "previously_submitted": False,
                "status_read": True,
                "error_code": None,
            },
        ],
        "submitted_count": 2,
        "failed_count": 0,
    }
    display = result.metadata["public_result"]["results"][0]["data"]
    assert [item["last_submitted"] for item in display["sitemaps"]] == [
        "2026-09-03T12:00:00Z",
        "2026-09-03T12:01:00Z",
    ]
    assert [call.kwargs["status"] for call in audit.await_args_list] == [
        AuditStatus.PENDING,
        AuditStatus.SUCCESS,
    ]
    pending = audit.await_args_list[0].kwargs["operation_detail"]
    terminal = audit.await_args_list[1].kwargs["operation_detail"]
    assert [item.fields for item in pending.intent_groups[0].items] == [
        {"sitemap_url": "https://example.com/one.xml", "previously_submitted": True},
        {"sitemap_url": "https://example.com/two.xml", "previously_submitted": False},
    ]
    assert terminal.intent_counts.applied == 2
    assert audit.await_args_list[1].kwargs["external_ref"] == (
        "https://example.com/one.xml,https://example.com/two.xml"
    )


async def test_submit_timeout_retains_unverified_result_and_evidence(monkeypatch) -> None:
    entry = _entry()
    audit = AsyncMock(return_value=uuid4())
    timeout = IntegrationTimeoutError(
        "The request timed out.",
        provider_key="google_search_console",
        operation="submit_sitemap",
        failure_disposition=IntegrationFailureDisposition.AMBIGUOUS,
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )
    monkeypatch.setattr(
        "integrations.google_search_console.tools.submit_sitemap.google_search_console_client",
        lambda _ctx, _entry: _async_value("client"),
    )
    monkeypatch.setattr(
        "integrations.google_search_console.tools.submit_sitemap.get_sitemap",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "integrations.google_search_console.tools.submit_sitemap.submit_sitemap",
        AsyncMock(side_effect=timeout),
    )

    result = await google_search_console_submit_sitemap(
        _ctx(entry),
        sitemap_urls=["https://example.com/sitemap.xml"],
    )

    fan_out = result.return_value["results"][0]
    assert fan_out["status"] == "error"
    assert fan_out["error_code"] == "unverified_mutation"
    assert fan_out["data"]["sitemaps"][0]["outcome"] == "unverified"
    assert fan_out["data"]["sitemaps"][0]["error_code"] == "unverified"
    public = result.metadata["public_result"]["results"][0]["data"]
    assert public["sitemaps"][0]["message"].startswith("Google may or may not")
    assert audit.await_args_list[-1].kwargs["status"] is AuditStatus.UNVERIFIED
    assert audit.await_args_list[-1].kwargs["operation_detail"].intent_counts.unverified == 1


async def test_failed_status_read_keeps_submission_confirmed(monkeypatch) -> None:
    entry = _entry()
    audit = AsyncMock(return_value=uuid4())
    read_error = IntegrationTimeoutError(
        "The status read timed out.",
        provider_key="google_search_console",
        operation="get_sitemap",
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )
    monkeypatch.setattr(
        "integrations.google_search_console.tools.submit_sitemap.google_search_console_client",
        lambda _ctx, _entry: _async_value("client"),
    )
    monkeypatch.setattr(
        "integrations.google_search_console.tools.submit_sitemap.get_sitemap",
        AsyncMock(side_effect=[None, read_error]),
    )
    monkeypatch.setattr(
        "integrations.google_search_console.tools.submit_sitemap.submit_sitemap",
        AsyncMock(),
    )

    result = await google_search_console_submit_sitemap(
        _ctx(entry),
        sitemap_urls=["https://example.com/sitemap.xml"],
    )

    public = result.metadata["public_result"]["results"][0]["data"]
    row = public["sitemaps"][0]
    assert row["outcome"] == "submitted"
    assert row["status_read"] is False
    assert row["error_code"] == "status_unavailable"
    assert audit.await_args_list[-1].kwargs["status"] is AuditStatus.SUCCESS


async def test_rejected_submission_uses_the_public_rejected_error_code(monkeypatch) -> None:
    entry = _entry()
    rejected = IntegrationTimeoutError(
        "Google rejected the request.",
        provider_key="google_search_console",
        operation="submit_sitemap",
        failure_disposition=IntegrationFailureDisposition.REJECTED,
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        AsyncMock(return_value=uuid4()),
    )
    monkeypatch.setattr(
        "integrations.google_search_console.tools.submit_sitemap.google_search_console_client",
        lambda _ctx, _entry: _async_value("client"),
    )
    monkeypatch.setattr(
        "integrations.google_search_console.tools.submit_sitemap.get_sitemap",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "integrations.google_search_console.tools.submit_sitemap.submit_sitemap",
        AsyncMock(side_effect=rejected),
    )

    result = await google_search_console_submit_sitemap(
        _ctx(entry),
        sitemap_urls=["https://example.com/sitemap.xml"],
    )

    row = result.metadata["public_result"]["results"][0]["data"]["sitemaps"][0]
    assert row["outcome"] == "failed"
    assert row["error_code"] == "rejected"


async def test_approval_display_marks_add_and_resubmit(monkeypatch) -> None:
    entry = _entry()
    deps = _ctx(entry).deps
    monkeypatch.setattr(
        "integrations.google_search_console.tools.submit_sitemap.google_search_console_client_for_principal",
        lambda *_args, **_kwargs: _async_value("client"),
    )
    monkeypatch.setattr(
        "integrations.google_search_console.tools.submit_sitemap.get_sitemap",
        AsyncMock(side_effect=[{"path": "one"}, None]),
    )

    result = await _approval_display_args(
        deps,
        {
            "sitemap_urls": [
                "https://example.com/one.xml",
                "https://example.com/two.xml",
            ]
        },
    )

    assert result["_sitemap_submission_status"] == [
        {
            "sitemap_url": "https://example.com/one.xml",
            "site_url": "https://example.com/",
            "previously_submitted": True,
        },
        {
            "sitemap_url": "https://example.com/two.xml",
            "site_url": "https://example.com/",
            "previously_submitted": False,
        },
    ]
    assert result["_sitemap_writable_sites"] == ["https://example.com/"]


async def test_approval_display_lists_every_selected_writable_site(monkeypatch) -> None:
    primary = _entry("https://example.com/")
    alternate = _entry("https://other.example/")
    monkeypatch.setattr(
        "integrations.google_search_console.tools.submit_sitemap.google_search_console_client_for_principal",
        lambda *_args, **_kwargs: _async_value("client"),
    )
    monkeypatch.setattr(
        "integrations.google_search_console.tools.submit_sitemap.get_sitemap",
        AsyncMock(return_value=None),
    )

    result = await _approval_display_args(
        _ctx(primary, alternate).deps,
        {"sitemap_urls": ["https://example.com/sitemap.xml"]},
    )

    assert result["_sitemap_writable_sites"] == [
        "https://example.com/",
        "https://other.example/",
    ]


async def test_unexpected_mid_batch_failure_closes_every_pending_intent(monkeypatch) -> None:
    entry = _entry()
    audit = AsyncMock(return_value=uuid4())
    submit = AsyncMock(side_effect=[None, RuntimeError("unexpected response")])
    get = AsyncMock(
        side_effect=[
            None,
            None,
            None,
            {
                "path": "one",
                "last_submitted": "2026-09-03T12:00:00Z",
                "is_pending": False,
                "warnings": 0,
                "errors": 0,
            },
        ]
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )
    monkeypatch.setattr(
        "integrations.google_search_console.tools.submit_sitemap.google_search_console_client",
        lambda _ctx, _entry: _async_value("client"),
    )
    monkeypatch.setattr(
        "integrations.google_search_console.tools.submit_sitemap.get_sitemap",
        get,
    )
    monkeypatch.setattr(
        "integrations.google_search_console.tools.submit_sitemap.submit_sitemap",
        submit,
    )

    result = await google_search_console_submit_sitemap(
        _ctx(entry),
        sitemap_urls=[
            "https://example.com/one.xml",
            "https://example.com/two.xml",
            "https://example.com/three.xml",
        ],
    )

    assert result.return_value["results"][0]["error_code"] == "unverified_mutation"
    terminal = audit.await_args_list[-1].kwargs["operation_detail"]
    assert terminal.intent_counts.model_dump() == {
        "applied": 1,
        "skipped": 0,
        "failed": 1,
        "unverified": 1,
    }
    assert [outcome.effects[0].error_code for outcome in terminal.outcome_groups[0].outcomes] == [
        None,
        "unverified",
        "rejected",
    ]


async def test_submit_sitemap_rejects_a_restricted_site_before_provider_calls(monkeypatch) -> None:
    provider = AsyncMock()
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "integrations.google_search_console.tools.submit_sitemap.submit_sitemap",
        provider,
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )

    result = await google_search_console_submit_sitemap(
        _ctx(_entry(write_allowed=False)),
        sitemap_urls=["https://example.com/sitemap.xml"],
    )

    provider.assert_not_awaited()
    assert result.return_value["results"][0]["error_code"] == "write_not_permitted"
    assert audit.await_args.kwargs["status"] is AuditStatus.FAILURE


async def test_approval_display_rejects_a_restricted_site_before_approval() -> None:
    with pytest.raises(ModelRetry, match="selected Search Console property"):
        await _approval_display_args(
            _ctx(_entry(write_allowed=False)).deps,
            {"sitemap_urls": ["https://example.com/sitemap.xml"]},
        )


async def _async_value(value):
    return value
