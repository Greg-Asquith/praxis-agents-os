# apps/api/tests/integrations/google_ads/test_google_ads_provider.py

"""Google Ads discovery, REST operation, and service-account contracts."""

import json
from types import SimpleNamespace
from typing import Any
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
from pydantic import SecretStr, ValidationError
from pydantic_ai import (
    Agent,
    DeferredToolRequests,
    DeferredToolResults,
    ModelRetry,
    ToolApproved,
)
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from core.exceptions.general import AppValidationError
from core.exceptions.integration import IntegrationValidationError
from integrations.google_ads.client import GoogleAdsClient
from integrations.google_ads.discover_resources import discover_google_ads_resources
from integrations.google_ads.entity_resolvers.ad_group import (
    resolve_google_ads_ad_groups,
    search_google_ads_ad_groups,
)
from integrations.google_ads.entity_resolvers.campaign import (
    GOOGLE_ADS_CAMPAIGN_RESOLVER,
    _choice as campaign_choice,
    resolve_google_ads_campaigns,
    search_google_ads_campaigns,
)
from integrations.google_ads.entity_resolvers.shared_set import (
    _choice as shared_set_choice,
    resolve_google_ads_shared_sets,
    search_google_ads_shared_sets,
)
from integrations.google_ads.entity_resolvers.utils import group_scoped_references
from integrations.google_ads.operations.ad_group_negative_keywords import (
    add_ad_group_negative_keywords,
    remove_ad_group_negative_keywords,
)
from integrations.google_ads.operations.add_negative_keywords import add_negative_keywords
from integrations.google_ads.operations.campaign_negative_keywords import (
    add_campaign_negative_keywords,
    remove_campaign_negative_keywords,
)
from integrations.google_ads.operations.create_negative_keyword_list import (
    create_negative_keyword_list,
)
from integrations.google_ads.operations.link_negative_keyword_list import (
    link_negative_keyword_list,
)
from integrations.google_ads.operations.list_accounts import list_accounts
from integrations.google_ads.operations.list_ad_groups import list_ad_groups
from integrations.google_ads.operations.list_campaigns import list_campaigns
from integrations.google_ads.operations.list_shared_sets import list_shared_sets
from integrations.google_ads.operations.remove_negative_keywords import (
    remove_negative_keywords,
)
from integrations.google_ads.operations.run_report import run_report
from integrations.google_ads.operations.update_campaign_status import update_campaign_status
from integrations.google_ads.operations.utils import (
    bounded_query,
    escape_gaql_like_literal,
    stream_rows,
)
from integrations.google_ads.references import (
    GoogleAdsAdGroupReference,
    GoogleAdsCampaignReference,
    GoogleAdsSharedSetReference,
)
from integrations.google_ads.tools.add_ad_group_negative_keywords import (
    google_ads_add_ad_group_negative_keywords,
)
from integrations.google_ads.tools.add_campaign_negative_keywords import (
    google_ads_add_campaign_negative_keywords,
)
from integrations.google_ads.tools.add_negative_keywords import (
    _negative_keyword_operation_detail,
    google_ads_add_negative_keywords,
)
from integrations.google_ads.tools.create_negative_keyword_list import (
    google_ads_create_negative_keyword_list,
)
from integrations.google_ads.tools.link_negative_keyword_list import (
    google_ads_link_negative_keyword_list,
)
from integrations.google_ads.tools.list_accounts import google_ads_list_accounts
from integrations.google_ads.tools.remove_ad_group_negative_keywords import (
    google_ads_remove_ad_group_negative_keywords,
)
from integrations.google_ads.tools.remove_campaign_negative_keywords import (
    google_ads_remove_campaign_negative_keywords,
)
from integrations.google_ads.tools.remove_negative_keywords import (
    _operation_detail as removal_operation_detail,
    google_ads_remove_negative_keywords,
)
from integrations.google_ads.tools.run_report import google_ads_run_report
from integrations.google_ads.tools.schemas.negative_keyword import (
    NegativeKeywordEntry,
    NegativeKeywordRemovalEntry,
)
from integrations.google_ads.tools.update_campaign_status import (
    DEFINITION as GOOGLE_ADS_UPDATE_CAMPAIGN_STATUS_DEFINITION,
    google_ads_update_campaign_status,
)
from integrations.google_ads.tools.utils import (
    GOOGLE_ADS_BINDING,
    MAX_NEGATIVE_KEYWORD_PUBLIC_RESULT_CHARS,
    MAX_NEGATIVE_KEYWORD_RESULT_CHARS,
    bounded_negative_keyword_removal_result,
    bounded_negative_keyword_result,
    complete_negative_keyword_removal_result,
    complete_negative_keyword_result,
    normalize_negative_keywords,
    run_audited_operation,
)
from integrations.google_ads.tools.verifiers import (
    verify_ad_groups,
    verify_campaigns,
    verify_shared_sets,
)
from services.agent_runs.validate_override_args import validate_and_canonicalize_override_args
from services.audit_events import AuditStatus
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
        "integrations.google_ads.tools.utils.audit.record_integration_operation_audit_event",
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
        "integrations.google_ads.tools.utils.audit.record_integration_operation_audit_event",
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


