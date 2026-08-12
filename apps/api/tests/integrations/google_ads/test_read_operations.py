"""Google Ads report and provider read-operation contracts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import (
    ModelRetry,
)

from integrations.google_ads.operations.list_accounts import list_accounts
from integrations.google_ads.operations.list_ad_groups import list_ad_groups
from integrations.google_ads.operations.list_campaigns import list_campaigns
from integrations.google_ads.operations.list_shared_sets import list_shared_sets
from integrations.google_ads.operations.run_report import run_report
from integrations.google_ads.operations.utils import (
    bounded_query,
    escape_gaql_like_literal,
    stream_rows,
)
from integrations.google_ads.tools.list_accounts import google_ads_list_accounts
from integrations.google_ads.tools.run_report import google_ads_run_report
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry
from tests.integrations.google_ads.support import (
    _OperationClient,
)


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
        ),
        tool_name="google_ads_list_accounts",
    )
    operation = AsyncMock(
        side_effect=[
            {"accounts": [{"customer_id": "222"}]},
            {"accounts": [{"customer_id": "333"}]},
        ]
    )
    monkeypatch.setattr("integrations.google_ads.tools.list_accounts.list_accounts", operation)
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
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


async def test_list_shared_sets_filters_enabled_negative_keyword_lists_and_escapes_search() -> None:
    client = _OperationClient({"results": [{"sharedSet": {"id": "50"}}]})

    assert await list_shared_sets(
        client,
        customer_id="333-333-3333",
        login_customer_id="111",
        shared_set_type="NEGATIVE_KEYWORDS",
        shared_set_ids=("50",),
        search="Brand's \\ list",
        minimum_id=50,
        minimum_id_inclusive=True,
        limit=1,
    )
    assert "shared_set.status = 'ENABLED'" in client.last_json["query"]
    assert "shared_set.type = 'NEGATIVE_KEYWORDS'" in client.last_json["query"]
    assert "shared_set.id IN (50)" in client.last_json["query"]
    assert "shared_set.id >= 50" in client.last_json["query"]
    assert "LIKE '%Brand\\'s \\\\ list%'" in client.last_json["query"]
    assert "ORDER BY shared_set.id LIMIT 1" in client.last_json["query"]


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
        minimum_id=10,
        minimum_id_inclusive=True,
        limit=101,
        exclude_removed=True,
    ) == [row]
    assert "ad_group.status != 'REMOVED'" in client.last_json["query"]
    assert "ad_group.id IN (10, 20)" in client.last_json["query"]
    assert "ad_group.id >= 10" in client.last_json["query"]
    assert "ad_group.name LIKE '%Group\\'s \\\\ sale%'" in client.last_json["query"]
    assert "ORDER BY ad_group.id LIMIT 101" in client.last_json["query"]


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
    with pytest.raises(ValueError, match="minimum id"):
        await operation(client, **common, minimum_id=-1)


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
        "ORDER BY shared_set.id LIMIT 1"
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
        "ORDER BY shared_set.id LIMIT 1"
    ).replace("SEARCH_LITERAL", "a" * 199)
    assert client.last_json["query"] == expected_query


async def test_list_shared_sets_requires_a_bounded_result() -> None:
    client = _OperationClient({"results": []})

    with pytest.raises(ValueError, match="between 1 and 101"):
        await list_shared_sets(
            client,
            customer_id="3333333333",
            login_customer_id="111",
            shared_set_type="NEGATIVE_KEYWORDS",
            limit=0,
        )


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
