# apps/api/tests/integrations/google_ads/test_google_ads_provider.py

"""Google Ads discovery, REST operation, and service-account contracts."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs
from uuid import uuid4

import httpx2
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)
from pydantic import SecretStr
from pydantic_ai import ModelRetry

from integrations.google_ads.client import GoogleAdsClient
from integrations.google_ads.discover_resources import discover_google_ads_resources
from integrations.google_ads.entity_resolvers.campaign import (
    _choice as campaign_choice,
    resolve_google_ads_campaigns,
    search_google_ads_campaigns,
)
from integrations.google_ads.operations.create_negative_keyword_list import (
    create_negative_keyword_list,
)
from integrations.google_ads.operations.list_accounts import list_accounts
from integrations.google_ads.operations.run_report import run_report
from integrations.google_ads.operations.update_campaign_status import update_campaign_status
from integrations.google_ads.operations.utils import bounded_query, stream_rows
from integrations.google_ads.references import GoogleAdsCampaignReference
from integrations.google_ads.tools.create_negative_keyword_list import (
    google_ads_create_negative_keyword_list,
)
from integrations.google_ads.tools.list_accounts import google_ads_list_accounts
from integrations.google_ads.tools.run_report import google_ads_run_report
from integrations.google_ads.tools.update_campaign_status import google_ads_update_campaign_status
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry
from services.integrations.credentials.google_service_account import (
    GOOGLE_TOKEN_URL,
    GoogleServiceAccountTokenProvider,
    parse_google_service_account_json,
)


async def test_client_routes_login_customer_id_from_each_request() -> None:
    seen_headers: list[httpx2.Headers] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen_headers.append(request.headers)
        return httpx2.Response(200, json={"results": []}, request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        client = GoogleAdsClient(
            _static_token,
            developer_token=SecretStr("developer-secret"),
            client=http_client,
        )
        await client.post(
            "customers/333/googleAds:searchStream",
            operation="report",
            login_customer_id="111-111-1111",
            json={"query": "SELECT campaign.id FROM campaign"},
        )

    assert seen_headers[0]["login-customer-id"] == "1111111111"
    assert seen_headers[0]["developer-token"] == "developer-secret"


async def test_discovery_preserves_root_routing_and_immediate_parent() -> None:
    client = _DiscoveryClient()
    resources = await discover_google_ads_resources(
        client,
        principal_email="agent@example.iam.gserviceaccount.com",
    )
    by_id = {resource.external_id: resource for resource in resources}

    assert by_id["111"].parent_external_id is None
    assert by_id["222"].parent_external_id == "111"
    assert by_id["333"].parent_external_id == "222"
    assert by_id["333"].permissions_metadata["login_customer_id"] == "111"
    assert by_id["333"].permissions_metadata["level"] == 2
    assert by_id["111"].writable is False
    assert by_id["222"].writable is False
    assert by_id["333"].writable is True
    assert {call["login_customer_id"] for call in client.calls} == {"111"}
    access_queries = [call for call in client.calls if "customer_user_access" in call["query"]]
    assert [call["path"] for call in access_queries] == ["customers/111/googleAds:searchStream"]
    hierarchy_queries = [
        call for call in client.calls if "customer_user_access" not in call["query"]
    ]
    assert [call["path"] for call in hierarchy_queries] == [
        "customers/111/googleAds:searchStream",
        "customers/222/googleAds:searchStream",
    ]


async def test_discovery_keeps_accounts_read_only_for_read_only_manager_role() -> None:
    resources = await discover_google_ads_resources(
        _DiscoveryClient(manager_access_role="READ_ONLY"),
        principal_email="agent@example.iam.gserviceaccount.com",
    )
    by_id = {resource.external_id: resource for resource in resources}

    assert by_id["333"].writable is False
    assert by_id["333"].permissions_metadata["access_role"] == "READ_ONLY"


async def test_discovery_prefers_writable_manager_route_for_duplicate_account() -> None:
    resources = await discover_google_ads_resources(
        _DuplicateRouteDiscoveryClient(),
        principal_email="agent@example.iam.gserviceaccount.com",
    )
    by_id = {resource.external_id: resource for resource in resources}

    assert by_id["333"].writable is True
    assert by_id["333"].permissions_metadata["login_customer_id"] == "111"


async def test_report_caps_rows_without_model_framing() -> None:
    client = _OperationClient(
        [{"results": [{"campaign": {"name": "one"}}, {"campaign": {"name": "two"}}]}]
    )
    result = await run_report(
        client,
        customer_id="333",
        currency_code="GBP",
        login_customer_id="111",
        query="SELECT campaign.name FROM campaign",
        max_rows=1,
    )
    assert result["currency_code"] == "GBP"
    assert result["row_count"] == 1
    assert result["truncated"] is True
    assert result["rows"][0]["campaign"]["name"] == "one"
    assert client.last_json["query"].endswith("LIMIT 2")


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        (
            "SELECT campaign.id FROM campaign WHERE campaign.name = 'LIMIT 1'",
            "SELECT campaign.id FROM campaign WHERE campaign.name = 'LIMIT 1' LIMIT 3",
        ),
        ("SELECT campaign.id FROM campaign -- LIMIT 1", "SELECT campaign.id FROM campaign LIMIT 3"),
        (
            "SELECT campaign.id FROM campaign /* LIMIT 1 */",
            "SELECT campaign.id FROM campaign LIMIT 3",
        ),
        (
            "SELECT campaign.id FROM campaign LIMIT 1 ORDER BY campaign.id",
            "SELECT campaign.id FROM campaign ORDER BY campaign.id LIMIT 3",
        ),
        ("SELECT campaign.id FROM campaign LIMIT 2", "SELECT campaign.id FROM campaign LIMIT 2"),
        ("SELECT campaign.id FROM campaign LIMIT 20", "SELECT campaign.id FROM campaign LIMIT 3"),
    ],
)
def test_bounded_query_enforces_one_terminal_clause(query: str, expected: str) -> None:
    assert bounded_query(query, max_rows=2) == expected


def test_stream_rows_stops_collecting_at_budget() -> None:
    class OversizedResults(list[dict]):
        def __iter__(self):
            for index, item in enumerate(super().__iter__()):
                if index >= 3:
                    raise AssertionError("stream_rows read beyond its row budget")
                yield item

    results = OversizedResults({"campaign": {"id": str(index)}} for index in range(100))
    payload = [{"results": results}, {"results": [{"campaign": {"id": "unreachable"}}]}]

    assert stream_rows(payload, max_rows=3) == results[:3]


async def test_report_tool_rejects_non_select_gaql_before_dispatch() -> None:
    with pytest.raises(ModelRetry, match="requires a GAQL SELECT query"):
        await google_ads_run_report(None, "UPDATE campaign SET status = 'PAUSED'")  # type: ignore[arg-type]


async def test_report_tool_uses_discovered_account_currency(monkeypatch) -> None:
    entry = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="google_ads",
        resource_type="google_ads_account",
        external_id="333",
        display_name="Client account",
        connection_id=uuid4(),
        connection_label="Agency",
        connection_status="active",
        write_allowed=True,
        permissions_metadata={"currency_code": "GBP", "login_customer_id": "111"},
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(entry,)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        )
    )
    provider_report = AsyncMock(
        return_value={
            "currency_code": "GBP",
            "rows": [],
            "row_count": 0,
            "truncated": False,
            "truncation_note": None,
        }
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.run_report.google_ads_client",
        AsyncMock(return_value=object()),
    )
    monkeypatch.setattr("integrations.google_ads.tools.run_report.run_report", provider_report)
    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.record_integration_operation_audit_event",
        AsyncMock(),
    )

    result = await google_ads_run_report(ctx, "SELECT campaign.id FROM campaign")

    assert result["results"][0]["data"]["currency_code"] == "GBP"
    assert provider_report.await_args.kwargs["currency_code"] == "GBP"


async def test_list_accounts_queries_only_the_selected_active_context_resource() -> None:
    connection_id = uuid4()
    selected_resource_id = uuid4()
    selected = SimpleNamespace(
        external_id="333",
        display_name="Selected account",
        parent_external_id="111",
        permissions_metadata={
            "manager": False,
            "currency_code": "GBP",
            "status": "ENABLED",
        },
        writable=True,
        enabled=True,
    )
    db = AsyncMock()
    db.scalar.return_value = selected

    result = await list_accounts(
        db,
        connection_id=connection_id,
        integration_resource_id=selected_resource_id,
    )

    statement = db.scalar.await_args.args[0]
    assert statement.compile().params == {
        "id_1": selected_resource_id,
        "connection_id_1": connection_id,
        "resource_type_1": "google_ads_account",
    }
    assert result["accounts"] == [
        {
            "customer_id": "333",
            "display_name": "Selected account",
            "parent_customer_id": "111",
            "manager": False,
            "currency_code": "GBP",
            "status": "ENABLED",
            "writable": True,
            "enabled": True,
        }
    ]


async def test_list_accounts_tool_scopes_each_result_to_its_context_entry(monkeypatch) -> None:
    connection_id = uuid4()
    entries = tuple(
        ResolvedContextEntry(
            integration_resource_id=uuid4(),
            provider_key="google_ads",
            resource_type="google_ads_account",
            external_id=customer_id,
            display_name=f"Account {customer_id}",
            connection_id=connection_id,
            connection_label="Agency",
            connection_status="active",
            write_allowed=True,
            permissions_metadata={"login_customer_id": customer_id},
        )
        for customer_id in ("222", "333")
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            db=object(),
            active_context=ResolvedActiveContext(entries=entries),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        )
    )
    operation = AsyncMock(
        side_effect=[
            {"accounts": [{"customer_id": "222"}]},
            {"accounts": [{"customer_id": "333"}]},
        ]
    )
    monkeypatch.setattr("integrations.google_ads.tools.list_accounts.list_accounts", operation)
    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.record_integration_operation_audit_event",
        AsyncMock(),
    )

    result = await google_ads_list_accounts(ctx)

    assert [item["data"]["accounts"][0]["customer_id"] for item in result["results"]] == [
        "222",
        "333",
    ]
    assert [call.kwargs["integration_resource_id"] for call in operation.await_args_list] == [
        entry.integration_resource_id for entry in entries
    ]


async def test_mutate_uses_partial_failure_and_surfaces_campaign_error() -> None:
    payload = {
        "results": [{"resourceName": "customers/333/campaigns/10"}],
        "partialFailureError": {
            "details": [
                {
                    "errors": [
                        {
                            "message": "Campaign is removed",
                            "errorCode": {"campaignError": "CANNOT_MODIFY_REMOVED_CAMPAIGN"},
                            "location": {
                                "fieldPathElements": [{"fieldName": "operations", "index": 1}]
                            },
                        }
                    ]
                }
            ]
        },
    }
    client = _OperationClient(payload)
    result = await update_campaign_status(
        client,
        customer_id="333",
        login_customer_id="111",
        campaign_ids=["10", "20"],
        status="PAUSED",
    )
    assert client.last_json["partialFailure"] is True
    assert client.last_login_customer_id == "111"
    assert result["resource_names"] == ["customers/333/campaigns/10"]
    assert result["campaign_errors"][0]["campaign_id"] == "20"
    assert result["campaign_errors"][0]["error_code"] == "CANNOT_MODIFY_REMOVED_CAMPAIGN"


async def test_create_negative_keyword_list_skips_existing_and_maps_partial_failure() -> None:
    client = _NegativeKeywordListClient(
        search_payload=[
            {
                "results": [
                    {"sharedSet": {"id": "1", "name": "Existing List"}},
                ]
            }
        ],
        mutate_payload={
            "results": [{"resourceName": "customers/333/sharedSets/10"}, {}],
            "partialFailureError": {
                "details": [
                    {
                        "errors": [
                            {
                                "message": "A list with this name is not allowed",
                                "errorCode": {"sharedSetError": "INVALID_NAME"},
                                "location": {
                                    "fieldPathElements": [{"fieldName": "operations", "index": 1}]
                                },
                            }
                        ]
                    }
                ]
            },
        },
    )

    result = await create_negative_keyword_list(
        client,
        customer_id="333-333-3333",
        login_customer_id="111-111-1111",
        names=["existing list", "Created List", "Rejected List"],
    )

    assert client.calls[0] == {
        "path": "customers/3333333333/googleAds:searchStream",
        "operation": "list_negative_keyword_lists",
        "login_customer_id": "111-111-1111",
        "json": {
            "query": (
                "SELECT shared_set.id, shared_set.name FROM shared_set "
                "WHERE shared_set.type = 'NEGATIVE_KEYWORDS' "
                "AND shared_set.status != 'REMOVED'"
            )
        },
    }
    assert client.calls[1]["path"] == "customers/3333333333/sharedSets:mutate"
    assert client.calls[1]["json"] == {
        "operations": [
            {"create": {"name": "Created List", "type": "NEGATIVE_KEYWORDS"}},
            {"create": {"name": "Rejected List", "type": "NEGATIVE_KEYWORDS"}},
        ],
        "partialFailure": True,
    }
    assert result == {
        "created_names": ["Created List"],
        "resource_names": ["customers/333/sharedSets/10"],
        "skipped_existing": ["existing list"],
        "list_errors": [
            {
                "name": "Rejected List",
                "message": "A list with this name is not allowed",
                "error_code": "INVALID_NAME",
            }
        ],
    }


async def test_create_negative_keyword_list_avoids_mutate_when_every_name_exists() -> None:
    client = _NegativeKeywordListClient(
        search_payload={
            "results": [
                {"sharedSet": {"id": "1", "name": "Existing List"}},
            ]
        },
        mutate_payload={"results": []},
    )

    result = await create_negative_keyword_list(
        client,
        customer_id="333",
        login_customer_id="111",
        names=["EXISTING LIST"],
    )

    assert len(client.calls) == 1
    assert result == {
        "created_names": [],
        "resource_names": [],
        "skipped_existing": ["EXISTING LIST"],
        "list_errors": [],
    }


async def test_create_negative_keyword_list_normalizes_and_fans_out_by_account(
    monkeypatch,
) -> None:
    entries = tuple(
        ResolvedContextEntry(
            integration_resource_id=uuid4(),
            provider_key="google_ads",
            resource_type="google_ads_account",
            external_id=customer_id,
            display_name=f"Account {customer_id}",
            connection_id=uuid4(),
            connection_label="Agency",
            connection_status="active",
            write_allowed=True,
            permissions_metadata={"login_customer_id": "999"},
        )
        for customer_id in ("111", "222")
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=entries))
    )
    provider_create = AsyncMock(
        side_effect=lambda _client, **kwargs: {
            "created_names": ["Alpha List", "Beta List"],
            "resource_names": [f"customers/{kwargs['customer_id']}/sharedSets/1"],
            "skipped_existing": [],
            "list_errors": [],
        }
    )

    async def passthrough_audit(_ctx, _entry, **kwargs):
        return await kwargs["execute"]()

    monkeypatch.setattr(
        "integrations.google_ads.tools.create_negative_keyword_list.google_ads_client",
        AsyncMock(return_value=object()),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.create_negative_keyword_list.create_negative_keyword_list",
        provider_create,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.create_negative_keyword_list.run_audited_operation",
        passthrough_audit,
    )

    result = await google_ads_create_negative_keyword_list(
        ctx,
        ["  Alpha   List  ", "", "alpha list", " Beta List "],
    )

    assert [item["status"] for item in result["results"]] == ["success", "success"]
    assert [call.kwargs["customer_id"] for call in provider_create.await_args_list] == [
        "111",
        "222",
    ]
    assert all(
        call.kwargs["names"] == ["Alpha List", "Beta List"]
        for call in provider_create.await_args_list
    )


@pytest.mark.parametrize("names", [[], ["  ", "\t"], ["x" * 256], ["é" * 128]])
async def test_create_negative_keyword_list_retries_invalid_names(names: list[str]) -> None:
    with pytest.raises(ModelRetry):
        await google_ads_create_negative_keyword_list(None, names)  # type: ignore[arg-type]


async def test_create_negative_keyword_list_write_denial_is_audited_before_provider_call(
    monkeypatch,
) -> None:
    entry = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="google_ads",
        resource_type="google_ads_account",
        external_id="333",
        display_name="Read-only account",
        connection_id=uuid4(),
        connection_label="Agency",
        connection_status="active",
        write_allowed=False,
        permissions_metadata={"login_customer_id": "111"},
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(entry,)))
    )
    provider_client = AsyncMock()
    audit = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.create_negative_keyword_list.google_ads_client",
        provider_client,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.create_negative_keyword_list.record_google_ads_operation_audit",
        audit,
    )

    result = await google_ads_create_negative_keyword_list(ctx, ["New List"])

    assert result["results"][0]["error_code"] == "write_not_permitted"
    provider_client.assert_not_awaited()
    audit.assert_awaited_once()
    assert audit.await_args.kwargs["status"].value == "failure"
    assert audit.await_args.kwargs["error_code"] == "write_not_permitted"


def test_campaign_reference_truncates_long_name() -> None:
    choice = campaign_choice(
        SimpleNamespace(integration_resource_id=uuid4(), display_name="Ads account"),
        {"id": "10", "name": "x" * 800, "status": "ENABLED"},
    )

    assert choice is not None
    assert choice.label == "x" * 500
    assert choice.value["label"] == "x" * 500


async def test_campaign_search_bounds_pagination_and_filters_active_scope(monkeypatch) -> None:
    active = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="google_ads",
        resource_type="google_ads_account",
        external_id="111",
        display_name="Ads account",
        connection_id=uuid4(),
        connection_label="Agency",
        connection_status="active",
        write_allowed=True,
        permissions_metadata={"login_customer_id": "999"},
    )
    second_active = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="google_ads",
        resource_type="google_ads_account",
        external_id="222",
        display_name="Second ads account",
        connection_id=uuid4(),
        connection_label="Agency",
        connection_status="active",
        write_allowed=True,
        permissions_metadata={"login_customer_id": "999"},
    )
    incompatible = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="gmail",
        resource_type="gmail_mailbox",
        external_id="owner@example.com",
        display_name="Mailbox",
        connection_id=uuid4(),
        connection_label="Gmail",
        connection_status="active",
        write_allowed=True,
    )
    ctx = SimpleNamespace(
        db=object(),
        actor=object(),
        workspace=object(),
        active_context=ResolvedActiveContext(entries=(active, second_active, incompatible)),
    )
    query = AsyncMock(
        return_value=[
            {"id": str(index), "name": f"Campaign {index}", "status": "ENABLED"}
            for index in range(101)
        ]
    )
    monkeypatch.setattr("integrations.google_ads.entity_resolvers.campaign._query", query)

    page = await search_google_ads_campaigns(ctx, "Campaign", {}, 25, "100")

    assert [choice.value["external_id"] for choice in page.choices] == ["100"]
    assert page.next_cursor is None
    assert [call.args[1] for call in query.await_args_list] == [active, second_active]
    assert all("LIKE '%Campaign%'" in call.args[2] for call in query.await_args_list)
    assert all("LIMIT 101" in call.args[2] for call in query.await_args_list)


async def test_campaign_hydration_rejects_stale_and_inactive_scope(monkeypatch) -> None:
    active = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="google_ads",
        resource_type="google_ads_account",
        external_id="111",
        display_name="Ads account",
        connection_id=uuid4(),
        connection_label="Agency",
        connection_status="active",
        write_allowed=True,
        permissions_metadata={"login_customer_id": "999"},
    )
    ctx = SimpleNamespace(
        db=object(),
        actor=object(),
        workspace=object(),
        active_context=ResolvedActiveContext(entries=(active,)),
    )
    query = AsyncMock(return_value=[{"id": "10", "name": "Current campaign", "status": "ENABLED"}])
    monkeypatch.setattr("integrations.google_ads.entity_resolvers.campaign._query", query)

    choices = await resolve_google_ads_campaigns(
        ctx,
        [
            GoogleAdsCampaignReference(
                integration_resource_id=active.integration_resource_id,
                external_id="10",
                label="Current campaign",
            ),
            GoogleAdsCampaignReference(
                integration_resource_id=active.integration_resource_id,
                external_id="20",
                label="Deleted campaign",
            ),
            GoogleAdsCampaignReference(
                integration_resource_id=uuid4(),
                external_id="30",
                label="Inactive account",
            ),
        ],
        {},
    )

    assert [choice.value["external_id"] for choice in choices] == ["10"]
    query.assert_awaited_once()
    assert "campaign.id IN (10, 20)" in query.await_args.args[2]


async def test_campaign_update_groups_ids_by_referenced_customer(monkeypatch) -> None:
    entries = tuple(
        ResolvedContextEntry(
            integration_resource_id=uuid4(),
            provider_key="google_ads",
            resource_type="google_ads_account",
            external_id=customer_id,
            display_name=f"Account {customer_id}",
            connection_id=uuid4(),
            connection_label="Agency",
            connection_status="active",
            write_allowed=True,
            permissions_metadata={"login_customer_id": customer_id},
        )
        for customer_id in ("111", "222")
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=entries))
    )
    client = AsyncMock()

    async def lookup(_path, **kwargs):
        query = kwargs["json"]["query"]
        campaign_id = "10" if "10" in query else "20"
        return {"results": [{"campaign": {"id": campaign_id}}]}

    client.post.side_effect = lookup
    provider_update = AsyncMock(
        side_effect=lambda _client, **kwargs: {
            "resource_names": [
                f"customers/{kwargs['customer_id']}/campaigns/{campaign_id}"
                for campaign_id in kwargs["campaign_ids"]
            ]
        }
    )

    async def passthrough_audit(_ctx, _entry, **kwargs):
        return await kwargs["execute"]()

    monkeypatch.setattr(
        "integrations.google_ads.tools.update_campaign_status.google_ads_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.update_campaign_status.update_campaign_status",
        provider_update,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.update_campaign_status.run_audited_operation",
        passthrough_audit,
    )

    result = await google_ads_update_campaign_status(
        ctx,
        [
            GoogleAdsCampaignReference(
                integration_resource_id=entries[0].integration_resource_id,
                external_id="10",
                label="First campaign",
            ),
            GoogleAdsCampaignReference(
                integration_resource_id=entries[1].integration_resource_id,
                external_id="20",
                label="Second campaign",
            ),
        ],
        "PAUSED",
    )

    assert len(result["results"]) == 2
    assert [item["status"] for item in result["results"]] == ["success", "success"], [
        item["error_message"] for item in result["results"]
    ]
    assert [call.kwargs["customer_id"] for call in provider_update.await_args_list] == [
        "111",
        "222",
    ]
    assert [call.kwargs["campaign_ids"] for call in provider_update.await_args_list] == [
        ["10"],
        ["20"],
    ]


async def test_campaign_update_fails_closed_when_pre_mutation_lookup_is_stale(
    monkeypatch,
) -> None:
    entry = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="google_ads",
        resource_type="google_ads_account",
        external_id="111",
        display_name="Ads account",
        connection_id=uuid4(),
        connection_label="Agency",
        connection_status="active",
        write_allowed=True,
        permissions_metadata={"login_customer_id": "999"},
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(entry,)))
    )
    client = AsyncMock()
    client.post.return_value = {"results": [{"campaign": {"id": "10", "name": "Still available"}}]}
    provider_update = AsyncMock()

    async def passthrough_audit(_ctx, _entry, **kwargs):
        return await kwargs["execute"]()

    monkeypatch.setattr(
        "integrations.google_ads.tools.update_campaign_status.google_ads_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.update_campaign_status.update_campaign_status",
        provider_update,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.update_campaign_status.run_audited_operation",
        passthrough_audit,
    )

    result = await google_ads_update_campaign_status(
        ctx,
        [
            GoogleAdsCampaignReference(
                integration_resource_id=entry.integration_resource_id,
                external_id="10",
                label="Still available",
            ),
            GoogleAdsCampaignReference(
                integration_resource_id=entry.integration_resource_id,
                external_id="20",
                label="Deleted before approval",
            ),
        ],
        "PAUSED",
    )

    assert result["results"][0]["status"] == "error"
    assert result["results"][0]["error_code"] == "ModelRetry"
    assert "campaign is unavailable" in result["results"][0]["error_message"]
    provider_update.assert_not_awaited()


async def test_service_account_assertion_claims_and_token_cache() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
    ).decode()
    raw = json.dumps(
        {
            "type": "service_account",
            "project_id": "praxis-ads",
            "client_email": "agent@example.iam.gserviceaccount.com",
            "private_key": private_pem,
            "token_uri": GOOGLE_TOKEN_URL,
        }
    )
    assertions: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        form = parse_qs(request.read().decode())
        assertions.append(form["assertion"][0])
        return httpx2.Response(
            200,
            json={"access_token": "short-lived-token", "expires_in": 3600},
            request=request,
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        provider = GoogleServiceAccountTokenProvider(
            parse_google_service_account_json(raw, provider_key="google_ads"),
            provider_key="google_ads",
            scope="https://www.googleapis.com/auth/adwords",
            client=http_client,
        )
        assert await provider.access_token() == "short-lived-token"
        assert await provider.access_token() == "short-lived-token"

    assert len(assertions) == 1
    claims = jwt.decode(
        assertions[0],
        private_key.public_key(),
        algorithms=["RS256"],
        audience=GOOGLE_TOKEN_URL,
    )
    assert claims["iss"] == "agent@example.iam.gserviceaccount.com"
    assert claims["sub"] == "agent@example.iam.gserviceaccount.com"
    assert claims["scope"] == "https://www.googleapis.com/auth/adwords"
    assert private_pem not in assertions[0]


def test_service_account_validation_never_echoes_secret() -> None:
    secret = "private-key-must-not-leak"
    with pytest.raises(Exception) as exc_info:
        parse_google_service_account_json(
            json.dumps({"private_key": secret}),
            provider_key="google_ads",
        )
    assert secret not in str(exc_info.value)


async def _static_token(_force: bool) -> str:
    return "access-token"


class _DiscoveryClient:
    def __init__(self, *, manager_access_role: str = "STANDARD") -> None:
        self.calls: list[dict[str, str]] = []
        self.manager_access_role = manager_access_role

    async def get(self, _path: str, **_kwargs):
        return {"resourceNames": ["customers/111"]}

    async def post(self, path: str, **kwargs):
        query = kwargs["json"]["query"]
        self.calls.append(
            {
                "path": path,
                "login_customer_id": kwargs["login_customer_id"],
                "query": query,
            }
        )
        if "customer_user_access" in query:
            customer_id = path.split("/")[1]
            if customer_id != "111":
                return [{"results": []}]
            return [
                {
                    "results": [
                        {
                            "customerUserAccess": {
                                "emailAddress": "agent@example.iam.gserviceaccount.com",
                                "accessRole": self.manager_access_role,
                            }
                        }
                    ]
                }
            ]
        customer_id = path.split("/")[1]
        if customer_id == "111":
            return [_hierarchy_page(("111", 0, True), ("222", 1, True))]
        if customer_id == "222":
            return [_hierarchy_page(("222", 0, True), ("333", 1, False))]
        return [_hierarchy_page((customer_id, 0, False))]


class _DuplicateRouteDiscoveryClient(_DiscoveryClient):
    async def get(self, _path: str, **_kwargs):
        return {"resourceNames": ["customers/333", "customers/111"]}

    async def post(self, path: str, **kwargs):
        query = kwargs["json"]["query"]
        if "customer_user_access" in query and path.startswith("customers/333/"):
            return [
                {
                    "results": [
                        {
                            "customerUserAccess": {
                                "emailAddress": "agent@example.iam.gserviceaccount.com",
                                "accessRole": "READ_ONLY",
                            }
                        }
                    ]
                }
            ]
        if "customer_user_access" not in query and path.startswith("customers/333/"):
            return [_hierarchy_page(("333", 0, False))]
        return await super().post(path, **kwargs)


class _OperationClient:
    def __init__(self, payload):
        self.payload = payload
        self.last_json = None
        self.last_login_customer_id = None

    async def post(self, _path: str, **kwargs):
        self.last_json = kwargs["json"]
        self.last_login_customer_id = kwargs["login_customer_id"]
        return self.payload


class _NegativeKeywordListClient:
    def __init__(self, *, search_payload, mutate_payload):
        self.search_payload = search_payload
        self.mutate_payload = mutate_payload
        self.calls: list[dict] = []

    async def post(self, path: str, **kwargs):
        self.calls.append({"path": path, **kwargs})
        if path.endswith("googleAds:searchStream"):
            return self.search_payload
        if path.endswith("sharedSets:mutate"):
            return self.mutate_payload
        raise AssertionError(f"Unexpected Google Ads operation path: {path}")


def _hierarchy_page(*customers: tuple[str, int, bool]) -> dict:
    return {
        "results": [
            {
                "customerClient": {
                    "clientCustomer": f"customers/{customer_id}",
                    "level": str(level),
                    "manager": manager,
                    "descriptiveName": f"Account {customer_id}",
                    "currencyCode": "GBP",
                    "status": "ENABLED",
                }
            }
            for customer_id, level, manager in customers
        ]
    }