async def test_link_negative_keyword_list_skips_existing_and_maps_failures() -> None:
    client = _CampaignSharedSetClient(
        search_payload={
            "results": [
                {
                    "campaignSharedSet": {
                        "campaign": "customers/3333333333/campaigns/10",
                        "sharedSet": "customers/3333333333/sharedSets/50",
                        "status": "ENABLED",
                    }
                }
            ]
        },
        mutate_payload={
            "results": [
                {"resourceName": "customers/3333333333/campaignSharedSets/20~50"},
                {},
            ],
            "partialFailureError": {
                "details": [
                    {
                        "errors": [
                            {
                                "message": "Campaign is removed",
                                "errorCode": {"campaignSharedSetError": "CAMPAIGN_REMOVED"},
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

    result = await link_negative_keyword_list(
        client,
        customer_id="333-333-3333",
        login_customer_id="111-111-1111",
        shared_set_id="50",
        campaign_ids=["10", "20", "30"],
        action="LINK",
    )

    assert client.calls[0]["json"]["query"] == (
        "SELECT campaign_shared_set.campaign, campaign_shared_set.shared_set, "
        "campaign_shared_set.status "
        "FROM campaign_shared_set WHERE campaign_shared_set.shared_set = "
        "'customers/3333333333/sharedSets/50' AND campaign_shared_set.status = 'ENABLED'"
    )
    assert client.calls[1] == {
        "path": "customers/3333333333/campaignSharedSets:mutate",
        "operation": "link_negative_keyword_list",
        "login_customer_id": "111-111-1111",
        "json": {
            "operations": [
                {
                    "create": {
                        "campaign": "customers/3333333333/campaigns/20",
                        "sharedSet": "customers/3333333333/sharedSets/50",
                    }
                },
                {
                    "create": {
                        "campaign": "customers/3333333333/campaigns/30",
                        "sharedSet": "customers/3333333333/sharedSets/50",
                    }
                },
            ],
            "partialFailure": True,
        },
    }
    assert result == {
        "resource_names": ["customers/3333333333/campaignSharedSets/20~50"],
        "skipped_existing": ["10"],
        "campaign_errors": [
            {
                "campaign_id": "30",
                "message": "Campaign is removed",
                "error_code": "CAMPAIGN_REMOVED",
            }
        ],
    }


async def test_unlink_negative_keyword_list_reports_not_found_and_composes_names() -> None:
    client = _CampaignSharedSetClient(
        search_payload={
            "results": [
                {
                    "campaignSharedSet": {
                        "campaign": "customers/333/campaigns/10",
                        "sharedSet": "customers/333/sharedSets/50",
                        "status": "ENABLED",
                    }
                }
            ]
        },
        mutate_payload={
            "results": [
                {"resourceName": "customers/333/campaignSharedSets/10~50"},
            ]
        },
    )

    result = await link_negative_keyword_list(
        client,
        customer_id="333",
        login_customer_id="111",
        shared_set_id="50",
        campaign_ids=["10", "20"],
        action="UNLINK",
    )

    assert client.calls[1]["json"] == {
        "operations": [
            {"remove": "customers/333/campaignSharedSets/10~50"},
        ],
        "partialFailure": True,
    }
    assert result == {
        "resource_names": ["customers/333/campaignSharedSets/10~50"],
        "not_found": ["20"],
        "campaign_errors": [],
    }


async def test_link_negative_keyword_list_avoids_noop_mutate() -> None:
    client = _CampaignSharedSetClient(search_payload={"results": []}, mutate_payload={})

    result = await link_negative_keyword_list(
        client,
        customer_id="333",
        login_customer_id="111",
        shared_set_id="50",
        campaign_ids=["10"],
        action="UNLINK",
    )

    assert len(client.calls) == 1
    assert result == {
        "resource_names": [],
        "not_found": ["10"],
        "campaign_errors": [],
    }


async def test_link_negative_keyword_list_does_not_treat_removed_link_as_existing() -> None:
    client = _CampaignSharedSetClient(
        search_payload={
            "results": [
                {
                    "campaignSharedSet": {
                        "campaign": "customers/333/campaigns/10",
                        "sharedSet": "customers/333/sharedSets/50",
                        "status": "REMOVED",
                    }
                }
            ]
        },
        mutate_payload={"results": [{"resourceName": "customers/333/campaignSharedSets/10~50"}]},
    )

    result = await link_negative_keyword_list(
        client,
        customer_id="333",
        login_customer_id="111",
        shared_set_id="50",
        campaign_ids=["10"],
        action="LINK",
    )

    assert len(client.calls) == 2
    assert result == {
        "resource_names": ["customers/333/campaignSharedSets/10~50"],
        "skipped_existing": [],
        "campaign_errors": [],
    }


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


async def test_add_negative_keywords_skips_pairs_and_maps_partial_failures() -> None:
    client = _NegativeKeywordClient(
        search_payload={
            "results": [
                {
                    "sharedCriterion": {
                        "criterionId": "1",
                        "keyword": {"text": "Existing Term", "matchType": "EXACT"},
                    }
                }
            ]
        },
        mutate_payload={
            "results": [{"resourceName": "customers/333/sharedCriteria/10~20"}, {}],
            "partialFailureError": {
                "details": [
                    {
                        "errors": [
                            {
                                "message": "Keyword is not permitted",
                                "errorCode": {"criterionError": "INVALID_KEYWORD_TEXT"},
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

    result = await add_negative_keywords(
        client,
        customer_id="333-333-3333",
        login_customer_id="111-111-1111",
        shared_set_id="50",
        keywords=[
            {"text": "existing term", "match_type": "EXACT"},
            {"text": "Created phrase", "match_type": "PHRASE"},
            {"text": "Rejected broad", "match_type": "BROAD"},
        ],
    )

    assert (
        "shared_criterion.shared_set = 'customers/3333333333/sharedSets/50'"
        in client.calls[0]["json"]["query"]
    )
    assert client.calls[1]["path"] == "customers/3333333333/sharedCriteria:mutate"
    assert client.calls[1]["json"] == {
        "operations": [
            {
                "create": {
                    "sharedSet": "customers/3333333333/sharedSets/50",
                    "keyword": {"text": "Created phrase", "matchType": "PHRASE"},
                }
            },
            {
                "create": {
                    "sharedSet": "customers/3333333333/sharedSets/50",
                    "keyword": {"text": "Rejected broad", "matchType": "BROAD"},
                }
            },
        ],
        "partialFailure": True,
    }
    assert result == {
        "added": [
            {
                "text": "Created phrase",
                "match_type": "PHRASE",
                "resource_name": "customers/333/sharedCriteria/10~20",
            }
        ],
        "skipped_existing": [{"text": "existing term", "match_type": "EXACT"}],
        "keyword_errors": [
            {
                "scope": "keyword",
                "text": "Rejected broad",
                "match_type": "BROAD",
                "message": "Keyword is not permitted",
                "error_code": "INVALID_KEYWORD_TEXT",
            }
        ],
    }


@pytest.mark.parametrize(
    "location",
    [
        {},
        {"fieldPathElements": [{"fieldName": "operations"}]},
        {"fieldPathElements": [{"fieldName": "operations", "index": "invalid"}]},
        {"fieldPathElements": [{"fieldName": "operations", "index": 9}]},
    ],
)
async def test_add_negative_keywords_fails_closed_for_unattributed_partial_failures(
    location: dict[str, object],
) -> None:
    client = _NegativeKeywordClient(
        search_payload={"results": []},
        mutate_payload={
            "results": [{"resourceName": "customers/333/sharedCriteria/50~1"}],
            "partialFailureError": {
                "details": [
                    {
                        "errors": [
                            {
                                "message": "The account rejected part of the request",
                                "errorCode": {"requestError": "INVALID_INPUT"},
                                "location": location,
                            }
                        ]
                    }
                ]
            },
        },
    )

    result = await add_negative_keywords(
        client,
        customer_id="333",
        login_customer_id="111",
        shared_set_id="50",
        keywords=[{"text": "Created phrase", "match_type": "PHRASE"}],
    )

    assert result["added"] == []
    assert result["keyword_errors"] == [
        {
            "scope": "keyword",
            "text": "Created phrase",
            "match_type": "PHRASE",
            "message": "The account rejected part of the request",
            "error_code": "INVALID_INPUT",
        }
    ]


async def test_add_negative_keywords_preserves_message_only_partial_failure() -> None:
    client = _NegativeKeywordClient(
        search_payload={"results": []},
        mutate_payload={
            "results": [],
            "partialFailureError": {
                "code": 3,
                "message": "The request contained an unattributed failure",
            },
        },
    )

    result = await add_negative_keywords(
        client,
        customer_id="333",
        login_customer_id="111",
        shared_set_id="50",
        keywords=[{"text": "Rejected phrase", "match_type": "PHRASE"}],
    )

    assert result["keyword_errors"] == [
        {
            "scope": "keyword",
            "text": "Rejected phrase",
            "match_type": "PHRASE",
            "message": "The request contained an unattributed failure",
            "error_code": "3",
        }
    ]


async def test_add_negative_keywords_groups_diagnostics_by_operation() -> None:
    location = {"fieldPathElements": [{"fieldName": "operations", "index": 0}]}
    client = _NegativeKeywordClient(
        search_payload={"results": []},
        mutate_payload={
            "results": [{}],
            "partialFailureError": {
                "details": [
                    {
                        "errors": [
                            {
                                "message": "Keyword is not permitted",
                                "errorCode": {"criterionError": "INVALID_KEYWORD_TEXT"},
                                "location": location,
                            },
                            {
                                "message": "Remove punctuation",
                                "errorCode": {"requestError": "INVALID_INPUT"},
                                "location": location,
                            },
                        ]
                    }
                ]
            },
        },
    )

    result = await add_negative_keywords(
        client,
        customer_id="333",
        login_customer_id="111",
        shared_set_id="50",
        keywords=[{"text": "Rejected phrase", "match_type": "PHRASE"}],
    )

    assert len(result["keyword_errors"]) == 1
    assert result["keyword_errors"][0]["message"] == (
        "Keyword is not permitted | Remove punctuation"
    )
    assert result["keyword_errors"][0]["error_code"] == ("INVALID_KEYWORD_TEXT | INVALID_INPUT")


async def test_add_negative_keywords_fails_closed_for_unaccounted_results() -> None:
    client = _NegativeKeywordClient(
        search_payload={"results": []},
        mutate_payload={"results": []},
    )

    result = await add_negative_keywords(
        client,
        customer_id="333",
        login_customer_id="111",
        shared_set_id="50",
        keywords=[{"text": "Unaccounted", "match_type": "EXACT"}],
    )

    assert result["added"] == []
    assert result["keyword_errors"] == [
        {
            "scope": "keyword",
            "text": "Unaccounted",
            "match_type": "EXACT",
            "message": "Google Ads did not account for this submitted operation",
            "error_code": "UNACCOUNTED_OPERATION",
        }
    ]


async def test_remove_negative_keywords_resolves_precise_and_any_rows() -> None:
    client = _NegativeKeywordClient(
        search_payload={
            "results": [
                {
                    "sharedCriterion": {
                        "criterionId": "1",
                        "keyword": {"text": "Brand Term", "matchType": "EXACT"},
                    }
                },
                {
                    "sharedCriterion": {
                        "criterionId": "2",
                        "keyword": {"text": "Generic Term", "matchType": "PHRASE"},
                    }
                },
                {
                    "sharedCriterion": {
                        "criterionId": "3",
                        "keyword": {"text": "generic term", "matchType": "BROAD"},
                    }
                },
                {
                    "sharedCriterion": {
                        "criterionId": "4",
                        "keyword": {"text": "Keep Me", "matchType": "BROAD"},
                    }
                },
            ]
        },
        mutate_payload={
            "results": [
                {"resourceName": "customers/3333333333/sharedCriteria/50~1"},
                {"resourceName": "customers/3333333333/sharedCriteria/50~2"},
                {"resourceName": "customers/3333333333/sharedCriteria/50~3"},
            ]
        },
    )

    result = await remove_negative_keywords(
        client,
        customer_id="333-333-3333",
        login_customer_id="111",
        shared_set_id="50",
        keywords=[
            {"text": "brand term", "match_type": "EXACT"},
            {"text": "GENERIC TERM", "match_type": "ANY"},
            {"text": "missing", "match_type": "PHRASE"},
        ],
    )

    assert "shared_criterion.criterion_id" in client.calls[0]["json"]["query"]
    assert client.calls[1]["json"] == {
        "operations": [
            {"remove": "customers/3333333333/sharedCriteria/50~1"},
            {"remove": "customers/3333333333/sharedCriteria/50~2"},
            {"remove": "customers/3333333333/sharedCriteria/50~3"},
        ],
        "partialFailure": True,
    }
    assert result["resource_names"] == [
        "customers/3333333333/sharedCriteria/50~1",
        "customers/3333333333/sharedCriteria/50~2",
        "customers/3333333333/sharedCriteria/50~3",
    ]
    assert [(item["text"], item["match_type"]) for item in result["removed"]] == [
        ("Brand Term", "EXACT"),
        ("Generic Term", "PHRASE"),
        ("generic term", "BROAD"),
    ]
    assert result["not_found"] == [{"text": "missing", "match_type": "PHRASE"}]
    assert result["keyword_errors"] == []


async def test_remove_negative_keywords_never_mutates_not_found_rows() -> None:
    client = _NegativeKeywordClient(search_payload={"results": []}, mutate_payload={})

    result = await remove_negative_keywords(
        client,
        customer_id="333",
        login_customer_id="111",
        shared_set_id="50",
        keywords=[{"text": "absent", "match_type": "ANY"}],
    )

    assert len(client.calls) == 1
    assert result == {
        "removed": [],
        "resource_names": [],
        "not_found": [{"text": "absent", "match_type": "ANY"}],
        "keyword_errors": [],
    }


async def test_remove_negative_keywords_rejects_any_expansion_above_audit_limit() -> None:
    search_rows = [
        {
            "sharedCriterion": {
                "criterionId": str(index * 3 + variant),
                "keyword": {"text": f"term {index}", "matchType": match_type},
            }
        }
        for index in range(167)
        for variant, match_type in enumerate(("EXACT", "PHRASE", "BROAD"), start=1)
    ]
    client = _NegativeKeywordClient(
        search_payload={"results": search_rows},
        mutate_payload={"results": []},
    )

    with pytest.raises(IntegrationValidationError, match="more than 500"):
        await remove_negative_keywords(
            client,
            customer_id="333",
            login_customer_id="111",
            shared_set_id="50",
            keywords=[{"text": f"term {index}", "match_type": "ANY"} for index in range(167)],
        )

    assert len(client.calls) == 1


async def test_remove_negative_keywords_maps_partial_failures_to_resolved_rows() -> None:
    client = _NegativeKeywordClient(
        search_payload={
            "results": [
                {
                    "sharedCriterion": {
                        "criterionId": "1",
                        "keyword": {"text": "accepted", "matchType": "EXACT"},
                    }
                },
                {
                    "sharedCriterion": {
                        "criterionId": "2",
                        "keyword": {"text": "rejected", "matchType": "PHRASE"},
                    }
                },
            ]
        },
        mutate_payload={
            "results": [
                {"resourceName": "customers/333/sharedCriteria/50~1"},
                {},
            ],
            "partialFailureError": {
                "details": [
                    {
                        "errors": [
                            {
                                "message": "Criterion cannot be removed",
                                "errorCode": {"criterionError": "CANNOT_REMOVE_CRITERION"},
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

    result = await remove_negative_keywords(
        client,
        customer_id="333",
        login_customer_id="111",
        shared_set_id="50",
        keywords=[
            {"text": "accepted", "match_type": "EXACT"},
            {"text": "rejected", "match_type": "PHRASE"},
        ],
    )

    assert result["resource_names"] == ["customers/333/sharedCriteria/50~1"]
    assert result["keyword_errors"] == [
        {
            "scope": "keyword",
            "text": "rejected",
            "match_type": "PHRASE",
            "message": "Criterion cannot be removed",
            "error_code": "CANNOT_REMOVE_CRITERION",
        }
    ]


def test_remove_negative_keyword_audit_detail_retains_removed_resource_names() -> None:
    reference = GoogleAdsSharedSetReference(
        integration_resource_id=uuid4(),
        external_id="50",
        label="Brand Protection",
    )

    detail = removal_operation_detail(
        reference,
        {
            "removed": [
                {
                    "text": "brand term",
                    "match_type": "EXACT",
                    "resource_name": "customers/333/sharedCriteria/50~1",
                }
            ],
            "not_found": [{"text": "missing", "match_type": "ANY"}],
            "keyword_errors": [],
        },
    )

    assert detail.changes[0].action == "remove"
    assert detail.changes[0].external_ref == "customers/333/sharedCriteria/50~1"
    assert detail.counts.model_dump() == {"applied": 1, "skipped": 1, "failed": 0}


async def test_durable_audit_failure_after_provider_write_is_not_silenced(monkeypatch) -> None:
    pending_event_id = uuid4()
    audit = AsyncMock(side_effect=[pending_event_id, RuntimeError("database unavailable")])
    execute = AsyncMock(return_value={"ok": True})
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        )
    )
    entry = SimpleNamespace()
    detail = _negative_keyword_operation_detail(
        GoogleAdsSharedSetReference(
            integration_resource_id=uuid4(),
            external_id="50",
            label="Brand Protection",
        ),
        {"added": [], "skipped_existing": [], "keyword_errors": []},
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.audit.record_google_ads_operation_audit",
        audit,
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        await run_audited_operation(
            ctx,
            entry,
            tool_name="google_ads_add_negative_keywords",
            operation="add_negative_keywords",
            execute=execute,
            operation_detail_from_result=lambda _result: detail,
            pending_operation_detail=detail,
            require_durable_audit=True,
        )

    execute.assert_awaited_once()
    assert [call.kwargs["status"] for call in audit.await_args_list] == [
        AuditStatus.PENDING,
        AuditStatus.SUCCESS,
    ]
    assert audit.await_args_list[1].kwargs["related_event_id"] == pending_event_id


@pytest.mark.parametrize("outcome", ["added", "skipped_existing", "failed"])
def test_negative_keyword_model_result_is_bounded_with_accurate_counts(outcome: str) -> None:
    keyword = {"text": "x" * 80, "match_type": "PHRASE"}
    provider_result = {
        "added": [],
        "skipped_existing": [],
        "keyword_errors": [],
    }
    if outcome == "added":
        provider_result["added"] = [
            {
                **keyword,
                "resource_name": f"customers/333/sharedCriteria/{'9' * 900}~{index}",
            }
            for index in range(500)
        ]
    elif outcome == "skipped_existing":
        provider_result["skipped_existing"] = [keyword.copy() for _ in range(500)]
    else:
        provider_result["keyword_errors"] = [
            {
                "scope": "keyword",
                **keyword,
                "message": "provider failure " + "y" * 2_000,
                "error_code": "INVALID_KEYWORD_TEXT",
            }
            for _ in range(500)
        ]

    result = bounded_negative_keyword_result(provider_result)
    serialized = json.dumps(
        result,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )

    assert len(serialized) <= MAX_NEGATIVE_KEYWORD_RESULT_CHARS
    assert result["counts"] == {
        "added": 500 if outcome == "added" else 0,
        "skipped_existing": 500 if outcome == "skipped_existing" else 0,
        "failed": 500 if outcome == "failed" else 0,
    }
    assert result["samples_truncated"] is True
    assert 0 < len(result["samples"][outcome]) <= 10
    assert "added_keywords" not in result
    assert "resource_names" not in result
    if outcome == "added":
        assert set(result["samples"]["added"][0]) == {
            "text",
            "match_type",
            "resource_name",
        }


def test_negative_keyword_display_result_retains_every_row() -> None:
    added = [
        {
            "text": f"term {index}",
            "match_type": "EXACT",
            "resource_name": f"customers/333/sharedCriteria/50~{index}",
        }
        for index in range(500)
    ]

    result = complete_negative_keyword_result(
        {"added": added, "skipped_existing": [], "keyword_errors": []}
    )

    assert result["counts"]["added"] == 500
    assert result["samples"]["added"] == added
    assert result["samples_truncated"] is False


def test_negative_keyword_removal_results_bound_model_data_and_keep_safe_display_rows() -> None:
    provider_result = {
        "removed": [
            {
                "text": f"term {index}",
                "match_type": "EXACT",
                "resource_name": f"customers/333/sharedCriteria/50~{index}",
            }
            for index in range(500)
        ],
        "not_found": [{"text": "missing", "match_type": "ANY"}],
        "keyword_errors": [
            {
                "scope": "keyword",
                "text": "failed",
                "match_type": "PHRASE",
                "message": "provider failure " + "y" * 2_000,
                "error_code": "E" * 200,
            }
        ],
    }

    model_result = bounded_negative_keyword_removal_result(provider_result)
    display_result = complete_negative_keyword_removal_result(provider_result)

    assert len(json.dumps(model_result, ensure_ascii=False)) <= MAX_NEGATIVE_KEYWORD_RESULT_CHARS
    assert model_result["counts"] == {"removed": 500, "not_found": 1, "failed": 1}
    assert model_result["samples_truncated"] is True
    assert len(display_result["samples"]["removed"]) == 500
    assert len(display_result["samples"]["failed"][0]["message"]) == 500
    assert len(display_result["samples"]["failed"][0]["error_code"]) == 100
    assert len(json.dumps(display_result, ensure_ascii=False)) < (
        MAX_NEGATIVE_KEYWORD_PUBLIC_RESULT_CHARS
    )


def test_negative_keyword_audit_detail_retains_all_applied_rows() -> None:
    reference = GoogleAdsSharedSetReference(
        integration_resource_id=uuid4(),
        external_id="50",
        label="Brand Protection",
    )
    provider_result = {
        "added": [
            {
                "text": f"keyword {index}",
                "match_type": "EXACT",
                "resource_name": f"customers/333/sharedCriteria/50~{index}",
            }
            for index in range(500)
        ],
        "skipped_existing": [],
        "keyword_errors": [],
    }

    detail = _negative_keyword_operation_detail(reference, provider_result)

    assert detail.counts.applied == 500
    assert len(detail.changes) == 500
    assert detail.changes[0].fields["text"] == "keyword 0"
    assert detail.changes[-1].fields["text"] == "keyword 499"
    assert detail.changes[-1].external_ref == "customers/333/sharedCriteria/50~499"


async def test_list_shared_sets_filters_enabled_negative_keyword_lists_and_escapes_search() -> None:
    client = _OperationClient({"results": [{"sharedSet": {"id": "50"}}]})

    assert await list_shared_sets(
        client,
        customer_id="333-333-3333",
        login_customer_id="111",
        shared_set_type="NEGATIVE_KEYWORDS",
        shared_set_ids=("50",),
        search="Brand's \\ list",
        limit=1,
    )
    assert "shared_set.status = 'ENABLED'" in client.last_json["query"]
    assert "shared_set.type = 'NEGATIVE_KEYWORDS'" in client.last_json["query"]
    assert "shared_set.id IN (50)" in client.last_json["query"]
    assert "LIKE '%Brand\\'s \\\\ list%'" in client.last_json["query"]
    assert "ORDER BY shared_set.name, shared_set.id LIMIT 1" in client.last_json["query"]


async def test_list_campaigns_validates_exact_ids_and_escapes_search() -> None:
    client = _OperationClient(
        {
            "results": [
                {"campaign": {"id": "10", "name": "Brand", "status": "ENABLED"}},
                {"notCampaign": {"id": "20"}},
            ]
        }
    )

    campaigns = await list_campaigns(
        client,
        customer_id="333-333-3333",
        login_customer_id="111",
        campaign_ids=("20", "10", "20"),
        search="Brand's \\ sale%_[]",
        limit=101,
        exclude_removed=True,
    )

    assert campaigns == [{"id": "10", "name": "Brand", "status": "ENABLED"}]
    assert "campaign.status != 'REMOVED'" in client.last_json["query"]
    assert "campaign.id IN (10, 20)" in client.last_json["query"]
    assert "LIKE '%Brand\\'s \\\\ sale[%][_][[][]]%'" in client.last_json["query"]
    assert "ORDER BY campaign.name, campaign.id LIMIT 101" in client.last_json["query"]


async def test_list_ad_groups_validates_exact_ids_and_returns_campaign_rows() -> None:
    row = {
        "adGroup": {"id": "10", "name": "Exact", "status": "ENABLED"},
        "campaign": {"name": "Brand"},
    }
    client = _OperationClient({"results": [row]})

    assert await list_ad_groups(
        client,
        customer_id="333-333-3333",
        login_customer_id="111",
        ad_group_ids=("20", "10", "20"),
        search="Group's \\ sale",
        limit=101,
        exclude_removed=True,
    ) == [row]
    assert "ad_group.status != 'REMOVED'" in client.last_json["query"]
    assert "ad_group.id IN (10, 20)" in client.last_json["query"]
    assert "ad_group.name LIKE '%Group\\'s \\\\ sale%'" in client.last_json["query"]
    assert "ORDER BY ad_group.name, ad_group.id LIMIT 101" in client.last_json["query"]


@pytest.mark.parametrize(
    ("operation", "id_name"),
    [(list_campaigns, "campaign_ids"), (list_ad_groups, "ad_group_ids")],
)
async def test_google_ads_entity_operations_reject_malformed_ids_and_bounds(
    operation,
    id_name: str,
) -> None:
    client = _OperationClient({"results": []})
    common = {
        "customer_id": "333",
        "login_customer_id": "111",
        "limit": 1,
        "exclude_removed": True,
    }

    with pytest.raises(ValueError, match="ids must contain only digits"):
        await operation(client, **common, **{id_name: ("10 OR 1=1",)})
    with pytest.raises(ValueError, match="between 1 and 101"):
        await operation(client, **{**common, "limit": 102})


@pytest.mark.parametrize(
    ("search", "escaped"),
    [
        ("[", "[[]"),
        ("]", "[]]"),
        ("%", "[%]"),
        ("_", "[_]"),
        ("[Brand] 100%_off", "[[]Brand[]] 100[%][_]off"),
    ],
)
async def test_list_shared_sets_treats_gaql_like_metacharacters_literally(
    search: str,
    escaped: str,
) -> None:
    client = _OperationClient({"results": []})

    await list_shared_sets(
        client,
        customer_id="3333333333",
        login_customer_id="111",
        shared_set_type="NEGATIVE_KEYWORDS",
        search=search,
        limit=1,
    )

    expected_query = (
        "SELECT shared_set.id, shared_set.name, shared_set.member_count FROM shared_set "
        "WHERE shared_set.type = 'NEGATIVE_KEYWORDS' AND shared_set.status = 'ENABLED' "
        "AND shared_set.name LIKE '%SEARCH_LITERAL%' "
        "ORDER BY shared_set.name, shared_set.id LIMIT 1"
    ).replace("SEARCH_LITERAL", escaped)
    assert client.last_json["query"] == expected_query


def test_gaql_like_literal_length_bound_never_splits_an_escape_sequence() -> None:
    assert escape_gaql_like_literal("ab%", max_length=5) == "ab[%]"
    assert escape_gaql_like_literal("abc%", max_length=5) == "abc"
    assert escape_gaql_like_literal(f"{'a' * 199}%") == "a" * 199


async def test_list_shared_sets_search_bound_never_splits_an_escape_sequence() -> None:
    client = _OperationClient({"results": []})

    await list_shared_sets(
        client,
        customer_id="3333333333",
        login_customer_id="111",
        shared_set_type="NEGATIVE_KEYWORDS",
        search=f"{'a' * 199}%",
        limit=1,
    )

    expected_query = (
        "SELECT shared_set.id, shared_set.name, shared_set.member_count FROM shared_set "
        "WHERE shared_set.type = 'NEGATIVE_KEYWORDS' AND shared_set.status = 'ENABLED' "
        "AND shared_set.name LIKE '%SEARCH_LITERAL%' "
        "ORDER BY shared_set.name, shared_set.id LIMIT 1"
    ).replace("SEARCH_LITERAL", "a" * 199)
    assert client.last_json["query"] == expected_query


async def test_list_shared_sets_can_return_the_complete_ordered_result() -> None:
    client = _OperationClient({"results": []})

    await list_shared_sets(
        client,
        customer_id="3333333333",
        login_customer_id="111",
        shared_set_type="NEGATIVE_KEYWORDS",
        limit=None,
    )

    assert "ORDER BY shared_set.name, shared_set.id" in client.last_json["query"]
    assert " LIMIT " not in client.last_json["query"]


async def test_list_shared_sets_uses_the_requested_validated_type() -> None:
    client = _OperationClient({"results": []})

    await list_shared_sets(
        client,
        customer_id="3333333333",
        login_customer_id="111",
        shared_set_type="FUTURE_SHARED_SET_TYPE",
        limit=1,
    )

    assert "shared_set.type = 'FUTURE_SHARED_SET_TYPE'" in client.last_json["query"]


@pytest.mark.parametrize("shared_set_type", ["", "negative_keywords", "TYPE' OR 1=1"])
async def test_list_shared_sets_rejects_invalid_type_identifiers(
    shared_set_type: str,
) -> None:
    client = _OperationClient({"results": []})

    with pytest.raises(ValueError, match="uppercase provider enum identifier"):
        await list_shared_sets(
            client,
            customer_id="3333333333",
            login_customer_id="111",
            shared_set_type=shared_set_type,
            limit=1,
        )


def test_negative_keyword_normalization_is_pairwise_and_bounded() -> None:
    normalized = normalize_negative_keywords(
        [
            NegativeKeywordEntry(text="  Brand   Term ", match_type="EXACT"),
            NegativeKeywordEntry(text="brand term", match_type="EXACT"),
            NegativeKeywordEntry(text="brand term", match_type="PHRASE"),
        ]
    )

    assert [item.model_dump() for item in normalized] == [
        {"text": "Brand Term", "match_type": "EXACT"},
        {"text": "brand term", "match_type": "PHRASE"},
    ]


def test_negative_keyword_removal_any_absorbs_same_text_precise_rows() -> None:
    normalized = normalize_negative_keywords(
        [
            NegativeKeywordRemovalEntry(text="Brand Term", match_type="EXACT"),
            NegativeKeywordRemovalEntry(text="brand term", match_type="ANY"),
            NegativeKeywordRemovalEntry(text="BRAND TERM", match_type="PHRASE"),
            NegativeKeywordRemovalEntry(text="other", match_type="BROAD"),
        ]
    )

    assert [item.model_dump() for item in normalized] == [
        {"text": "brand term", "match_type": "ANY"},
        {"text": "other", "match_type": "BROAD"},
    ]


def test_negative_keyword_entry_normalizes_whitespace_before_length_validation() -> None:
    entry = NegativeKeywordEntry(
        text=f"   Brand{' ' * 81}Term   ",
        match_type="EXACT",
    )

    assert entry.text == "Brand Term"


def test_negative_keyword_entry_accepts_exactly_80_normalized_characters() -> None:
    entry = NegativeKeywordEntry(
        text=f"  {'x' * 80}  ",
        match_type="EXACT",
    )

    assert entry.text == "x" * 80


def test_negative_keyword_entry_rejects_81_normalized_characters() -> None:
    with pytest.raises(ValidationError, match="at most 80 characters"):
        NegativeKeywordEntry(text=f"  {'x' * 81}  ", match_type="EXACT")


@pytest.mark.parametrize("text", ["one two three four five six seven eight nine ten eleven"])
def test_negative_keyword_normalization_retries_invalid_text(text: str) -> None:
    with pytest.raises(ModelRetry):
        normalize_negative_keywords([NegativeKeywordEntry(text=text, match_type="EXACT")])


def test_negative_keyword_entry_rejects_empty_normalized_text() -> None:
    with pytest.raises(ValidationError, match="at least 1 character"):
        NegativeKeywordEntry(text="   ", match_type="EXACT")


async def test_negative_keyword_approval_resume_validates_canonical_override_text() -> None:
    executed: list[NegativeKeywordEntry] = []

    def model(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        if not any(message.kind == "request" for message in messages[1:]):
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="add_keywords",
                        args={"keywords": [{"text": "original", "match_type": "EXACT"}]},
                        tool_call_id="approval-call",
                    )
                ]
            )
        return ModelResponse(parts=[TextPart(content="done")])

    agent = Agent(
        FunctionModel(model),
        output_type=[str, DeferredToolRequests],
    )

    @agent.tool_plain(requires_approval=True)
    def add_keywords(keywords: list[NegativeKeywordEntry]) -> str:
        executed.extend(keywords)
        return "added"

    suspended = await agent.run("Add a keyword")
    assert isinstance(suspended.output, DeferredToolRequests)

    resumed = await agent.run(
        message_history=suspended.all_messages(),
        deferred_tool_results=DeferredToolResults(
            approvals={
                "approval-call": ToolApproved(
                    override_args={
                        "keywords": [
                            {
                                "text": f"   Edited{' ' * 81}Brand   ",
                                "match_type": "PHRASE",
                            }
                        ]
                    }
                )
            }
        ),
    )

    assert resumed.output == "done"
    assert [entry.model_dump() for entry in executed] == [
        {"text": "Edited Brand", "match_type": "PHRASE"}
    ]


def test_negative_keyword_entry_forbids_extra_keys() -> None:
    with pytest.raises(ValidationError):
        NegativeKeywordEntry.model_validate(
            {"text": "term", "match_type": "EXACT", "provider_id": "unsafe"}
        )


async def test_add_negative_keywords_retries_above_bulk_bound() -> None:
    with pytest.raises(ModelRetry, match="at most 500"):
        await google_ads_add_negative_keywords(
            None,  # type: ignore[arg-type]
            GoogleAdsSharedSetReference(
                integration_resource_id=uuid4(),
                external_id="50",
                label="Brand Protection",
            ),
            [
                NegativeKeywordEntry(text=f"term {index}", match_type="EXACT")
                for index in range(501)
            ],
        )


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


def test_campaign_reference_rejects_removed_campaign() -> None:
    choice = campaign_choice(
        SimpleNamespace(integration_resource_id=uuid4(), display_name="Ads account"),
        {"id": "10", "name": "Removed campaign", "status": "REMOVED"},
    )

    assert choice is None


def test_scoped_reference_grouping_is_context_ordered_deduplicated_and_bounded() -> None:
    first = _writable_google_ads_entry()
    second = _writable_google_ads_entry()
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
        active_context=ResolvedActiveContext(entries=(first, incompatible, second))
    )
    values = [
        _campaign_reference(second, "900"),
        *(_campaign_reference(first, str(index)) for index in range(60, 0, -1)),
        _campaign_reference(first, "10"),
        _campaign_reference(incompatible, "800"),
        {"not": "a reference"},
    ]

    grouped = group_scoped_references(
        ctx,
        GOOGLE_ADS_BINDING,
        values,
        GoogleAdsCampaignReference,
    )

    assert [entry for entry, _references in grouped] == [first, second]
    assert [reference.external_id for reference in grouped[0][1]] == sorted(
        {str(index) for index in range(1, 61)}
    )[:50]
    assert [reference.external_id for reference in grouped[1][1]] == ["900"]


def test_shared_set_choice_carries_member_count() -> None:
    choice = shared_set_choice(
        SimpleNamespace(integration_resource_id=uuid4(), display_name="Ads account"),
        {"id": "50", "name": "Brand Protection", "memberCount": "312"},
    )

    assert choice is not None
    assert choice.value["entity_kind"] == "google_ads_shared_set"
    assert choice.value["member_count"] == 312
    assert choice.description == "312 negative keywords"


def test_shared_set_reference_canonicalizes_google_resource_name() -> None:
    resource_id = uuid4()

    reference = GoogleAdsSharedSetReference.model_validate(
        {
            "entity_kind": "google_ads_shared_set",
            "integration_resource_id": resource_id,
            "external_id": "customers/9308708411/sharedSets/12186751748",
            "entity_id": "12186751748",
            "label": "Testing 2",
        }
    )

    assert reference.external_id == "12186751748"
    assert "entity_id" not in reference.model_dump()


def test_shared_set_reference_rejects_conflicting_redundant_id() -> None:
    with pytest.raises(ValidationError, match="entity_id"):
        GoogleAdsSharedSetReference.model_validate(
            {
                "integration_resource_id": uuid4(),
                "external_id": "customers/9308708411/sharedSets/12186751748",
                "entity_id": "999",
                "label": "Testing 2",
            }
        )


async def test_shared_set_search_pages_every_account_without_truncation(monkeypatch) -> None:
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
        db=object(),
        actor=object(),
        workspace=object(),
        active_context=ResolvedActiveContext(entries=entries),
    )
    query_calls = []

    async def query(_ctx, entry, **kwargs):
        query_calls.append((entry, kwargs))
        if entry == entries[1]:
            return [{"id": "900", "name": "Only in second", "memberCount": 1}]
        return [
            {
                "id": str(index),
                "name": f"List {index:03d}",
                "memberCount": index,
            }
            for index in range(150)
        ]

    monkeypatch.setattr("integrations.google_ads.entity_resolvers.shared_set._query", query)

    pages = []
    cursors = []
    cursor = None
    while True:
        page = await search_google_ads_shared_sets(ctx, "Brand's \\ list", {}, 25, cursor)
        pages.append(page)
        if page.next_cursor is None:
            break
        assert page.next_cursor not in cursors
        cursors.append(page.next_cursor)
        cursor = page.next_cursor

    choices = [choice for page in pages for choice in page.choices]
    identities = [
        (choice.value["integration_resource_id"], choice.value["external_id"]) for choice in choices
    ]
    assert len(choices) == 151
    assert len(identities) == len(set(identities))
    assert identities[1] == (str(entries[1].integration_resource_id), "900")
    assert all(len(page.choices) <= 25 for page in pages)
    assert pages[-1].next_cursor is None
    assert cursors == ["25", "50", "75", "100", "125", "150"]
    assert all(kwargs["search"] == "Brand's \\ list" for _, kwargs in query_calls)
    assert all(kwargs["limit"] is None for _, kwargs in query_calls)

    invalid_cursor_page = await search_google_ads_shared_sets(
        ctx, "Brand's \\ list", {}, 25, "invalid"
    )
    assert invalid_cursor_page.choices == pages[0].choices


async def test_shared_set_hydration_drops_invalid_and_inactive_ids(monkeypatch) -> None:
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
    query = AsyncMock(return_value=[{"id": "50", "name": "Current list", "memberCount": 4}])
    monkeypatch.setattr("integrations.google_ads.entity_resolvers.shared_set._query", query)

    choices = await resolve_google_ads_shared_sets(
        ctx,
        [
            {
                "entity_kind": "google_ads_shared_set",
                "integration_resource_id": str(active.integration_resource_id),
                "external_id": "customers/111/sharedSets/50",
                "entity_id": "50",
                "label": "Current list",
            },
            GoogleAdsSharedSetReference(
                integration_resource_id=active.integration_resource_id,
                external_id="not-digits",
                label="Invalid list",
            ),
            GoogleAdsSharedSetReference(
                integration_resource_id=uuid4(),
                external_id="60",
                label="Inactive list",
            ),
        ],
        {},
    )

    assert [choice.value["external_id"] for choice in choices] == ["50"]
    assert query.await_args.kwargs["shared_set_ids"] == ["50"]
    assert query.await_args.kwargs["limit"] == 1


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

    page = await search_google_ads_campaigns(ctx, "Campaign's \\ list", {}, 25, "100")

    assert [choice.value["external_id"] for choice in page.choices] == ["100"]
    assert page.next_cursor is None
    assert [call.args[1] for call in query.await_args_list] == [active, second_active]
    assert all(
        call.kwargs
        == {
            "search": "Campaign's \\ list",
            "limit": 101,
            "exclude_removed": True,
        }
        for call in query.await_args_list
    )


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
    assert query.await_args.kwargs == {
        "campaign_ids": ["10", "20"],
        "limit": 2,
        "exclude_removed": True,
    }


async def test_ad_group_search_fans_out_and_labels_campaign_scope(monkeypatch) -> None:
    active = _writable_google_ads_entry()
    second_active = _writable_google_ads_entry()
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
            {
                "adGroup": {"id": "10", "name": "Exact", "status": "ENABLED"},
                "campaign": {"name": "Brand"},
            }
        ]
    )
    monkeypatch.setattr("integrations.google_ads.entity_resolvers.ad_group._query", query)

    page = await search_google_ads_ad_groups(ctx, "Group's \\ name", {}, 25, None)

    assert len(page.choices) == 2
    assert [choice.value["scope_label"] for choice in page.choices] == ["Brand", "Brand"]
    assert [call.args[1] for call in query.await_args_list] == [active, second_active]
    assert all(
        call.kwargs
        == {
            "search": "Group's \\ name",
            "limit": 26,
            "exclude_removed": True,
        }
        for call in query.await_args_list
    )


async def test_ad_group_hydration_drops_stale_and_out_of_context_values(monkeypatch) -> None:
    active = _writable_google_ads_entry()
    ctx = SimpleNamespace(
        db=object(),
        actor=object(),
        workspace=object(),
        active_context=ResolvedActiveContext(entries=(active,)),
    )
    query = AsyncMock(
        return_value=[
            {
                "adGroup": {"id": "10", "name": "Exact", "status": "ENABLED"},
                "campaign": {"name": "Brand"},
            }
        ]
    )
    monkeypatch.setattr("integrations.google_ads.entity_resolvers.ad_group._query", query)

    choices = await resolve_google_ads_ad_groups(
        ctx,
        [
            _ad_group_reference(active, "10"),
            _ad_group_reference(active, "20"),
            GoogleAdsAdGroupReference(
                integration_resource_id=uuid4(),
                external_id="30",
                label="Inactive ad group",
            ),
        ],
        {},
    )

    assert [choice.value["external_id"] for choice in choices] == ["10"]
    assert choices[0].value["scope_label"] == "Brand"
    assert query.await_args.kwargs == {
        "ad_group_ids": ["10", "20"],
        "limit": 2,
        "exclude_removed": True,
    }


async def test_campaign_and_ad_group_resolvers_call_canonical_operations(monkeypatch) -> None:
    entry = _writable_google_ads_entry()
    ctx = SimpleNamespace(
        db=object(),
        actor=object(),
        workspace=object(),
        active_context=ResolvedActiveContext(entries=(entry,)),
    )
    client = object()
    campaign_operation = AsyncMock(
        return_value=[{"id": "10", "name": "Search", "status": "ENABLED"}]
    )
    ad_group_operation = AsyncMock(
        return_value=[
            {
                "adGroup": {"id": "20", "name": "Exact", "status": "ENABLED"},
                "campaign": {"name": "Brand"},
            }
        ]
    )
    monkeypatch.setattr(
        "integrations.google_ads.entity_resolvers.campaign.google_ads_client_for_principal",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.entity_resolvers.campaign.list_campaigns",
        campaign_operation,
    )
    monkeypatch.setattr(
        "integrations.google_ads.entity_resolvers.ad_group.google_ads_client_for_principal",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.entity_resolvers.ad_group.list_ad_groups",
        ad_group_operation,
    )

    await resolve_google_ads_campaigns(ctx, [_campaign_reference(entry, "10")], {})
    await resolve_google_ads_ad_groups(ctx, [_ad_group_reference(entry, "20")], {})

    campaign_operation.assert_awaited_once_with(
        client,
        customer_id="111",
        login_customer_id="999",
        campaign_ids=["10"],
        search=None,
        limit=1,
        exclude_removed=True,
    )
    ad_group_operation.assert_awaited_once_with(
        client,
        customer_id="111",
        login_customer_id="999",
        ad_group_ids=["20"],
        search=None,
        limit=1,
        exclude_removed=True,
    )


async def test_google_ads_approval_canonicalization_rejects_stale_target(monkeypatch) -> None:
    entry = _writable_google_ads_entry()
    resolver_context = SimpleNamespace(
        db=object(),
        actor=object(),
        workspace=object(),
        active_context=ResolvedActiveContext(entries=(entry,)),
    )
    reference = _campaign_reference(entry, "10").model_dump(mode="json")
    authorized = SimpleNamespace(
        context=resolver_context,
        resolver=GOOGLE_ADS_CAMPAIGN_RESOLVER,
        field_key="campaign_ids",
        entity_kind="google_ads_campaign",
        depends_on=(),
    )
    monkeypatch.setattr(
        "services.agents.runtime.tools.registry.get_runtime_tool_definition",
        lambda _tool_name: GOOGLE_ADS_UPDATE_CAMPAIGN_STATUS_DEFINITION,
    )
    monkeypatch.setattr(
        "services.agents.runtime.entity_references.service.authorize_entity_field",
        AsyncMock(return_value=authorized),
    )
    monkeypatch.setattr(
        "integrations.google_ads.entity_resolvers.campaign._query",
        AsyncMock(return_value=[]),
    )

    with pytest.raises(AppValidationError, match="unavailable or no longer accessible"):
        await validate_and_canonicalize_override_args(
            AsyncMock(),
            actor=SimpleNamespace(),
            workspace=SimpleNamespace(),
            membership=SimpleNamespace(),
            run=SimpleNamespace(conversation_id=uuid4()),
            tool_call=SimpleNamespace(
                tool_name="google_ads_update_campaign_status",
                args={"campaign_ids": [reference], "status": "PAUSED"},
            ),
            override_args=None,
        )


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


async def test_campaign_verification_can_ignore_removed_campaigns() -> None:
    entry = _writable_google_ads_entry()
    client = AsyncMock()
    client.post.return_value = {"results": [{"campaign": {"id": "10", "status": "REMOVED"}}]}

    with pytest.raises(ModelRetry, match="campaign is unavailable"):
        await verify_campaigns(
            client,
            entry=entry,
            campaign_ids=["10"],
            ignore_removed=True,
        )

    assert "campaign.status != 'REMOVED'" in client.post.await_args.kwargs["json"]["query"]

    await verify_campaigns(
        client,
        entry=entry,
        campaign_ids=["10"],
        ignore_removed=False,
    )

    assert "campaign.status != 'REMOVED'" not in client.post.await_args.kwargs["json"]["query"]


async def test_execution_verifiers_share_canonical_operation_layer(monkeypatch) -> None:
    entry = _writable_google_ads_entry()
    client = AsyncMock()
    campaign_operation = AsyncMock(
        return_value=[
            {"id": "10", "status": "ENABLED"},
            {"id": "20", "status": "ENABLED"},
        ]
    )
    ad_group_operation = AsyncMock(
        return_value=[
            {"adGroup": {"id": "30"}, "campaign": {"name": "Brand"}},
        ]
    )
    shared_set_operation = AsyncMock(return_value=[{"id": "50"}])
    monkeypatch.setattr(
        "integrations.google_ads.tools.verifiers.campaign.list_campaigns",
        campaign_operation,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.verifiers.ad_group.list_ad_groups",
        ad_group_operation,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.verifiers.shared_set.list_shared_sets",
        shared_set_operation,
    )

    await verify_campaigns(
        client,
        entry=entry,
        campaign_ids=["20", "10", "20"],
        ignore_removed=True,
    )
    await verify_ad_groups(client, entry=entry, ad_group_ids=["30"])
    await verify_shared_sets(client, entry=entry, shared_set_ids=["50"])

    assert campaign_operation.await_args.kwargs["campaign_ids"] == ("10", "20")
    assert campaign_operation.await_args.kwargs["exclude_removed"] is True
    assert ad_group_operation.await_args.kwargs["ad_group_ids"] == ("30",)
    assert shared_set_operation.await_args.kwargs == {
        "customer_id": "111",
        "login_customer_id": "999",
        "shared_set_type": "NEGATIVE_KEYWORDS",
        "shared_set_ids": ("50",),
        "limit": 1,
    }

    campaign_operation.return_value = [{"id": "10", "status": "ENABLED"}]
    with pytest.raises(ModelRetry, match="campaign is unavailable"):
        await verify_campaigns(
            client,
            entry=entry,
            campaign_ids=["10", "20"],
            ignore_removed=True,
        )

    calls_before_invalid = shared_set_operation.await_count
    with pytest.raises(ModelRetry, match="list is unavailable"):
        await verify_shared_sets(client, entry=entry, shared_set_ids=["not-digits"])
    assert shared_set_operation.await_count == calls_before_invalid


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


async def test_negative_list_campaign_links_reject_cross_account_references(
    monkeypatch,
) -> None:
    list_resource_id = uuid4()
    campaign_resource_id = uuid4()
    ctx = SimpleNamespace(deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=())))
    provider_client = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.link_negative_keyword_list.google_ads_client",
        provider_client,
    )

    with pytest.raises(ModelRetry, match="must belong to the same Google Ads account"):
        await google_ads_link_negative_keyword_list(
            ctx,
            GoogleAdsSharedSetReference(
                integration_resource_id=list_resource_id,
                external_id="50",
                label="Brand Protection",
            ),
            [
                GoogleAdsCampaignReference(
                    integration_resource_id=campaign_resource_id,
                    external_id="10",
                    label="Search",
                )
            ],
            "LINK",
        )

    provider_client.assert_not_awaited()


@pytest.mark.parametrize(
    ("shared_sets", "campaign_payload", "message"),
    [
        ([], None, "list is unavailable"),
        ([{"id": "50"}], {"results": []}, "campaign is unavailable"),
        (
            [{"id": "50"}],
            {"results": [{"campaign": {"id": "10", "status": "REMOVED"}}]},
            "campaign is unavailable",
        ),
    ],
)
async def test_negative_list_campaign_links_fail_closed_for_stale_references(
    monkeypatch,
    shared_sets,
    campaign_payload,
    message,
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
    if campaign_payload is not None:
        client.post.return_value = campaign_payload
    provider_link = AsyncMock()

    async def passthrough_audit(_ctx, _entry, **kwargs):
        return await kwargs["execute"]()

    monkeypatch.setattr(
        "integrations.google_ads.tools.link_negative_keyword_list.google_ads_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.verifiers.shared_set.list_shared_sets",
        AsyncMock(return_value=shared_sets),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.link_negative_keyword_list.link_negative_keyword_list",
        provider_link,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.link_negative_keyword_list.run_audited_operation",
        passthrough_audit,
    )

    result = await google_ads_link_negative_keyword_list(
        ctx,
        GoogleAdsSharedSetReference(
            integration_resource_id=entry.integration_resource_id,
            external_id="50",
            label="Brand Protection",
        ),
        [
            GoogleAdsCampaignReference(
                integration_resource_id=entry.integration_resource_id,
                external_id="10",
                label="Search",
            )
        ],
        "LINK",
    )

    assert result["results"][0]["error_code"] == "ModelRetry"
    assert message in result["results"][0]["error_message"]
    provider_link.assert_not_awaited()


async def test_negative_list_campaign_links_reverify_and_mutate_one_account(
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
    client.post.return_value = {"results": [{"campaign": {"id": "10"}}, {"campaign": {"id": "20"}}]}
    provider_link = AsyncMock(
        return_value={
            "resource_names": ["customers/111/campaignSharedSets/10~50"],
            "skipped_existing": ["20"],
            "campaign_errors": [],
        }
    )
    audited_kwargs: dict[str, Any] = {}

    async def passthrough_audit(_ctx, _entry, **kwargs):
        audited_kwargs.update(kwargs)
        return await kwargs["execute"]()

    monkeypatch.setattr(
        "integrations.google_ads.tools.link_negative_keyword_list.google_ads_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.verifiers.shared_set.list_shared_sets",
        AsyncMock(return_value=[{"id": "50"}]),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.link_negative_keyword_list.link_negative_keyword_list",
        provider_link,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.link_negative_keyword_list.run_audited_operation",
        passthrough_audit,
    )

    result = await google_ads_link_negative_keyword_list(
        ctx,
        GoogleAdsSharedSetReference(
            integration_resource_id=entry.integration_resource_id,
            external_id="50",
            label="Brand Protection",
        ),
        [
            GoogleAdsCampaignReference(
                integration_resource_id=entry.integration_resource_id,
                external_id="20",
                label="Shopping",
            ),
            GoogleAdsCampaignReference(
                integration_resource_id=entry.integration_resource_id,
                external_id="10",
                label="Search",
            ),
        ],
        "LINK",
    )

    assert result["results"][0]["status"] == "success"
    assert provider_link.await_args.kwargs == {
        "customer_id": "111",
        "login_customer_id": "999",
        "shared_set_id": "50",
        "campaign_ids": ["10", "20"],
        "action": "LINK",
    }
    provider_result = provider_link.return_value
    assert audited_kwargs["external_ref_from_result"](provider_result) == (
        "customers/111/campaignSharedSets/10~50"
    )
    detail = audited_kwargs["operation_detail_from_result"](provider_result)
    assert detail.changes[0].external_ref == "customers/111/campaignSharedSets/10~50"
    assert audited_kwargs["require_durable_audit"] is True


async def test_negative_list_campaign_links_audit_write_denial_before_provider(
    monkeypatch,
) -> None:
    entry = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="google_ads",
        resource_type="google_ads_account",
        external_id="111",
        display_name="Read-only account",
        connection_id=uuid4(),
        connection_label="Agency",
        connection_status="active",
        write_allowed=False,
        permissions_metadata={"login_customer_id": "999"},
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(entry,)))
    )
    provider_client = AsyncMock()
    audit = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.link_negative_keyword_list.google_ads_client",
        provider_client,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.link_negative_keyword_list.record_google_ads_operation_audit",
        audit,
    )

    result = await google_ads_link_negative_keyword_list(
        ctx,
        GoogleAdsSharedSetReference(
            integration_resource_id=entry.integration_resource_id,
            external_id="50",
            label="Brand Protection",
        ),
        [
            GoogleAdsCampaignReference(
                integration_resource_id=entry.integration_resource_id,
                external_id="10",
                label="Search",
            )
        ],
        "UNLINK",
    )

    assert result["results"][0]["error_code"] == "write_not_permitted"
    provider_client.assert_not_awaited()
    assert audit.await_args.kwargs["status"] == AuditStatus.FAILURE
    assert audit.await_args.kwargs["error_code"] == "write_not_permitted"


async def test_add_negative_keywords_targets_one_account_and_uses_normalized_rows(
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
    client.post.return_value = {"results": [{"sharedSet": {"id": "50"}}]}
    provider_add = AsyncMock(
        return_value={
            "added": [
                {
                    "text": "Brand Term",
                    "match_type": "EXACT",
                    "resource_name": "criteria/1",
                }
            ],
            "skipped_existing": [],
            "keyword_errors": [],
        }
    )

    async def passthrough_audit(_ctx, _entry, **kwargs):
        return await kwargs["execute"]()

    monkeypatch.setattr(
        "integrations.google_ads.tools.add_negative_keywords.google_ads_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.add_negative_keywords.add_negative_keywords",
        provider_add,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.add_negative_keywords.run_audited_operation",
        passthrough_audit,
    )

    result = await google_ads_add_negative_keywords(
        ctx,
        GoogleAdsSharedSetReference(
            integration_resource_id=entry.integration_resource_id,
            external_id="50",
            label="Brand Protection",
        ),
        [
            NegativeKeywordEntry(text="  Brand   Term ", match_type="EXACT"),
            NegativeKeywordEntry(text="brand term", match_type="EXACT"),
            NegativeKeywordEntry(text="brand term", match_type="PHRASE"),
        ],
    )

    assert result.return_value["results"][0]["status"] == "success"
    assert result.metadata["public_result"]["results"][0]["data"]["samples"] == {
        "added": [
            {
                "text": "Brand Term",
                "match_type": "EXACT",
                "resource_name": "criteria/1",
            }
        ],
        "skipped_existing": [],
        "failed": [],
    }
    assert provider_add.await_args.kwargs["shared_set_id"] == "50"
    assert provider_add.await_args.kwargs["keywords"] == [
        {"text": "Brand Term", "match_type": "EXACT"},
        {"text": "brand term", "match_type": "PHRASE"},
    ]


async def test_add_negative_keywords_audits_only_exact_applied_outcome(monkeypatch) -> None:
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
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(entry,)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        )
    )
    client = AsyncMock()
    client.post.return_value = {"results": [{"sharedSet": {"id": "50"}}]}
    provider_add = AsyncMock(
        return_value={
            "added": [
                {
                    "text": "Edited Brand",
                    "match_type": "PHRASE",
                    "resource_name": "customers/111/sharedCriteria/50~1",
                }
            ],
            "skipped_existing": [{"text": "existing", "match_type": "EXACT"}],
            "keyword_errors": [
                {
                    "scope": "keyword",
                    "text": "rejected",
                    "match_type": "BROAD",
                    "message": "provider detail must not be retained",
                    "error_code": "INVALID_KEYWORD_TEXT",
                }
            ],
        }
    )
    audit = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.add_negative_keywords.google_ads_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.add_negative_keywords.add_negative_keywords",
        provider_add,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.audit.record_integration_operation_audit_event",
        audit,
    )

    await google_ads_add_negative_keywords(
        ctx,
        GoogleAdsSharedSetReference(
            integration_resource_id=entry.integration_resource_id,
            external_id="50",
            label="Brand Protection",
            member_count=7,
        ),
        [
            NegativeKeywordEntry(text="  Edited   Brand ", match_type="PHRASE"),
            NegativeKeywordEntry(text="existing", match_type="EXACT"),
            NegativeKeywordEntry(text="rejected", match_type="BROAD"),
        ],
    )

    detail = audit.await_args.kwargs["operation_detail"].model_dump(mode="json")
    assert audit.await_args.kwargs["status"] == AuditStatus.SUCCESS
    assert detail == {
        "schema_version": 1,
        "target": {
            "entity_type": "google_ads_shared_set",
            "external_id": "50",
            "display_name": "Brand Protection",
            "integration_resource_id": str(entry.integration_resource_id),
            "attributes": {"member_count": 7},
        },
        "changes": [
            {
                "action": "add",
                "entity_type": "negative_keyword",
                "external_ref": "customers/111/sharedCriteria/50~1",
                "fields": {"text": "Edited Brand", "match_type": "PHRASE"},
            }
        ],
        "counts": {"applied": 1, "skipped": 1, "failed": 1},
    }
    serialized = json.dumps(detail)
    assert "existing" not in serialized
    assert "rejected" not in serialized
    assert "provider detail" not in serialized


@pytest.mark.parametrize(
    ("provider_result", "expected_status", "expected_counts", "expected_changes"),
    [
        pytest.param(
            {
                "added": [
                    {
                        "text": "accepted",
                        "match_type": "EXACT",
                        "resource_name": "customers/111/sharedCriteria/50~1",
                    }
                ],
                "skipped_existing": [],
                "keyword_errors": [],
            },
            AuditStatus.SUCCESS,
            {"applied": 1, "skipped": 0, "failed": 0},
            1,
            id="all-success",
        ),
        pytest.param(
            {
                "added": [],
                "skipped_existing": [{"text": "existing", "match_type": "EXACT"}],
                "keyword_errors": [],
            },
            AuditStatus.SUCCESS,
            {"applied": 0, "skipped": 1, "failed": 0},
            0,
            id="all-skipped-no-op",
        ),
        pytest.param(
            {
                "added": [
                    {
                        "text": "accepted",
                        "match_type": "EXACT",
                        "resource_name": "customers/111/sharedCriteria/50~1",
                    }
                ],
                "skipped_existing": [],
                "keyword_errors": [
                    {
                        "scope": "keyword",
                        "text": "rejected",
                        "match_type": "PHRASE",
                        "message": "invalid",
                        "error_code": "INVALID_KEYWORD_TEXT",
                    }
                ],
            },
            AuditStatus.SUCCESS,
            {"applied": 1, "skipped": 0, "failed": 1},
            1,
            id="mixed-partial-success",
        ),
        pytest.param(
            {
                "added": [],
                "skipped_existing": [],
                "keyword_errors": [
                    {
                        "scope": "account",
                        "message": "request rejected",
                        "error_code": "AUTHORIZATION_ERROR",
                    }
                ],
            },
            AuditStatus.FAILURE,
            {"applied": 0, "skipped": 0, "failed": 1},
            0,
            id="all-failed",
        ),
    ],
)
async def test_add_negative_keywords_classifies_audit_outcome(
    monkeypatch,
    provider_result,
    expected_status: AuditStatus,
    expected_counts: dict[str, int],
    expected_changes: int,
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
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(entry,)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        )
    )
    client = AsyncMock()
    client.post.return_value = {"results": [{"sharedSet": {"id": "50"}}]}
    audit = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.add_negative_keywords.google_ads_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.add_negative_keywords.add_negative_keywords",
        AsyncMock(return_value=provider_result),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.audit.record_integration_operation_audit_event",
        audit,
    )

    await google_ads_add_negative_keywords(
        ctx,
        GoogleAdsSharedSetReference(
            integration_resource_id=entry.integration_resource_id,
            external_id="50",
            label="Brand Protection",
        ),
        [
            NegativeKeywordEntry(text="accepted", match_type="EXACT"),
            NegativeKeywordEntry(text="rejected", match_type="PHRASE"),
        ],
    )

    assert audit.await_count == 2
    pending_kwargs, audit_kwargs = [call.kwargs for call in audit.await_args_list]
    assert pending_kwargs["status"] == AuditStatus.PENDING
    assert pending_kwargs["raise_on_error"] is True
    assert audit_kwargs["status"] == expected_status
    assert audit_kwargs["raise_on_error"] is True
    detail = audit_kwargs["operation_detail"].model_dump(mode="json")
    assert detail["counts"] == expected_counts
    assert len(detail["changes"]) == expected_changes


async def test_add_negative_keywords_fails_closed_when_list_is_missing(monkeypatch) -> None:
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
    client.post.return_value = {"results": []}
    provider_add = AsyncMock()

    async def passthrough_audit(_ctx, _entry, **kwargs):
        return await kwargs["execute"]()

    monkeypatch.setattr(
        "integrations.google_ads.tools.add_negative_keywords.google_ads_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.add_negative_keywords.add_negative_keywords",
        provider_add,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.add_negative_keywords.run_audited_operation",
        passthrough_audit,
    )

    result = await google_ads_add_negative_keywords(
        ctx,
        GoogleAdsSharedSetReference(
            integration_resource_id=entry.integration_resource_id,
            external_id="50",
            label="Removed list",
        ),
        [NegativeKeywordEntry(text="term", match_type="EXACT")],
    )

    assert result.return_value["results"][0]["error_code"] == "ModelRetry"
    assert "list is unavailable" in result.return_value["results"][0]["error_message"]
    provider_add.assert_not_awaited()


async def test_add_negative_keywords_rejects_target_outside_active_context() -> None:
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
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(active,)))
    )

    with pytest.raises(ModelRetry, match="no longer in the active integration context"):
        await google_ads_add_negative_keywords(
            ctx,
            GoogleAdsSharedSetReference(
                integration_resource_id=uuid4(),
                external_id="50",
                label="Other account list",
            ),
            [NegativeKeywordEntry(text="term", match_type="EXACT")],
        )


async def test_add_negative_keywords_write_denial_is_audited_before_provider_call(
    monkeypatch,
) -> None:
    entry = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="google_ads",
        resource_type="google_ads_account",
        external_id="111",
        display_name="Read-only account",
        connection_id=uuid4(),
        connection_label="Agency",
        connection_status="active",
        write_allowed=False,
        permissions_metadata={"login_customer_id": "999"},
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(entry,)))
    )
    provider_client = AsyncMock()
    audit = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.add_negative_keywords.google_ads_client",
        provider_client,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.add_negative_keywords.record_google_ads_operation_audit",
        audit,
    )

    result = await google_ads_add_negative_keywords(
        ctx,
        GoogleAdsSharedSetReference(
            integration_resource_id=entry.integration_resource_id,
            external_id="50",
            label="Brand Protection",
        ),
        [NegativeKeywordEntry(text="term", match_type="EXACT")],
    )

    assert result.return_value["results"][0]["error_code"] == "write_not_permitted"
    provider_client.assert_not_awaited()
    assert audit.await_args.kwargs["status"] == AuditStatus.FAILURE
    assert audit.await_args.kwargs["error_code"] == "write_not_permitted"


