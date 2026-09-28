"""Google Ads report and provider read-operation contracts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import (
    ModelRetry,
)

from core.exceptions.integration import IntegrationNotFoundError, IntegrationValidationError
from integrations.google_ads.operations.get_report_field import (
    get_report_field,
    get_report_fields,
)
from integrations.google_ads.operations.list_campaign_device_criteria import (
    list_campaign_device_criteria,
)
from integrations.google_ads.operations.list_campaigns import list_campaigns
from integrations.google_ads.operations.list_report_fields import list_report_fields
from integrations.google_ads.operations.list_shared_sets import list_shared_sets
from integrations.google_ads.operations.run_report import run_report
from integrations.google_ads.operations.utils import (
    escape_gaql_like_literal,
    stream_rows,
)
from integrations.google_ads.tools.run_report import google_ads_run_report
from integrations.google_ads.tools.schemas.report_fields import (
    GoogleAdsGetReportFieldOutput,
    GoogleAdsListReportFieldsOutput,
)
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry
from services.integrations.http import IntegrationRequestPolicy
from tests.integrations.google_ads.support import (
    _OperationClient,
)


def _report_field(
    name: str,
    *,
    category: str = "ATTRIBUTE",
    data_type: str = "STRING",
    **values,
) -> dict:
    return {
        "name": name,
        "category": category,
        "dataType": data_type,
        "selectable": True,
        "filterable": True,
        "sortable": False,
        "isRepeated": False,
        **values,
    }


class _ReportFieldClient:
    def __init__(self, *, resource_payload, search_payload=None) -> None:
        self.resource_payload = resource_payload
        self.search_payload = search_payload
        self.calls: list[dict] = []

    async def get(self, path: str, **kwargs):
        self.calls.append({"method": "GET", "path": path, **kwargs})
        return self.resource_payload

    async def post(self, path: str, **kwargs):
        self.calls.append({"method": "POST", "path": path, **kwargs})
        return self.search_payload


async def test_list_report_fields_rejects_a_repeated_page_token() -> None:
    client = _ReportFieldClient(
        resource_payload=_report_field("campaign", category="RESOURCE", data_type="MESSAGE"),
        search_payload={
            "results": [_report_field("campaign.id", data_type="INT64")],
            "nextPageToken": "more-fields",
        },
    )

    with pytest.raises(IntegrationValidationError, match="complete report field catalogue"):
        await list_report_fields(client, resource="campaign", search=None, limit=2)


@pytest.mark.parametrize(
    "field_name",
    [
        "",
        ".campaign",
    ],
)
async def test_get_report_field_rejects_invalid_names_before_dispatch(field_name: str) -> None:
    client = AsyncMock()

    with pytest.raises(ValueError, match="report field name"):
        await get_report_field(client, field_name=field_name)

    client.get.assert_not_awaited()


@pytest.mark.parametrize(
    "payload",
    [
        None,
    ],
)
async def test_get_report_field_rejects_malformed_metadata(payload) -> None:
    client = _ReportFieldClient(resource_payload=payload)

    with pytest.raises(IntegrationValidationError, match="invalid report field response"):
        await get_report_field(client, field_name="campaign.name")


class _BatchFieldClient:
    def __init__(self, payloads: dict[str, object]) -> None:
        self.payloads = payloads
        self.paths: list[str] = []

    async def get(self, path: str, **_kwargs):
        self.paths.append(path)
        payload = self.payloads[path.removeprefix("googleAdsFields/")]
        if isinstance(payload, Exception):
            raise payload
        return payload


async def test_get_report_fields_batches_names_and_reports_missing_ones() -> None:
    client = _BatchFieldClient(
        {
            "campaign.status": _report_field(
                "campaign.status", data_type="ENUM", enumValues=["PAUSED", "ENABLED"]
            ),
            "campaign.nope": IntegrationNotFoundError(
                "Integration resource was not found",
                provider_key="google_ads",
                operation="get_report_field",
            ),
            "metrics.clicks": _report_field("metrics.clicks", category="METRIC", data_type="INT64"),
        }
    )

    result = await get_report_fields(
        client,
        field_names=[" campaign.status ", "campaign.nope", "campaign.status", "metrics.clicks"],
    )

    assert GoogleAdsGetReportFieldOutput.model_validate(result)
    assert result["api_version"] == "v24"
    assert [field["name"] for field in result["fields"]] == ["campaign.status", "metrics.clicks"]
    assert result["fields"][0]["enum_values"] == ["ENABLED", "PAUSED"]
    assert result["missing"] == ["campaign.nope"]
    assert client.paths == [
        "googleAdsFields/campaign.status",
        "googleAdsFields/campaign.nope",
        "googleAdsFields/metrics.clicks",
    ]


@pytest.mark.parametrize(
    "query",
    [
        "SELECT campaign.name FROM campaign",
    ],
)
async def test_report_preserves_query_and_every_streamed_row(query: str) -> None:
    rows = [{"campaign": {"name": str(index)}} for index in range(1_500)]
    client = _OperationClient([{"results": rows[:800]}, {"results": rows[800:]}])
    result = await run_report(
        client,
        customer_id="333",
        currency_code="GBP",
        login_customer_id="111",
        query=query,
        max_response_bytes=1_000_000,
    )
    assert result["currency_code"] == "GBP"
    assert result["row_count"] == 1_500
    assert result["truncated"] is False
    assert result["truncation_note"] is None
    assert result["rows"] == rows
    assert client.last_json["query"] == query


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
        ),
        tool_name="google_ads_run_report",
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
        "services.integrations.operations.record_integration_operation_audit_event",
        AsyncMock(),
    )

    result = await google_ads_run_report(ctx, "SELECT campaign.id FROM campaign")

    assert result["results"][0]["data"]["currency_code"] == "GBP"
    assert provider_report.await_args.kwargs["currency_code"] == "GBP"


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
        minimum_id=10,
        minimum_id_inclusive=False,
        limit=101,
        exclude_removed=True,
    )

    assert campaigns == [{"id": "10", "name": "Brand", "status": "ENABLED"}]
    assert "campaign.status != 'REMOVED'" in client.last_json["query"]
    assert "campaign.id IN (10, 20)" in client.last_json["query"]
    assert "campaign.id > 10" in client.last_json["query"]
    assert "LIKE '%Brand\\'s \\\\ sale[%][_][[][]]%'" in client.last_json["query"]
    assert "ORDER BY campaign.id LIMIT 101" in client.last_json["query"]


async def test_list_campaign_device_criteria_assembles_strategy_and_device_state() -> None:
    class Client:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def post(self, path: str, **kwargs):
            self.calls.append({"path": path, **kwargs})
            if "FROM campaign_criterion" in kwargs["json"]["query"]:
                return {
                    "results": [
                        {
                            "campaign": {"id": "10"},
                            "campaignCriterion": {
                                "criterionId": "30001",
                                "device": {"type": "MOBILE"},
                                "bidModifier": 0.7,
                                "status": "ENABLED",
                            },
                        },
                        {
                            "campaign": {"id": "10"},
                            "campaignCriterion": {
                                "criterionId": "30002",
                                "device": {"type": "TABLET"},
                                "bidModifier": 0.6,
                                "status": "REMOVED",
                            },
                        },
                    ]
                }
            return {
                "results": [
                    {
                        "campaign": {
                            "id": "10",
                            "status": "ENABLED",
                            "biddingStrategyType": "MANUAL_CPC",
                        }
                    },
                    {
                        "campaign": {
                            "id": "20",
                            "status": "PAUSED",
                            "biddingStrategyType": "TARGET_ROAS",
                            "maximizeConversions": {"targetCpaMicros": "2500000"},
                        }
                    },
                ]
            }

    client = Client()
    result = await list_campaign_device_criteria(
        client,
        customer_id="333-333-3333",
        login_customer_id="111",
        campaign_ids=("20", "10", "20"),
    )

    assert result == {
        "10": {
            "bidding_strategy_type": "MANUAL_CPC",
            "target_cpa_configured": False,
            "devices": {"MOBILE": {"criterion_id": "30001", "bid_modifier": 0.7}},
        },
        "20": {
            "bidding_strategy_type": "TARGET_ROAS",
            "target_cpa_configured": True,
            "devices": {},
        },
    }
    campaign_query = client.calls[0]["json"]["query"]
    criterion_query = client.calls[1]["json"]["query"]
    assert "campaign.status != 'REMOVED'" in campaign_query
    assert "campaign.id IN (10, 20)" in campaign_query
    assert "campaign.maximize_conversions.target_cpa_micros" in campaign_query
    assert "bidding_strategy.maximize_conversions.target_cpa_micros" in campaign_query
    assert "campaign_criterion.type = 'DEVICE'" in criterion_query
    assert "campaign_criterion.status != 'REMOVED'" in criterion_query
    assert "campaign.id IN (10, 20)" in criterion_query
    assert all(call["policy"] is IntegrationRequestPolicy.READ for call in client.calls)


@pytest.mark.parametrize(
    ("operation", "id_name"),
    [
        (list_campaigns, "campaign_ids"),
    ],
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
    with pytest.raises(ValueError, match="minimum id"):
        await operation(client, **common, minimum_id=-1)


@pytest.mark.parametrize(
    ("search", "escaped"),
    [
        ("[", "[[]"),
        ("]", "[]]"),
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
        "ORDER BY shared_set.id LIMIT 1"
    ).replace("SEARCH_LITERAL", escaped)
    assert client.last_json["query"] == expected_query


def test_gaql_like_literal_length_bound_never_splits_an_escape_sequence() -> None:
    assert escape_gaql_like_literal("ab%", max_length=5) == "ab[%]"
    assert escape_gaql_like_literal("abc%", max_length=5) == "abc"
    assert escape_gaql_like_literal(f"{'a' * 199}%") == "a" * 199


async def test_list_report_fields_retains_all_pages_and_compatibility_by_default() -> None:
    fields = [_report_field(f"campaign.field_{index:04}") for index in range(2101)]
    client = SimpleNamespace(
        get=AsyncMock(
            return_value=_report_field(
                "campaign",
                category="RESOURCE",
                data_type="MESSAGE",
                attributeResources=[f"resource_{index:03}" for index in range(101)],
                metrics=[f"metrics.value_{index:03}" for index in range(201)],
                segments=[f"segments.value_{index:03}" for index in range(201)],
            )
        ),
        post=AsyncMock(
            side_effect=[
                {"results": fields[:2000], "nextPageToken": "last", "totalResultsCount": "2101"},
                {"results": fields[2000:], "totalResultsCount": "2101"},
            ]
        ),
    )
    result = await list_report_fields(client, resource="campaign", search=None)
    assert GoogleAdsListReportFieldsOutput.model_validate(result)
    assert len(result["fields"]) == 2101
    assert len(result["metrics"]) == len(result["segments"]) == 201
    assert len(result["attribute_resources"]) == 101
    assert result["truncated"] is False
    assert result["compatibility_truncated"] is False
    calls = client.post.await_args_list
    assert "LIMIT" not in calls[0].kwargs["json"]["query"]
    assert calls[1].kwargs["json"]["pageToken"] == "last"
    assert calls[1].kwargs["max_response_bytes"] < calls[0].kwargs["max_response_bytes"]
