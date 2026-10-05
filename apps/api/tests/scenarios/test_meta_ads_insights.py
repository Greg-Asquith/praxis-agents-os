"""Meta Insights runs through dispatch, retained Files, and Code Mode."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID

import httpx2
import pytest
from pydantic_ai.messages import RetryPromptPart, ToolReturnPart
from sqlalchemy import select

from core.database import set_session_tenant_context
from core.exceptions.integration import IntegrationAuthError
from core.settings import settings
from integrations.meta_ads import throttle
from integrations.meta_ads.client import META_GRAPH_API_VERSION, MetaAdsClient
from integrations.meta_ads.settings import meta_ads_settings
from integrations.meta_ads.tools.run_insights import DEFINITION
from models.files import File, FileRevision
from services.agents.runtime.structured_results import result_json
from services.agents.runtime.tools.code_mode import RUN_CODE_TOOL_NAME
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.files.utils import file_revision_ref
from services.integrations.context.domain import ResolvedActiveContext
from services.storage.factory import get_storage_provider
from tests.integrations.meta_ads.support import context_entry
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    next_scenario_run,
    run_scenario,
    scripted_model,
)
from tests.support.storage import reset_storage_provider_cache

TODAY = datetime.now(UTC).date().isoformat()


@pytest.fixture
def insights_runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "AGENT_STRUCTURED_RESULT_MAX_CHARS", 12_000)
    monkeypatch.setattr(settings, "AGENT_RESULT_PREVIEW_ROWS", 10)
    monkeypatch.setattr(settings, "AGENT_RUN_TOTAL_TOKENS_LIMIT", 100_000)
    monkeypatch.setattr(settings, "AGENT_CODE_MODE_VALUE_MAX_BYTES", 8 * 1024 * 1024)
    monkeypatch.setattr(meta_ads_settings, "META_ADS_INSIGHTS_MAX_ROWS", 2_000)
    monkeypatch.setitem(
        RUNTIME_TOOL_CATALOG,
        DEFINITION.name,
        replace(DEFINITION, availability_check=lambda: True, max_public_result_chars=12_000),
    )
    monkeypatch.setattr(
        "services.agents.runtime.execute.setup.resolve_active_context",
        AsyncMock(return_value=ResolvedActiveContext(entries=(context_entry("111"),))),
    )
    reset_storage_provider_cache()
    monkeypatch.setattr(throttle, "_accounts", {})
    yield
    reset_storage_provider_cache()


@pytest.mark.parametrize(("nested", "failure"), [(False, "query"), (True, None)])
async def test_insights_dispatch_preserves_complete_report(
    db_session_factory, monkeypatch, insights_runtime, nested, failure
):
    today = datetime.now(UTC).date().isoformat()
    rows = [
        {
            "account_id": "111",
            "account_name": "Example account",
            "campaign_id": str(index),
            "campaign_name": f"Campaign {index}: " + "Example campaign " * 2,
            "date_start": today,
            "date_stop": today,
            "spend": "2.50",
            "impressions": str(index),
            "actions": [{"action_type": "offsite_conversion.custom.901", "value": "2"}],
            **(
                {
                    "objective": "OUTCOME_SALES",
                    "quality_ranking": "ABOVE_AVERAGE",
                    "outbound_clicks": [{"action_type": "link_click", "value": "3"}],
                    "video_play_actions": [{"action_type": "video_view", "value": "4"}],
                }
                if index % 2
                else {}
            ),
        }
        for index in range(1_500)
    ]
    requests = []
    if failure:
        monkeypatch.setattr(
            "services.agents.runtime.execute.setup.resolve_active_context",
            AsyncMock(
                return_value=ResolvedActiveContext(
                    entries=(context_entry("111"), context_entry("222"))
                )
            ),
        )
    error_code = "meta_ads_invalid_insights" if failure == "query" else "IntegrationAuthError"

    def respond(request):
        requests.append(request)
        assert request.method == "GET"
        if request.url.path == f"/{META_GRAPH_API_VERSION}/act_111/customconversions":
            return httpx2.Response(200, json={"data": [{"id": "901", "name": "Qualified lead"}]})
        if request.url.path == f"/{META_GRAPH_API_VERSION}/act_222/insights":
            return httpx2.Response(
                400,
                json={
                    "error": {
                        "code": 100 if failure == "query" else 190,
                        "message": "Account cannot use this query test-meta-token",
                    }
                },
            )
        assert request.url.path == f"/{META_GRAPH_API_VERSION}/act_111/insights"
        assert request.url.params["action_breakdowns"] == "action_type"
        assert json.loads(request.url.params["time_range"]) == {"since": today, "until": today}
        if request.url.params.get("after") == "next":
            assert request.url.params["limit"] == "500"
            return httpx2.Response(200, json={"data": rows[1_000:]})
        return httpx2.Response(
            200,
            json={
                "data": rows[:1_000],
                "paging": {
                    "next": f"https://graph.facebook.com/{META_GRAPH_API_VERSION}/act_111/insights?after=next"
                },
            },
        )

    context = await build_scenario_agent(db_session_factory, tool_names=[DEFINITION.name])
    fields = [
        "spend",
        "impressions",
        "actions",
        "objective",
        "quality_ranking",
        "outbound_clicks",
        "video_play_actions",
    ]
    arguments = {
        "fields": fields,
        "since": today,
        "until": today,
        "limit": 1_500,
        "action_breakdowns": ["action_type"],
    }
    code = (
        f"report = await meta_ads_run_insights(fields={fields!r}, "
        f"since={today!r}, until={today!r}, limit=1500, action_breakdowns=['action_type'])\n"
        "data = report['results'][0]['data']\n"
        "{'rows': len(data['rows']), 'impressions': sum(row['metrics']['impressions'] "
        "for row in data['rows']), 'currency': data['currency'], "
        "'conversion_names': list(set(row['actions']['actions'][0]['custom_conversion_name'] "
        "for row in data['rows'])), "
        "'conversion_total': sum(row['actions']['actions'][0]['value'] for row in data['rows']), "
        "'first_objective': data['rows'][0]['keys']['objective'], "
        "'second_objective': data['rows'][1]['keys']['objective'], "
        "'first_outbound': data['rows'][0]['actions']['outbound_clicks'], "
        "'video_views': data['rows'][1]['actions']['video_play_actions'][0]['value'], "
        "'outbound_clicks': data['rows'][1]['actions']['outbound_clicks'][0]['value'], "
        "'statuses': [entry['status'] for entry in report['results']], "
        "'error_codes': [entry['error_code'] for entry in report['results']]}"
    )
    call = (
        ToolCall(RUN_CODE_TOOL_NAME, {"code": code})
        if nested
        else ToolCall(DEFINITION.name, arguments)
    )
    seen = []
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:
        provider = MetaAdsClient(AsyncMock(return_value="test-meta-token"), client=http)

        async def resolve_client(_ctx, entry):
            if entry.external_id == "222" and failure == "credentials":
                raise IntegrationAuthError("Replace the Meta Ads access token to reconnect.")
            return provider

        monkeypatch.setattr(
            "integrations.meta_ads.tools.run_insights.meta_ads_client",
            resolve_client,
        )
        result = await run_scenario(
            db_session_factory,
            context,
            model=scripted_model(turns=[ToolTurn((call,)), "Report ready."], seen_requests=seen),
        )

    assert result.run.status == "completed"
    assert len(requests) == (4 if failure in {"query", "authentication"} else 3), [
        part.content
        for message in seen[-1][0]
        for part in message.parts
        if isinstance(part, RetryPromptPart)
    ]
    assert any(
        row.tool_name == DEFINITION.name and row.status == "success" for row in result.audit_rows
    )
    operations = [
        row for row in result.audit_rows if row.details.get("provider_operation") == "run_insights"
    ]
    assert len(operations) == (2 if failure else 1)
    assert {row.details["external_id"]: row.status for row in operations} == (
        {"111": "success", "222": "failure"} if failure else {"111": "success"}
    )
    assert "test-meta-token" not in str([row.details for row in result.audit_rows])
    assert "test-meta-token" not in str(
        result.tool_returns(RUN_CODE_TOOL_NAME if nested else DEFINITION.name)
    )
    if nested:
        assert result.tool_returns(RUN_CODE_TOOL_NAME), [
            part.content
            for message in seen[-1][0]
            for part in message.parts
            if isinstance(part, RetryPromptPart)
        ]
        assert result.tool_returns(RUN_CODE_TOOL_NAME)[0]["content"] == {
            "rows": 1_500,
            "impressions": 1_124_250,
            "currency": "EUR",
            "conversion_names": ["Qualified lead"],
            "conversion_total": 3_000,
            "first_objective": None,
            "second_objective": "OUTCOME_SALES",
            "first_outbound": [],
            "video_views": 4.0,
            "outbound_clicks": 3.0,
            "statuses": ["success", "error"] if failure else ["success"],
            "error_codes": [None, error_code] if failure else [None],
        }
        async with db_session_factory() as db:
            await set_session_tenant_context(
                db, workspace_id=context.workspace_id, user_id=context.user_id
            )
            assert not (
                await db.execute(select(File.id).where(File.is_tool_result.is_(True)))
            ).all()
        return

    [returned] = result.tool_returns(DEFINITION.name)
    preview = returned["content"]
    assert preview["preview"] is True
    assert preview["lists"] == {"results.0.data.rows": {"total": 1_500, "shown": 10}}
    data = preview["data"]["results"][0]["data"]
    assert data["rows"][0]["actions"]["actions"][0]["custom_conversion_name"] == "Qualified lead"
    assert data["rows"][0]["keys"]["objective"] is None
    assert data["rows"][1]["keys"]["objective"] == "OUTCOME_SALES"
    assert data["rows"][0]["actions"]["outbound_clicks"] == []
    assert data["rows"][1]["actions"]["outbound_clicks"][0]["value"] == 3
    assert "outbound_clicks" not in data["rows"][0]["metrics"]
    if failure:
        assert preview["data"]["results"][1]["status"] == "error"
        assert preview["data"]["results"][1]["error_code"] == error_code
    assert data["row_count"] == 1_500 and data["truncated"] is False
    assert data["currency"] == "EUR" and data["timezone_name"] == "Europe/Paris"
    assert returned["metadata"]["result_preview"] == preview
    assert len(result_json(preview)) <= 12_000
    [model_return] = [
        part for message in seen[1][0] for part in message.parts if isinstance(part, ToolReturnPart)
    ]
    assert model_return.content == preview

    async with db_session_factory() as db:
        await set_session_tenant_context(
            db, workspace_id=context.workspace_id, user_id=context.user_id
        )
        file = await db.get(File, UUID(preview["file_id"]))
        assert file.is_tool_result and file.folder_id is None
        revision = await db.get(FileRevision, file.current_revision_id)
        saved = await get_storage_provider().get_object(file_revision_ref(revision))
    saved_results = json.loads(saved)["results"]
    full = saved_results[0]["data"]
    if failure:
        assert saved_results[1]["error_code"] == error_code
    assert full["row_count"] == len(full["rows"]) == 1_500
    assert full["rows"][-1]["keys"]["campaign_id"] == "1499"
    assert sum(row["metrics"]["impressions"] for row in full["rows"]) == 1_124_250
    assert sum(row["metrics"]["spend"] for row in full["rows"]) == 3_750
    assert all(
        row["actions"]["actions"][0]["custom_conversion_name"] == "Qualified lead"
        and row["actions"]["actions"][0]["custom_conversion_id"] == "901"
        for row in full["rows"]
    )
    assert sum(row["actions"]["actions"][0]["value"] for row in full["rows"]) == 3_000
    assert len(saved) > 12_000

    followup = await run_scenario(
        db_session_factory,
        await next_scenario_run(db_session_factory, context),
        model=scripted_model(
            turns=[
                ToolTurn(
                    (
                        ToolCall(
                            "read_file",
                            {
                                "file_id": preview["file_reference"],
                                "offset": len(saved) - 2_000,
                                "max_bytes": 2_000,
                            },
                        ),
                    )
                ),
                "Final campaign inspected.",
            ]
        ),
        prompt="Inspect the last campaign in the saved report.",
    )
    assert followup.run.status == "completed"
    assert "1499" in str(followup.tool_returns("read_file")[0]["content"])


async def test_account_reads_dispatch_with_isolated_failures_and_safe_audits(
    db_session_factory, monkeypatch, insights_runtime
):
    from integrations.meta_ads.tools import TOOL_DEFINITIONS

    definitions = [item for item in TOOL_DEFINITIONS if item.name != DEFINITION.name]
    for definition in definitions:
        monkeypatch.setitem(
            RUNTIME_TOOL_CATALOG,
            definition.name,
            replace(definition, availability_check=lambda: True),
        )
    monkeypatch.setattr(
        "services.agents.runtime.execute.setup.resolve_active_context",
        AsyncMock(
            return_value=ResolvedActiveContext(entries=(context_entry("111"), context_entry("222")))
        ),
    )
    requests = []

    def respond(request):
        path = request.url.path.removeprefix(f"/{META_GRAPH_API_VERSION}/")
        requests.append(path)
        assert request.method == "GET"
        if path.startswith("act_222"):
            return httpx2.Response(400, json={"error": {"code": 190, "message": "Expired token"}})
        if path == "act_111":
            payload = {"name": "Account name", "currency": "EUR", "account_status": 1}
        elif path == "act_111/campaigns":
            payload = {"data": [{"id": "801", "name": "Campaign name", "status": "PAUSED"}]}
        elif path == "act_111/activities":
            payload = {
                "data": [
                    {
                        "event_time": f"{TODAY}T09:00:00+0000",
                        "object_id": "801",
                        "object_name": "Campaign name",
                        "actor_name": "Actor name",
                        "extra_data": json.dumps({"old_value": "Paused", "new_value": "Active"}),
                    }
                ]
            }
        elif path == "act_111/insights":
            payload = {
                "data": [
                    {
                        "date_start": TODAY,
                        "date_stop": TODAY,
                        "conversions": [
                            {
                                "action_type": "offsite_conversion.fb_pixel_custom.Event name",
                                "value": "3",
                            }
                        ],
                    }
                ]
            }
        else:
            assert path == "act_111/customconversions"
            payload = {
                "data": [{"id": "901", "name": "Conversion name", "description": "Private rule"}]
            }
        return httpx2.Response(200, json=payload)

    context = await build_scenario_agent(
        db_session_factory, tool_names=[item.name for item in definitions]
    )
    calls = [
        ToolCall("meta_ads_get_accounts", {}),
        ToolCall("meta_ads_list_objects", {"object_type": "campaign"}),
        ToolCall("meta_ads_list_conversions", {}),
        ToolCall("meta_ads_list_activities", {"since": TODAY, "until": TODAY}),
    ]
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:
        provider = MetaAdsClient(AsyncMock(return_value="test-meta-token"), client=http)
        for module in (
            "get_accounts",
            "list_objects",
            "list_conversions",
            "list_activities",
        ):
            monkeypatch.setattr(
                f"integrations.meta_ads.tools.{module}.meta_ads_client",
                AsyncMock(return_value=provider),
            )
        result = await run_scenario(
            db_session_factory,
            context,
            model=scripted_model(turns=[ToolTurn(tuple(calls)), "Account details ready."]),
        )
    assert result.run.status == "completed"
    reports = [result.tool_returns(call.name)[0]["content"] for call in calls]
    for report in reports:
        assert [item["status"] for item in report["results"]] == ["success", "error"], report
        assert report["results"][1]["error_code"] == "IntegrationAuthError"
    assert reports[0]["results"][0]["data"]["name"] == "Account name"
    assert reports[1]["results"][0]["data"]["objects"][0]["name"] == "Campaign name"
    assert [item["name"] for item in reports[2]["results"][0]["data"]["conversions"]] == [
        "Conversion name",
        "Event name",
    ]
    change = reports[3]["results"][0]["data"]["events"][0]
    assert (change["actor_name"], change["old_value"], change["new_value"]) == (
        "Actor name",
        "Paused",
        "Active",
    )
    operations = [row for row in result.audit_rows if row.resource_type == "integration_resource"]
    assert len(operations) == 8
    assert [row.status for row in operations].count("success") == 4
    expected_fields = {
        "get_account": {"account_count": 1},
        "list_objects": {
            "object_type": "campaign",
            "statuses": ["ACTIVE", "PAUSED"],
            "object_count": 1,
        },
        "list_conversions": {"conversion_count": 2, "custom_event_count": 1},
        "list_activities": {
            "since": TODAY,
            "until": TODAY,
            "object_id_count": 0,
            "event_count": 1,
        },
    }
    for row in operations:
        if row.status == "success":
            fields = row.details["operation_detail"]["intent_groups"][0]["items"][0]["fields"]
            assert fields == expected_fields[row.details["provider_operation"]]
    details = json.dumps([row.details for row in operations])
    for text in (
        "Account name",
        "Campaign name",
        "Conversion name",
        "Private rule",
        "Event name",
        "Actor name",
        "Paused",
        "test-meta-token",
    ):
        assert text not in details
    assert sorted(requests) == sorted(
        [
            f"act_{account}{suffix}"
            for account in ("111", "222")
            for suffix in ("", "/campaigns", "/customconversions", "/activities")
        ]
        + ["act_111/insights"]
    )


async def test_account_listings_retain_complete_named_results(
    db_session_factory, monkeypatch, insights_runtime
):
    from integrations.meta_ads.tools import TOOL_DEFINITIONS

    definition = next(item for item in TOOL_DEFINITIONS if item.name == "meta_ads_list_objects")
    monkeypatch.setitem(
        RUNTIME_TOOL_CATALOG,
        definition.name,
        replace(definition, availability_check=lambda: True, max_public_result_chars=12_000),
    )
    total = 500
    records = [{"id": str(index + 1), "name": f"Named item {index}"} for index in range(total)]

    def respond(request):
        assert request.url.path == f"/{META_GRAPH_API_VERSION}/act_111/campaigns"
        offset = int(request.url.params.get("after", "0"))
        limit = int(request.url.params["limit"])
        payload = {"data": records[offset : offset + limit]}
        if offset + limit < len(records):
            payload["paging"] = {
                "next": f"https://graph.facebook.com{request.url.path}?after={offset + limit}"
            }
        return httpx2.Response(200, json=payload)

    context = await build_scenario_agent(db_session_factory, tool_names=[definition.name])
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:
        provider = MetaAdsClient(AsyncMock(return_value="test-meta-token"), client=http)
        monkeypatch.setattr(
            "integrations.meta_ads.tools.list_objects.meta_ads_client",
            AsyncMock(return_value=provider),
        )
        args = {"limit": total, "object_type": "campaign"}
        result = await run_scenario(
            db_session_factory,
            context,
            model=scripted_model(
                turns=[ToolTurn((ToolCall(definition.name, args),)), "The full list is saved."]
            ),
        )
    assert result.run.status == "completed"
    preview = result.tool_returns(definition.name)[0]["content"]
    assert preview["preview"] is True
    assert preview["lists"] == {"results.0.data.objects": {"total": total, "shown": 10}}
    assert preview["data"]["results"][0]["data"]["objects"][0]["name"] == "Named item 0"
    async with db_session_factory() as db:
        await set_session_tenant_context(
            db, workspace_id=context.workspace_id, user_id=context.user_id
        )
        file = await db.get(File, UUID(preview["file_id"]))
        revision = await db.get(FileRevision, file.current_revision_id)
        saved = await get_storage_provider().get_object(file_revision_ref(revision))
    full = json.loads(saved)["results"][0]["data"]["objects"]
    assert len(full) == total
    assert full[-1]["name"] == f"Named item {total - 1}"