async def test_remove_negative_keywords_normalizes_any_and_targets_one_account(
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
    client.post.return_value = {"results": [{"sharedSet": {"id": "50"}}]}
    provider_remove = AsyncMock(
        return_value={
            "removed": [],
            "resource_names": [],
            "not_found": [{"text": "Brand Term", "match_type": "ANY"}],
            "keyword_errors": [],
        }
    )

    async def passthrough_audit(_ctx, _entry, **kwargs):
        return await kwargs["execute"]()

    monkeypatch.setattr(
        "integrations.google_ads.tools.remove_negative_keywords.google_ads_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.remove_negative_keywords.remove_negative_keywords",
        provider_remove,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.remove_negative_keywords.run_audited_operation",
        passthrough_audit,
    )

    await google_ads_remove_negative_keywords(
        ctx,
        GoogleAdsSharedSetReference(
            integration_resource_id=entry.integration_resource_id,
            external_id="50",
            label="Brand Protection",
        ),
        [
            NegativeKeywordRemovalEntry(text="Brand Term", match_type="EXACT"),
            NegativeKeywordRemovalEntry(text=" brand   term ", match_type="ANY"),
            NegativeKeywordRemovalEntry(text="brand term", match_type="PHRASE"),
        ],
    )

    assert provider_remove.await_args.kwargs["keywords"] == [
        {"text": "brand term", "match_type": "ANY"}
    ]


async def test_remove_negative_keywords_fails_closed_when_list_is_missing(
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
    client.post.return_value = {"results": []}
    provider_remove = AsyncMock()

    async def passthrough_audit(_ctx, _entry, **kwargs):
        return await kwargs["execute"]()

    monkeypatch.setattr(
        "integrations.google_ads.tools.remove_negative_keywords.google_ads_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.remove_negative_keywords.remove_negative_keywords",
        provider_remove,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.remove_negative_keywords.run_audited_operation",
        passthrough_audit,
    )

    result = await google_ads_remove_negative_keywords(
        ctx,
        GoogleAdsSharedSetReference(
            integration_resource_id=entry.integration_resource_id,
            external_id="50",
            label="Removed list",
        ),
        [NegativeKeywordRemovalEntry(text="term", match_type="ANY")],
    )

    assert result.return_value["results"][0]["error_code"] == "ModelRetry"
    assert "list is unavailable" in result.return_value["results"][0]["error_message"]
    provider_remove.assert_not_awaited()


async def test_remove_negative_keywords_write_denial_is_audited_before_provider_call(
    monkeypatch,
) -> None:
    entry = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="google_ads",
        resource_type="google_ads_account",
        external_id="111",
        display_name="Read-only account",
        connection_id=uuid4(),
        connection_label="Agency",
        connection_status="active",
        write_allowed=False,
        permissions_metadata={"login_customer_id": "999"},
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(entry,)))
    )
    provider_client = AsyncMock()
    audit = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.remove_negative_keywords.google_ads_client",
        provider_client,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.remove_negative_keywords.record_google_ads_operation_audit",
        audit,
    )

    result = await google_ads_remove_negative_keywords(
        ctx,
        GoogleAdsSharedSetReference(
            integration_resource_id=entry.integration_resource_id,
            external_id="50",
            label="Brand Protection",
        ),
        [NegativeKeywordRemovalEntry(text="term", match_type="EXACT")],
    )

    assert result.return_value["results"][0]["error_code"] == "write_not_permitted"
    provider_client.assert_not_awaited()
    assert audit.await_args.kwargs["status"] == AuditStatus.FAILURE
    assert audit.await_args.kwargs["error_code"] == "write_not_permitted"


