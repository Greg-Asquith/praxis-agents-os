"""Meta read fan-out, policy, and safe audit evidence."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry

from core.exceptions.general import AppValidationError
from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationRateLimitError,
    IntegrationValidationError,
)
from integrations.meta_ads.tools.run_insights import DEFINITION, meta_ads_run_insights
from integrations.meta_ads.tools.schemas.activities import (
    MetaAdsActivitiesData,
    MetaAdsActivitiesOutput,
)
from integrations.meta_ads.tools.schemas.insights import MetaAdsInsightsData, MetaAdsInsightsOutput
from services.agent_runs.validate_override_args import validate_and_canonicalize_override_args
from services.integrations.context.domain import ResolvedActiveContext
from services.integrations.report_results import REPORT_RESULT_GUIDANCE
from tests.integrations.meta_ads.support import context_entry

TODAY = datetime.now(UTC).date().isoformat()
HOSTILE = (
    (Path(__file__).parents[2] / "fixtures/prompt_injection/hostile_meta_campaign_name.txt")
    .read_text()
    .strip()
)


def _ctx(*entries):
    return SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=entries),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4(), name="Reporting agent"),
            run=SimpleNamespace(id=uuid4(), user_id=uuid4()),
        ),
        tool_name="meta_ads_run_insights",
        tool_call_id="call-meta-insights",
    )


def _report():
    return MetaAdsInsightsData(
        rows=[
            {
                "keys": {"campaign_name": HOSTILE},
                "metrics": {"spend": 5339.5},
                "actions": {},
                "date_start": TODAY,
                "date_stop": TODAY,
            }
        ],
        row_count=1,
        truncated=False,
        truncation_note=None,
        mode="direct",
        notes=[],
        money_fields=["spend"],
        level="campaign",
        since=TODAY,
        until=TODAY,
    )


@pytest.mark.parametrize("optional", [{}, {"filters": None}, {"filters": []}])
async def test_insights_approval_accepts_absent_filters(monkeypatch, optional):
    monkeypatch.setattr(
        "services.agents.runtime.tools.registry.get_runtime_tool_definition", lambda _: DEFINITION
    )
    args = {"fields": ["spend"], "since": TODAY, "until": TODAY, **optional}
    assert (
        await validate_and_canonicalize_override_args(
            AsyncMock(),
            actor=SimpleNamespace(),
            workspace=SimpleNamespace(),
            membership=SimpleNamespace(),
            run=SimpleNamespace(),
            tool_call=SimpleNamespace(tool_name=DEFINITION.name, args=args),
            override_args=None,
        )
        is None
    )


async def test_insights_approval_accepts_all_report_edits(monkeypatch):
    monkeypatch.setattr(
        "services.agents.runtime.tools.registry.get_runtime_tool_definition", lambda _: DEFINITION
    )
    original = {"fields": ["spend"], "since": TODAY, "until": TODAY}
    effective = {
        **original,
        "level": "adset",
        "fields": ["spend", "actions"],
        "breakdowns": ["country"],
        "action_breakdowns": ["action_type"],
        "attribution_windows": ["7d_click"],
        "time_increment": 7,
        "limit": 500,
        "sort": "spend_descending",
        "filters": [
            {"field": "campaign.id", "operator": "IN", "value": ["123", "456"]},
            {"field": "spend", "operator": "GREATER_THAN", "value": 5},
        ],
    }
    result = await validate_and_canonicalize_override_args(
        AsyncMock(),
        actor=SimpleNamespace(),
        workspace=SimpleNamespace(),
        membership=SimpleNamespace(),
        run=SimpleNamespace(),
        tool_call=SimpleNamespace(tool_name=DEFINITION.name, args=original),
        override_args=effective,
    )
    assert result == effective
    from integrations.meta_ads.tools.utils.validation import validated_insights_request

    assert validated_insights_request(max_rows=1000, **result).time_increment == 7


@pytest.mark.parametrize("value", [True, {"injected": "value"}, [False], [float("nan")]])
async def test_insights_approval_rejects_invalid_filter_cells(monkeypatch, value):
    monkeypatch.setattr(
        "services.agents.runtime.tools.registry.get_runtime_tool_definition", lambda _: DEFINITION
    )
    args = {
        "fields": ["spend"],
        "since": TODAY,
        "until": TODAY,
        "filters": [{"field": "spend", "operator": "EQUAL", "value": value}],
    }
    with pytest.raises(AppValidationError):
        await validate_and_canonicalize_override_args(
            AsyncMock(),
            actor=SimpleNamespace(),
            workspace=SimpleNamespace(),
            membership=SimpleNamespace(),
            run=SimpleNamespace(),
            tool_call=SimpleNamespace(tool_name=DEFINITION.name, args=args),
            override_args=None,
        )


async def test_insights_fans_out_and_audits_parameters_without_provider_text(monkeypatch):
    entries = (context_entry("111"), context_entry("222"))
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )

    async def client(_ctx, entry):
        return entry.external_id

    async def report(client, **kwargs):
        assert kwargs["max_response_bytes"] > 0
        if client == "111":
            raise IntegrationRateLimitError("Try again in 10 minutes.", provider_key="meta_ads")
        return _report()

    monkeypatch.setattr("integrations.meta_ads.tools.run_insights.meta_ads_client", client)
    monkeypatch.setattr("integrations.meta_ads.tools.run_insights.run_insights", report)
    result = await meta_ads_run_insights(_ctx(*entries), fields=["spend"], since=TODAY, until=TODAY)
    MetaAdsInsightsOutput.model_validate(result)
    assert [row["status"] for row in result["results"]] == ["error", "success"]
    assert "10 minutes" in result["results"][0]["error_message"]
    data = result["results"][1]["data"]
    assert data["currency"] == "EUR"
    assert data["timezone_name"] == "Europe/Paris"
    assert data["rows"][0]["keys"]["campaign_name"] == HOSTILE
    for entry in entries:
        assert str(entry.integration_resource_id) not in str(result)
        assert str(entry.connection_id) not in str(result)
    assert audit.await_count == 2
    detail = audit.await_args_list[1].kwargs["operation_detail"].model_dump()
    assert HOSTILE not in str(detail)
    fields = detail["intent_groups"][0]["items"][0]["fields"]
    assert fields == {
        "level": "campaign",
        "since": TODAY,
        "until": TODAY,
        "field_count": 1,
        "breakdowns": [],
        "attribution_mode": "unified",
        "mode": "direct",
        "row_count": 1,
    }


async def test_invalid_request_never_resolves_credentials(monkeypatch):
    client = AsyncMock()
    monkeypatch.setattr("integrations.meta_ads.tools.run_insights.meta_ads_client", client)
    with pytest.raises(ModelRetry, match="since"):
        await meta_ads_run_insights(
            _ctx(context_entry("111")), fields=["spend"], since="last_week", until=TODAY
        )
    client.assert_not_awaited()


async def test_known_throttle_is_audited_without_resolving_credentials(monkeypatch):
    audit = AsyncMock(return_value=uuid4())
    client = AsyncMock()
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    monkeypatch.setattr("integrations.meta_ads.tools.run_insights.meta_ads_client", client)

    def unavailable(account_id, *, operation):
        raise IntegrationRateLimitError("Try again in 5 minutes.", provider_key="meta_ads")

    monkeypatch.setattr(
        "integrations.meta_ads.tools.run_insights.ensure_account_available", unavailable
    )
    result = await meta_ads_run_insights(
        _ctx(context_entry("111")), fields=["spend"], since=TODAY, until=TODAY
    )
    assert result["results"][0]["status"] == "error"
    client.assert_not_awaited()
    assert audit.await_args.kwargs["status"] == "failure"
    assert audit.await_args.kwargs["error_code"] == "IntegrationRateLimitError"


def test_read_tool_uses_shared_retention_and_governance_contract():
    assert DEFINITION.timeout == 150
    assert DEFINITION.code_eligible
    assert DEFINITION.effect == "read"
    assert DEFINITION.egress == "provider_query"
    assert DEFINITION.preview_list_path == "results.*.data.rows"
    assert DEFINITION.max_public_result_chars > 0
    assert DEFINITION.description.endswith(REPORT_RESULT_GUIDANCE)
    assert DEFINITION.integration_binding.resource_types == frozenset({"meta_ads_ad_account"})


@pytest.mark.parametrize(
    "failure",
    [
        IntegrationValidationError(
            "Invalid breakdown combination.", error_code="meta_ads_invalid_insights"
        ),
        IntegrationValidationError(
            "Unknown Insights field.", error_code="meta_ads_invalid_insights"
        ),
    ],
)
async def test_provider_validation_retries_after_recording_account_audit(monkeypatch, failure):
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    monkeypatch.setattr("integrations.meta_ads.tools.run_insights.meta_ads_client", AsyncMock())
    monkeypatch.setattr(
        "integrations.meta_ads.tools.run_insights.run_insights", AsyncMock(side_effect=failure)
    )
    with pytest.raises(ModelRetry, match=r"breakdown|field"):
        await meta_ads_run_insights(
            _ctx(context_entry("111")), fields=["spend"], since=TODAY, until=TODAY
        )
    assert audit.await_args.kwargs["status"] == "failure"


@pytest.mark.parametrize("success", [False, True])
@pytest.mark.parametrize("kind", ["query", "credentials"])
async def test_account_corrections_preserve_success_and_audit_each_account(
    monkeypatch, success, kind
):
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    failure = (
        IntegrationValidationError("Unknown field.", error_code="meta_ads_invalid_insights")
        if kind == "query"
        else IntegrationAuthError(
            "Replace the Meta Ads access token to reconnect.", provider_key="meta_ads"
        )
    )

    async def report(client, **kwargs):
        if success and kwargs["account_id"] == "111":
            return _report()
        raise failure

    monkeypatch.setattr("integrations.meta_ads.tools.run_insights.meta_ads_client", AsyncMock())
    monkeypatch.setattr("integrations.meta_ads.tools.run_insights.run_insights", report)
    call = meta_ads_run_insights(
        _ctx(context_entry("111"), context_entry("222")), fields=["spend"], since=TODAY, until=TODAY
    )
    if not success and kind == "query":
        with pytest.raises(ModelRetry, match="Unknown field"):
            await call
    else:
        result = await call
        assert [item["status"] for item in result["results"]] == (
            ["success", "error"] if success else ["error", "error"]
        )
        if success:
            assert result["results"][0]["data"]["rows"][0]["metrics"]["spend"] == 5339.5
        assert result["results"][-1]["error_code"] == (
            "meta_ads_invalid_insights" if kind == "query" else "IntegrationAuthError"
        )
        assert "meta-test-access-token" not in str(result)
    assert audit.await_count == 2
    assert [call.kwargs["status"] for call in audit.await_args_list] == (
        ["success", "failure"] if success else ["failure", "failure"]
    )


async def test_execution_deadline_preserves_completed_accounts_and_audits_unstarted(monkeypatch):
    import asyncio
    import importlib

    module = importlib.import_module("integrations.meta_ads.tools.run_insights")
    monkeypatch.setattr(module, "_EXECUTION_SECONDS", 0.03)
    monkeypatch.setattr(module, "_AUDIT_SECONDS_PER_ACCOUNT", 0)
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    credentials = AsyncMock()
    monkeypatch.setattr(module, "meta_ads_client", credentials)
    cancelled = []

    async def report(client, **kwargs):
        if kwargs["account_id"] == "111":
            return _report()
        try:
            await asyncio.sleep(0.08)
        except asyncio.CancelledError:
            cancelled.append(kwargs["account_id"])
            raise
        return _report()

    monkeypatch.setattr(module, "run_insights", report)
    result = await meta_ads_run_insights(
        _ctx(*(context_entry(account) for account in ["111", "222", "333"])),
        fields=["spend"],
        since=TODAY,
        until=TODAY,
    )
    assert [item["status"] for item in result["results"]] == ["success", "error", "error"]
    assert [item["error_code"] for item in result["results"][1:]] == [
        "meta_ads_insights_deadline"
    ] * 2
    assert result["results"][0]["data"]["row_count"] == 1
    assert cancelled == ["222"]
    assert credentials.await_count == 2
    assert audit.await_count == 3


@pytest.mark.parametrize(
    "phase", ["credentials", "submission", "retry", "polling", "paging", "conversion_lookup"]
)
async def test_complete_account_budget_covers_every_wait(monkeypatch, phase):
    import asyncio
    import importlib
    from dataclasses import replace

    import httpx2
    from pydantic_ai import RunContext
    from pydantic_ai.models.test import TestModel
    from pydantic_ai.toolsets import FunctionToolset
    from pydantic_ai.usage import RunUsage

    from integrations.meta_ads.client import MetaAdsClient
    from tests.integrations.meta_ads.support import static_token

    module = importlib.import_module("integrations.meta_ads.tools.run_insights")
    monkeypatch.setattr(module, "_EXECUTION_SECONDS", 0.1)
    monkeypatch.setattr(module, "_AUDIT_SECONDS_PER_ACCOUNT", 0)
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    requests = []
    cancelled = []

    async def stall():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(phase)
            raise

    async def respond(request):
        requests.append(request)
        path = request.url.path
        if "act_111" in path:
            return httpx2.Response(
                200, json={"data": [{"spend": "5", "date_start": TODAY, "date_stop": TODAY}]}
            )
        if phase == "conversion_lookup":
            if path.endswith("/customconversions"):
                await stall()
            return httpx2.Response(
                200,
                json={
                    "data": [
                        {
                            "actions": [
                                {"action_type": "offsite_conversion.custom.901", "value": "2"}
                            ],
                            "date_start": TODAY,
                            "date_stop": TODAY,
                        }
                    ]
                },
            )
        if phase == "retry":
            return httpx2.Response(503, headers={"Retry-After": "5"}, json={"error": {"code": 2}})
        if phase == "paging":
            if request.url.params.get("after"):
                await stall()
            return httpx2.Response(
                200,
                json={
                    "data": [{"spend": "8", "date_start": TODAY, "date_stop": TODAY}],
                    "paging": {"next": f"https://graph.facebook.com{path}?after=next"},
                },
            )
        if request.method == "POST":
            if phase == "submission":
                await stall()
            return httpx2.Response(200, json={"report_run_id": "987"})
        if path.endswith("/987"):
            await stall()
        return httpx2.Response(400, json={"error": {"code": 100, "error_subcode": 1487534}})

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:
        provider = MetaAdsClient(static_token, client=http)

        async def resolve(ctx, entry):
            if phase == "credentials" and entry.external_id == "222":
                await stall()
            return provider

        monkeypatch.setattr(module, "meta_ads_client", resolve)
        ctx = RunContext(
            deps=_ctx(context_entry("111"), context_entry("222"), context_entry("333")).deps,
            model=TestModel(),
            usage=RunUsage(),
            tool_name=DEFINITION.name,
            tool_call_id="deadline",
        )
        toolset = FunctionToolset([replace(DEFINITION, timeout=0.5).to_pydantic_tool()])
        tool = (await toolset.get_tools(ctx))[DEFINITION.name]
        result = await toolset.call_tool(
            DEFINITION.name,
            {
                "fields": ["actions"] if phase == "conversion_lookup" else ["spend"],
                "since": TODAY,
                "until": TODAY,
            },
            ctx,
            tool,
        )
    assert [item["status"] for item in result["results"]] == ["success", "error", "error"]
    if phase != "conversion_lookup":
        assert result["results"][0]["data"]["rows"][0]["metrics"]["spend"] == 5
    assert [item["error_code"] for item in result["results"][1:]] == [
        "meta_ads_insights_deadline"
    ] * 2
    assert audit.await_count == 3
    assert all("act_333" not in str(request.url) for request in requests)
    if phase == "retry":
        assert len(requests) == 2
    else:
        assert cancelled == [phase]


async def test_background_accounts_share_deadline_including_completed_wait(monkeypatch):
    import asyncio
    import importlib

    import httpx2

    from integrations.meta_ads.client import MetaAdsClient
    from tests.integrations.meta_ads.support import static_token

    module = importlib.import_module("integrations.meta_ads.tools.run_insights")
    clock = [0.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(module, "_EXECUTION_SECONDS", 0.1)
    monkeypatch.setattr(module, "_AUDIT_SECONDS_PER_ACCOUNT", 0)
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    cancelled = []

    async def respond(request):
        path = request.url.path
        if request.method == "POST":
            return httpx2.Response(200, json={"report_run_id": "111" if "111" in path else "222"})
        if "act_" in path:
            return httpx2.Response(400, json={"error": {"code": 100, "error_subcode": 1487534}})
        if path.endswith("/insights"):
            return httpx2.Response(
                200, json={"data": [{"spend": "5", "date_start": TODAY, "date_stop": TODAY}]}
            )
        if path.endswith("/111"):
            clock[0] += 0.07
        else:
            try:
                await asyncio.sleep(0.07)
            except asyncio.CancelledError:
                cancelled.append("222")
                raise
        return httpx2.Response(
            200, json={"async_status": "Job Completed", "async_percent_completion": 100}
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:
        provider = MetaAdsClient(static_token, client=http)
        monkeypatch.setattr(module, "meta_ads_client", AsyncMock(return_value=provider))
        result = await meta_ads_run_insights(
            _ctx(context_entry("111"), context_entry("222")),
            fields=["spend"],
            since=TODAY,
            until=TODAY,
        )
    assert [item["status"] for item in result["results"]] == ["success", "error"]
    assert result["results"][0]["data"]["mode"] == "background"
    assert result["results"][1]["error_code"] == "meta_ads_insights_deadline"
    assert cancelled == ["222"]
    assert audit.await_count == 2


async def test_external_cancellation_propagates_and_audits(monkeypatch):
    import asyncio

    started = asyncio.Event()
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    monkeypatch.setattr("integrations.meta_ads.tools.run_insights.meta_ads_client", AsyncMock())

    async def report(client, **kwargs):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("integrations.meta_ads.tools.run_insights.run_insights", report)
    task = asyncio.create_task(
        meta_ads_run_insights(
            _ctx(context_entry("111")), fields=["spend"], since=TODAY, until=TODAY
        )
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert audit.await_count == 1
    assert audit.await_args.kwargs["error_code"] == "CancelledError"


async def test_deadline_reserves_terminal_audits_for_all_accounts(monkeypatch):
    import asyncio
    import importlib
    from dataclasses import replace

    from pydantic_ai import RunContext
    from pydantic_ai.models.test import TestModel
    from pydantic_ai.toolsets import FunctionToolset
    from pydantic_ai.usage import RunUsage

    module = importlib.import_module("integrations.meta_ads.tools.run_insights")
    monkeypatch.setattr(module, "_EXECUTION_SECONDS", 0.45)
    monkeypatch.setattr(module, "_AUDIT_SECONDS_PER_ACCOUNT", 0.04, raising=False)

    async def record(**kwargs):
        await asyncio.sleep(0.035)
        return uuid4()

    audit = AsyncMock(side_effect=record)
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    monkeypatch.setattr(module, "meta_ads_client", AsyncMock())

    async def report(client, **kwargs):
        if kwargs["account_id"] == "111":
            return _report()
        await asyncio.Event().wait()
        raise AssertionError("The report must be cancelled.")

    monkeypatch.setattr(module, "run_insights", report)
    ctx = RunContext(
        deps=_ctx(*(context_entry(str(value)) for value in [111, 222, 333, 444])).deps,
        model=TestModel(),
        usage=RunUsage(),
        tool_name=DEFINITION.name,
        tool_call_id="slow-audit",
    )
    toolset = FunctionToolset([replace(DEFINITION, timeout=0.5).to_pydantic_tool()])
    tool = (await toolset.get_tools(ctx))[DEFINITION.name]
    result = await toolset.call_tool(
        DEFINITION.name, {"fields": ["spend"], "since": TODAY, "until": TODAY}, ctx, tool
    )
    assert [item["status"] for item in result["results"]] == ["success", "error", "error", "error"]
    assert audit.await_count == 4


def test_account_audit_reserve_covers_shared_finalisation_bound():
    import importlib

    from services.integrations import operations

    module = importlib.import_module("integrations.meta_ads.tools.run_insights")
    assert module._AUDIT_SECONDS_PER_ACCOUNT >= operations._TERMINAL_AUDIT_FINALIZE_TIMEOUT_SECONDS
    assert DEFINITION.timeout - module._EXECUTION_SECONDS >= 15


@pytest.mark.parametrize(
    "tool_name,preview_path",
    [
        ("meta_ads_get_accounts", None),
        ("meta_ads_list_objects", "results.*.data.objects"),
        ("meta_ads_list_custom_conversions", "results.*.data.conversions"),
        ("meta_ads_list_activities", "results.*.data.events"),
    ],
)
def test_account_read_tools_use_shared_governance(tool_name, preview_path):
    from integrations.meta_ads.tools import TOOL_DEFINITIONS

    definition = next(item for item in TOOL_DEFINITIONS if item.name == tool_name)
    assert definition.timeout == 60
    assert definition.effect == "read"
    assert definition.egress == "provider_query"
    assert definition.default_policy == "auto"
    assert definition.code_eligible
    assert definition.preview_list_path == preview_path
    assert definition.integration_binding.resource_types == frozenset({"meta_ads_ad_account"})
    if preview_path:
        assert definition.max_public_result_chars > 0
        assert definition.description.endswith(REPORT_RESULT_GUIDANCE)


@pytest.mark.parametrize(
    "module_name,tool_name,operation_name,args",
    [
        ("get_accounts", "meta_ads_get_accounts", "get_account", {}),
        ("list_objects", "meta_ads_list_objects", "list_objects", {"object_type": "campaign"}),
        (
            "list_custom_conversions",
            "meta_ads_list_custom_conversions",
            "list_custom_conversions",
            {},
        ),
        (
            "list_activities",
            "meta_ads_list_activities",
            "list_activities",
            {"since": TODAY, "until": TODAY},
        ),
    ],
)
async def test_account_read_throttle_fails_before_resolving_credentials(
    monkeypatch, module_name, tool_name, operation_name, args
):
    import importlib

    module = importlib.import_module(f"integrations.meta_ads.tools.{module_name}")
    audit = AsyncMock(return_value=uuid4())
    client = AsyncMock()
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    monkeypatch.setattr(module, "meta_ads_client", client)

    def unavailable(account_id, *, operation):
        assert operation == operation_name
        raise IntegrationRateLimitError("Try again in 5 minutes.", provider_key="meta_ads")

    monkeypatch.setattr(module, "ensure_account_available", unavailable)
    ctx = _ctx(context_entry("111"))
    ctx.tool_name = tool_name
    result = await getattr(module, tool_name)(ctx, **args)
    assert result["results"][0]["status"] == "error"
    assert "5 minutes" in result["results"][0]["error_message"]
    client.assert_not_awaited()
    assert audit.await_args.kwargs["status"] == "failure"
    assert audit.await_args.kwargs["error_code"] == "IntegrationRateLimitError"


async def test_activities_fan_out_with_account_time_zone_and_counts_only_audit(monkeypatch):
    from integrations.meta_ads.tools import list_activities as module

    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    monkeypatch.setattr(module, "meta_ads_client", AsyncMock())
    zones = []

    async def history(client, **kwargs):
        zones.append(kwargs["timezone_name"])
        assert kwargs["max_response_bytes"] > 0
        return MetaAdsActivitiesData(
            events=[
                {
                    "event_time": f"{TODAY}T09:00:00+00:00",
                    "event_type": "update_ad_set_budget",
                    "translated_event_type": "Ad set budget updated",
                    "object_type": "ADSET",
                    "object_id": "10",
                    "object_name": HOSTILE,
                    "actor_name": "Dana",
                    "old_value": "1000",
                    "new_value": "2500",
                }
            ],
            event_count=1,
            truncated=False,
            window_note=None,
            timezone_name=kwargs["timezone_name"],
        )

    monkeypatch.setattr(module, "list_activities", history)
    ctx = _ctx(context_entry("111"))
    ctx.tool_name = "meta_ads_list_activities"
    result = await module.meta_ads_list_activities(ctx, TODAY, TODAY, ["10", "11"])
    MetaAdsActivitiesOutput.model_validate(result)
    assert zones == ["Europe/Paris"]
    assert result["results"][0]["data"]["events"][0]["object_name"] == HOSTILE
    detail = audit.await_args.kwargs["operation_detail"].model_dump()
    for text in (HOSTILE, "Dana", "2500", "Ad set budget updated"):
        assert text not in str(detail)
    assert detail["intent_groups"][0]["items"][0]["fields"] == {
        "since": TODAY,
        "until": TODAY,
        "object_id_count": 2,
        "event_count": 1,
    }
