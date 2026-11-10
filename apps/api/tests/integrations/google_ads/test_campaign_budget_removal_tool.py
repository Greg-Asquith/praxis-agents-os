# apps/api/tests/integrations/google_ads/test_campaign_budget_removal_tool.py

"""Exact budget money, budget references, and campaign budget removal."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from pydantic_ai import ModelRetry

from integrations.google_ads.operations.remove_campaign_budgets import remove_campaign_budgets
from integrations.google_ads.references import GoogleAdsCampaignBudgetReference
from integrations.google_ads.tools.remove_campaign_budgets import (
    DEFINITION as REMOVE_DEFINITION,
    google_ads_remove_campaign_budgets,
)
from integrations.google_ads.tools.utils.money import money_to_micros
from integrations.google_ads.tools.verifiers.campaign_budget import verify_campaign_budgets
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry
from services.integrations.http import IntegrationRequestPolicy


class Client:
    def __init__(self, payload):
        self.payload = payload
        self.path = None
        self.kwargs = None

    async def post(self, path, **kwargs):
        self.path = path
        self.kwargs = kwargs
        return self.payload


def entry() -> ResolvedContextEntry:
    return ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="google_ads",
        resource_type="google_ads_account",
        external_id="333",
        display_name="Retail account",
        connection_id=uuid4(),
        connection_label="Google Ads",
        connection_status="active",
        write_allowed=True,
        permissions_metadata={
            "login_customer_id": "111",
            "currency_code": "GBP",
            "time_zone": "Europe/London",
        },
    )


def budget_row(
    budget_id: str,
    *,
    name: str,
    explicitly_shared: bool,
    reference_count: int,
    period: str = "DAILY",
) -> dict[str, object]:
    row: dict[str, object] = {
        "id": budget_id,
        "name": name,
        "status": "ENABLED",
        "period": period,
        "deliveryMethod": "STANDARD",
        "explicitlyShared": explicitly_shared,
        "referenceCount": str(reference_count),
        "currencyCode": "GBP",
        "campaignLabels": (),
    }
    row["amountMicros" if period == "DAILY" else "totalAmountMicros"] = "12500000"
    return row


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1", 1_000_000), ("1.000001", 1_000_001), ("0004.50", 4_500_000)],
)
def test_money_to_micros_is_exact(value: str, expected: int) -> None:
    assert money_to_micros(value) == expected


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("0", "greater than zero"),
        ("-1", "positive decimal"),
        ("1.0000001", "six decimal places"),
        ("9223372036854.775808", "too large"),
    ],
)
def test_money_to_micros_rejects_invalid_provider_values(value: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        money_to_micros(value)


def test_campaign_budget_reference_rejects_cross_account_resource_name() -> None:
    with pytest.raises(ValidationError, match="must belong to its customer"):
        GoogleAdsCampaignBudgetReference(
            customer_id="333",
            budget_id="customers/999/campaignBudgets/55",
            label="Budget",
        )


async def test_campaign_budget_verifier_fails_closed_for_stale_reference(monkeypatch) -> None:
    list_budgets = AsyncMock(return_value=[])
    monkeypatch.setattr(
        "integrations.google_ads.tools.verifiers.campaign_budget.list_campaign_budgets",
        list_budgets,
    )
    with pytest.raises(ModelRetry, match="no longer available"):
        await verify_campaign_budgets(
            Client({}),
            entry=entry(),
            budget_ids=["55"],  # type: ignore[arg-type]
        )


async def test_remove_campaign_budgets_uses_pinned_remove_payload() -> None:
    client = Client(
        {
            "results": [
                {"resourceName": "customers/333/campaignBudgets/44"},
                {"resourceName": "customers/333/campaignBudgets/55"},
            ]
        }
    )

    ledger = await remove_campaign_budgets(
        client,
        customer_id="333",
        login_customer_id="111",
        budget_ids=["44", "55"],
    )

    assert client.path == "customers/333/campaignBudgets:mutate"
    assert client.kwargs["policy"] is IntegrationRequestPolicy.MUTATION
    assert client.kwargs["json"] == {
        "operations": [
            {"remove": "customers/333/campaignBudgets/44"},
            {"remove": "customers/333/campaignBudgets/55"},
        ],
        "partialFailure": True,
    }
    assert [item["budget_id"] for item in ledger.result()["removed"]] == ["44", "55"]


async def test_remove_campaign_budget_tool_rejects_live_linked_budget(monkeypatch) -> None:
    selected = entry()
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(selected,))),
        tool_name=REMOVE_DEFINITION.name,
    )
    reference = GoogleAdsCampaignBudgetReference(
        customer_id="333",
        budget_id="55",
        label="Selected budget",
    )
    provider_client = Client({})

    async def passthrough_audit(_ctx, _entry, **kwargs):
        await kwargs["prepare_pending_operation"]()
        return await kwargs["execute"]()

    monkeypatch.setattr(
        "integrations.google_ads.tools.remove_campaign_budgets.google_ads_client",
        AsyncMock(return_value=provider_client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.remove_campaign_budgets.verify_campaign_budgets",
        AsyncMock(
            return_value={
                "55": budget_row(
                    "55",
                    name="Linked budget",
                    explicitly_shared=True,
                    reference_count=2,
                )
            }
        ),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.remove_campaign_budgets.run_audited_integration_operation",
        passthrough_audit,
    )

    result = await google_ads_remove_campaign_budgets(ctx, [reference])

    assert result.return_value["results"][0]["status"] == "error"
    assert "linked to campaigns" in result.return_value["results"][0]["error_message"]
    assert provider_client.path is None