async def test_add_campaign_negative_keywords_skips_per_campaign_and_maps_errors() -> None:
    client = _CampaignNegativeKeywordClient(
        search_payload={
            "results": [
                {
                    "campaign": {"id": "10"},
                    "campaignCriterion": {
                        "resourceName": "customers/333/campaignCriteria/10~1",
                        "keyword": {"text": "existing", "matchType": "EXACT"},
                    },
                }
            ]
        },
        mutate_payload={
            "results": [
                {"resourceName": "customers/333/campaignCriteria/10~2"},
                {"resourceName": "customers/333/campaignCriteria/20~3"},
                {},
            ],
            "partialFailureError": {
                "details": [
                    {
                        "errors": [
                            {
                                "message": "Keyword is not permitted",
                                "errorCode": {"criterionError": "INVALID_KEYWORD_TEXT"},
                                "location": {
                                    "fieldPathElements": [{"fieldName": "operations", "index": 2}]
                                },
                            }
                        ]
                    }
                ]
            },
        },
    )

    result = await add_campaign_negative_keywords(
        client,
        customer_id="333-333-3333",
        login_customer_id="111",
        campaign_ids=["10", "20"],
        keywords=[
            {"text": "existing", "match_type": "EXACT"},
            {"text": "phrase", "match_type": "PHRASE"},
        ],
    )

    assert "campaign_criterion.negative = TRUE" in client.calls[0]["json"]["query"]
    assert "campaign.id IN (10, 20)" in client.calls[0]["json"]["query"]
    assert client.calls[1]["path"] == "customers/3333333333/campaignCriteria:mutate"
    assert client.calls[1]["json"]["operations"] == [
        {
            "create": {
                "campaign": "customers/3333333333/campaigns/10",
                "negative": True,
                "keyword": {"text": "phrase", "matchType": "PHRASE"},
            }
        },
        {
            "create": {
                "campaign": "customers/3333333333/campaigns/20",
                "negative": True,
                "keyword": {"text": "existing", "matchType": "EXACT"},
            }
        },
        {
            "create": {
                "campaign": "customers/3333333333/campaigns/20",
                "negative": True,
                "keyword": {"text": "phrase", "matchType": "PHRASE"},
            }
        },
    ]
    assert client.calls[1]["json"]["partialFailure"] is True
    assert result["skipped_existing"] == [
        {"campaign_id": "10", "text": "existing", "match_type": "EXACT"}
    ]
    assert [(item["campaign_id"], item["match_type"]) for item in result["added"]] == [
        ("10", "PHRASE"),
        ("20", "EXACT"),
    ]
    assert result["campaign_errors"] == [
        {
            "campaign_id": "20",
            "text": "phrase",
            "match_type": "PHRASE",
            "message": "Keyword is not permitted",
            "error_code": "INVALID_KEYWORD_TEXT",
        }
    ]


async def test_remove_campaign_negative_keywords_resolves_each_campaign_and_any() -> None:
    rows = [
        ("10", "1", "term", "EXACT"),
        ("10", "2", "term", "BROAD"),
        ("20", "3", "Term", "PHRASE"),
    ]
    client = _CampaignNegativeKeywordClient(
        search_payload={
            "results": [
                {
                    "campaign": {"id": campaign_id},
                    "campaignCriterion": {
                        "resourceName": f"customers/333/campaignCriteria/{campaign_id}~{criterion_id}",
                        "keyword": {"text": text, "matchType": match_type},
                    },
                }
                for campaign_id, criterion_id, text, match_type in rows
            ]
        },
        mutate_payload={
            "results": [
                {"resourceName": "customers/333/campaignCriteria/10~1"},
                {},
                {"resourceName": "customers/333/campaignCriteria/20~3"},
            ],
            "partialFailureError": {
                "details": [
                    {
                        "errors": [
                            {
                                "message": "Criterion cannot be removed",
                                "errorCode": {"criterionError": "CANNOT_REMOVE_CRITERION"},
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

    result = await remove_campaign_negative_keywords(
        client,
        customer_id="333",
        login_customer_id="111",
        campaign_ids=["10", "20"],
        keywords=[
            {"text": "TERM", "match_type": "ANY"},
            {"text": "missing", "match_type": "EXACT"},
        ],
    )

    assert client.calls[1]["json"] == {
        "operations": [
            {"remove": "customers/333/campaignCriteria/10~1"},
            {"remove": "customers/333/campaignCriteria/10~2"},
            {"remove": "customers/333/campaignCriteria/20~3"},
        ],
        "partialFailure": True,
    }
    assert [(item["campaign_id"], item["match_type"]) for item in result["removed"]] == [
        ("10", "EXACT"),
        ("20", "PHRASE"),
    ]
    assert result["not_found"] == [
        {"campaign_id": "10", "text": "missing", "match_type": "EXACT"},
        {"campaign_id": "20", "text": "missing", "match_type": "EXACT"},
    ]
    assert result["campaign_errors"][0]["campaign_id"] == "10"
    assert result["campaign_errors"][0]["match_type"] == "BROAD"


async def test_campaign_negative_keyword_fan_out_bound_accepts_2500_operations(
    monkeypatch,
) -> None:
    entry = _writable_google_ads_entry()
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(entry,)))
    )
    client = AsyncMock()
    client.post.return_value = {
        "results": [{"campaign": {"id": str(index), "status": "ENABLED"}} for index in range(1, 51)]
    }
    provider_add = AsyncMock(
        return_value={
            "added": [],
            "resource_names": [],
            "skipped_existing": [],
            "campaign_errors": [],
        }
    )

    async def passthrough_audit(_ctx, _entry, **kwargs):
        return await kwargs["execute"]()

    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.campaign_negative_keywords.google_ads_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.campaign_negative_keywords.add_campaign_negative_keywords",
        provider_add,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.campaign_negative_keywords.run_audited_operation",
        passthrough_audit,
    )

    result = await google_ads_add_campaign_negative_keywords(
        ctx,
        [_campaign_reference(entry, str(index)) for index in range(1, 51)],
        [NegativeKeywordEntry(text=f"term {index}", match_type="EXACT") for index in range(50)],
    )

    assert result.return_value["results"][0]["status"] == "success"
    assert len(provider_add.await_args.kwargs["campaign_ids"]) == 50
    assert len(provider_add.await_args.kwargs["keywords"]) == 50


async def test_campaign_negative_keyword_fan_out_bound_rejects_3000_before_provider(
    monkeypatch,
) -> None:
    entry = _writable_google_ads_entry()
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(entry,)))
    )
    provider_client = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.campaign_negative_keywords.google_ads_client",
        provider_client,
    )

    result = await google_ads_remove_campaign_negative_keywords(
        ctx,
        [_campaign_reference(entry, str(index)) for index in range(1, 7)],
        [
            NegativeKeywordRemovalEntry(text=f"term {index}", match_type="ANY")
            for index in range(500)
        ],
    )

    assert result.return_value["results"][0]["error_code"] == "ModelRetry"
    assert "2,500" in result.return_value["results"][0]["error_message"]
    provider_client.assert_not_awaited()


async def test_campaign_negative_keywords_fail_closed_when_campaign_is_missing(
    monkeypatch,
) -> None:
    entry = _writable_google_ads_entry()
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(entry,)))
    )
    client = AsyncMock()
    client.post.return_value = {"results": []}
    provider_add = AsyncMock()

    async def passthrough_audit(_ctx, _entry, **kwargs):
        return await kwargs["execute"]()

    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.campaign_negative_keywords.google_ads_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.campaign_negative_keywords.add_campaign_negative_keywords",
        provider_add,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.campaign_negative_keywords.run_audited_operation",
        passthrough_audit,
    )

    result = await google_ads_add_campaign_negative_keywords(
        ctx,
        [_campaign_reference(entry, "10")],
        [NegativeKeywordEntry(text="term", match_type="EXACT")],
    )

    assert result.return_value["results"][0]["error_code"] == "ModelRetry"
    assert "campaign is unavailable" in result.return_value["results"][0]["error_message"]
    provider_add.assert_not_awaited()


async def test_campaign_negative_keyword_write_denial_is_audited_before_provider(
    monkeypatch,
) -> None:
    entry = _writable_google_ads_entry(write_allowed=False)
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(entry,)))
    )
    provider_client = AsyncMock()
    audit = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.campaign_negative_keywords.google_ads_client",
        provider_client,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.campaign_negative_keywords.record_google_ads_operation_audit",
        audit,
    )

    add_result = await google_ads_add_campaign_negative_keywords(
        ctx,
        [_campaign_reference(entry, "10")],
        [NegativeKeywordEntry(text="term", match_type="EXACT")],
    )
    remove_result = await google_ads_remove_campaign_negative_keywords(
        ctx,
        [_campaign_reference(entry, "10")],
        [NegativeKeywordRemovalEntry(text="term", match_type="EXACT")],
    )

    assert add_result.return_value["results"][0]["error_code"] == "write_not_permitted"
    assert remove_result.return_value["results"][0]["error_code"] == "write_not_permitted"
    provider_client.assert_not_awaited()
    assert [call.kwargs["operation"] for call in audit.await_args_list] == [
        "add_campaign_negative_keywords",
        "remove_campaign_negative_keywords",
    ]
    assert all(call.kwargs["status"] == AuditStatus.FAILURE for call in audit.await_args_list)


async def test_ad_group_negative_keyword_operations_skip_resolve_and_map_rows() -> None:
    add_client = _AdGroupNegativeKeywordClient(
        search_payload={
            "results": [
                {
                    "adGroup": {"id": "10"},
                    "adGroupCriterion": {
                        "resourceName": "customers/333/adGroupCriteria/10~1",
                        "keyword": {"text": "existing", "matchType": "EXACT"},
                    },
                }
            ]
        },
        mutate_payload={
            "results": [
                {"resourceName": "customers/333/adGroupCriteria/10~2"},
                {"resourceName": "customers/333/adGroupCriteria/20~3"},
                {},
            ],
            "partialFailureError": {
                "details": [
                    {
                        "errors": [
                            {
                                "message": "Keyword is not permitted",
                                "errorCode": {"criterionError": "INVALID_KEYWORD_TEXT"},
                                "location": {
                                    "fieldPathElements": [{"fieldName": "operations", "index": 2}]
                                },
                            }
                        ]
                    }
                ]
            },
        },
    )

    added = await add_ad_group_negative_keywords(
        add_client,
        customer_id="333-333-3333",
        login_customer_id="111",
        ad_group_ids=["10", "20"],
        keywords=[
            {"text": "existing", "match_type": "EXACT"},
            {"text": "phrase", "match_type": "PHRASE"},
        ],
    )

    assert "ad_group_criterion.negative = TRUE" in add_client.calls[0]["json"]["query"]
    assert "ad_group.id IN (10, 20)" in add_client.calls[0]["json"]["query"]
    assert add_client.calls[1]["path"] == "customers/3333333333/adGroupCriteria:mutate"
    assert add_client.calls[1]["json"]["operations"][0]["create"] == {
        "adGroup": "customers/3333333333/adGroups/10",
        "negative": True,
        "keyword": {"text": "phrase", "matchType": "PHRASE"},
    }
    assert added["skipped_existing"] == [
        {"ad_group_id": "10", "text": "existing", "match_type": "EXACT"}
    ]
    assert [(item["ad_group_id"], item["match_type"]) for item in added["added"]] == [
        ("10", "PHRASE"),
        ("20", "EXACT"),
    ]
    assert added["ad_group_errors"][0]["ad_group_id"] == "20"

    rows = [("10", "1", "term", "EXACT"), ("10", "2", "term", "BROAD")]
    remove_client = _AdGroupNegativeKeywordClient(
        search_payload={
            "results": [
                {
                    "adGroup": {"id": ad_group_id},
                    "adGroupCriterion": {
                        "resourceName": (
                            f"customers/333/adGroupCriteria/{ad_group_id}~{criterion_id}"
                        ),
                        "keyword": {"text": text, "matchType": match_type},
                    },
                }
                for ad_group_id, criterion_id, text, match_type in rows
            ]
        },
        mutate_payload={
            "results": [
                {"resourceName": "customers/333/adGroupCriteria/10~1"},
                {"resourceName": "customers/333/adGroupCriteria/10~2"},
            ]
        },
    )
    removed = await remove_ad_group_negative_keywords(
        remove_client,
        customer_id="333",
        login_customer_id="111",
        ad_group_ids=["10", "20"],
        keywords=[
            {"text": "TERM", "match_type": "ANY"},
            {"text": "missing", "match_type": "EXACT"},
        ],
    )
    assert remove_client.calls[1]["json"]["operations"] == [
        {"remove": "customers/333/adGroupCriteria/10~1"},
        {"remove": "customers/333/adGroupCriteria/10~2"},
    ]
    assert len(removed["removed"]) == 2
    assert removed["not_found"] == [
        {"ad_group_id": "10", "text": "missing", "match_type": "EXACT"},
        {"ad_group_id": "20", "text": "TERM", "match_type": "ANY"},
        {"ad_group_id": "20", "text": "missing", "match_type": "EXACT"},
    ]


async def test_ad_group_negative_keyword_tools_bound_and_fail_closed(monkeypatch) -> None:
    entry = _writable_google_ads_entry()
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(entry,)))
    )
    accepted_client = AsyncMock()
    accepted_client.post.return_value = {
        "results": [{"adGroup": {"id": str(index)}} for index in range(1, 51)]
    }
    provider_add = AsyncMock(
        return_value={
            "added": [],
            "resource_names": [],
            "skipped_existing": [],
            "ad_group_errors": [],
        }
    )

    async def passthrough_audit(_ctx, _entry, **kwargs):
        return await kwargs["execute"]()

    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.ad_group_negative_keywords.google_ads_client",
        AsyncMock(return_value=accepted_client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.ad_group_negative_keywords.add_ad_group_negative_keywords",
        provider_add,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.ad_group_negative_keywords.run_audited_operation",
        passthrough_audit,
    )
    accepted = await google_ads_add_ad_group_negative_keywords(
        ctx,
        [_ad_group_reference(entry, str(index)) for index in range(1, 51)],
        [NegativeKeywordEntry(text=f"term {index}", match_type="EXACT") for index in range(50)],
    )
    assert accepted.return_value["results"][0]["status"] == "success"
    assert len(provider_add.await_args.kwargs["ad_group_ids"]) == 50
    assert len(provider_add.await_args.kwargs["keywords"]) == 50

    provider_client = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.ad_group_negative_keywords.google_ads_client",
        provider_client,
    )

    oversized = await google_ads_remove_ad_group_negative_keywords(
        ctx,
        [_ad_group_reference(entry, str(index)) for index in range(1, 7)],
        [
            NegativeKeywordRemovalEntry(text=f"term {index}", match_type="ANY")
            for index in range(500)
        ],
    )

    assert oversized.return_value["results"][0]["error_code"] == "ModelRetry"
    assert "2,500" in oversized.return_value["results"][0]["error_message"]
    provider_client.assert_not_awaited()

    client = AsyncMock()
    client.post.return_value = {"results": []}
    provider_add = AsyncMock()

    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.ad_group_negative_keywords.google_ads_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.ad_group_negative_keywords.add_ad_group_negative_keywords",
        provider_add,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.ad_group_negative_keywords.run_audited_operation",
        passthrough_audit,
    )
    missing = await google_ads_add_ad_group_negative_keywords(
        ctx,
        [_ad_group_reference(entry, "10")],
        [NegativeKeywordEntry(text="term", match_type="EXACT")],
    )
    assert missing.return_value["results"][0]["error_code"] == "ModelRetry"
    assert "ad group is unavailable" in missing.return_value["results"][0]["error_message"]
    provider_add.assert_not_awaited()


async def test_ad_group_negative_keyword_write_denial_is_audited_before_provider(
    monkeypatch,
) -> None:
    entry = _writable_google_ads_entry(write_allowed=False)
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(entry,)))
    )
    provider_client = AsyncMock()
    audit = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.ad_group_negative_keywords.google_ads_client",
        provider_client,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.ad_group_negative_keywords.record_google_ads_operation_audit",
        audit,
    )

    add_result = await google_ads_add_ad_group_negative_keywords(
        ctx,
        [_ad_group_reference(entry, "10")],
        [NegativeKeywordEntry(text="term", match_type="EXACT")],
    )
    remove_result = await google_ads_remove_ad_group_negative_keywords(
        ctx,
        [_ad_group_reference(entry, "10")],
        [NegativeKeywordRemovalEntry(text="term", match_type="EXACT")],
    )

    assert add_result.return_value["results"][0]["error_code"] == "write_not_permitted"
    assert remove_result.return_value["results"][0]["error_code"] == "write_not_permitted"
    provider_client.assert_not_awaited()
    assert [call.kwargs["operation"] for call in audit.await_args_list] == [
        "add_ad_group_negative_keywords",
        "remove_ad_group_negative_keywords",
    ]
    assert all(call.kwargs["status"] == AuditStatus.FAILURE for call in audit.await_args_list)


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


class _NegativeKeywordClient:
    def __init__(self, *, search_payload, mutate_payload):
        self.search_payload = search_payload
        self.mutate_payload = mutate_payload
        self.calls: list[dict] = []

    async def post(self, path: str, **kwargs):
        self.calls.append({"path": path, **kwargs})
        if path.endswith("googleAds:searchStream"):
            return self.search_payload
        if path.endswith("sharedCriteria:mutate"):
            return self.mutate_payload
        raise AssertionError(f"Unexpected Google Ads operation path: {path}")


class _CampaignSharedSetClient:
    def __init__(self, *, search_payload, mutate_payload):
        self.search_payload = search_payload
        self.mutate_payload = mutate_payload
        self.calls: list[dict] = []

    async def post(self, path: str, **kwargs):
        self.calls.append({"path": path, **kwargs})
        if path.endswith("googleAds:searchStream"):
            return self.search_payload
        if path.endswith("campaignSharedSets:mutate"):
            return self.mutate_payload
        raise AssertionError(f"Unexpected Google Ads operation path: {path}")


class _CampaignNegativeKeywordClient:
    def __init__(self, *, search_payload, mutate_payload):
        self.search_payload = search_payload
        self.mutate_payload = mutate_payload
        self.calls: list[dict] = []

    async def post(self, path: str, **kwargs):
        self.calls.append({"path": path, **kwargs})
        if path.endswith("googleAds:searchStream"):
            return self.search_payload
        if path.endswith("campaignCriteria:mutate"):
            return self.mutate_payload
        raise AssertionError(f"Unexpected Google Ads operation path: {path}")


class _AdGroupNegativeKeywordClient:
    def __init__(self, *, search_payload, mutate_payload):
        self.search_payload = search_payload
        self.mutate_payload = mutate_payload
        self.calls: list[dict] = []

    async def post(self, path: str, **kwargs):
        self.calls.append({"path": path, **kwargs})
        if path.endswith("googleAds:searchStream"):
            return self.search_payload
        if path.endswith("adGroupCriteria:mutate"):
            return self.mutate_payload
        raise AssertionError(f"Unexpected Google Ads operation path: {path}")


def _writable_google_ads_entry(*, write_allowed: bool = True) -> ResolvedContextEntry:
    return ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="google_ads",
        resource_type="google_ads_account",
        external_id="111",
        display_name="Ads account",
        connection_id=uuid4(),
        connection_label="Agency",
        connection_status="active",
        write_allowed=write_allowed,
        permissions_metadata={"login_customer_id": "999"},
    )


def _campaign_reference(
    entry: ResolvedContextEntry,
    campaign_id: str,
) -> GoogleAdsCampaignReference:
    return GoogleAdsCampaignReference(
        integration_resource_id=entry.integration_resource_id,
        external_id=campaign_id,
        label=f"Campaign {campaign_id}",
    )


def _ad_group_reference(
    entry: ResolvedContextEntry,
    ad_group_id: str,
) -> GoogleAdsAdGroupReference:
    return GoogleAdsAdGroupReference(
        integration_resource_id=entry.integration_resource_id,
        external_id=ad_group_id,
        label=f"Ad Group {ad_group_id}",
        scope_label="Campaign 1",
    )


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
