"""Google Ads campaign budget creation contracts."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from pydantic_ai import ModelRetry

from integrations.google_ads.operations.create_campaign_budget import create_campaign_budget
from integrations.google_ads.operations.list_campaign_budgets import list_campaign_budgets
from integrations.google_ads.references import GoogleAdsCampaignBudgetReference
from integrations.google_ads.tools.create_campaign_budget import (
    DEFINITION,
    google_ads_create_campaign_budget,
)
from integrations.google_ads.tools.schemas import (
    GoogleAdsCreateCampaignBudgetOutput,
    GoogleAdsDailyBudgetAmount,
    GoogleAdsTotalBudgetAmount,
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


class SequencedClient:
    def __init__(self, payloads):
        self.payloads = iter(payloads)
        self.calls = []

    async def post(self, path, **kwargs):
        self.calls.append((path, kwargs))
        return next(self.payloads)


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
        permissions_metadata={"login_customer_id": "111", "currency_code": "GBP"},
    )


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
        ("1e2", "positive decimal"),
        ("9223372036854.775808", "too large"),
    ],
)
def test_money_to_micros_rejects_invalid_provider_values(value: str, message: str) -> None:
    with pytest.raises(ModelRetry, match=message):
        money_to_micros(value)


@pytest.mark.parametrize(
    "amount_type",
    [GoogleAdsDailyBudgetAmount, GoogleAdsTotalBudgetAmount],
)
def test_campaign_budget_amount_rejects_oversized_decimal_strings(amount_type) -> None:
    field_name = "daily_amount" if amount_type is GoogleAdsDailyBudgetAmount else "total_amount"
    with pytest.raises(ValidationError, match="at most 32 characters"):
        amount_type.model_validate({field_name: "1" * 33})


def test_campaign_budget_reference_canonicalizes_resource_name() -> None:
    reference = GoogleAdsCampaignBudgetReference.model_validate(
        {
            "customer_id": "930-870-8411",
            "budget_id": "customers/9308708411/campaignBudgets/55",
            "label": "Daily budget",
        }
    )
    assert reference.customer_id == "9308708411"
    assert reference.budget_id == "55"


def test_campaign_budget_reference_rejects_non_digit_ids() -> None:
    with pytest.raises(ValidationError):
        GoogleAdsCampaignBudgetReference(customer_id="333", budget_id="budget-55", label="Budget")


def test_campaign_budget_reference_rejects_cross_account_resource_name() -> None:
    with pytest.raises(ValidationError, match="must belong to its customer"):
        GoogleAdsCampaignBudgetReference(
            customer_id="333",
            budget_id="customers/999/campaignBudgets/55",
            label="Budget",
        )


async def test_list_campaign_budgets_returns_currency_and_bounded_campaign_labels() -> None:
    client = SequencedClient(
        [
            [
                {
                    "results": [
                        {
                            "campaignBudget": {
                                "id": "55",
                                "name": "Launch budget",
                                "status": "ENABLED",
                                "period": "DAILY",
                                "amountMicros": "12500000",
                                "explicitlyShared": True,
                                "referenceCount": "1",
                            },
                            "customer": {"currencyCode": "GBP"},
                        }
                    ]
                }
            ],
            [
                {
                    "results": [
                        {
                            "campaign": {
                                "id": "9",
                                "name": "Autumn launch",
                                "campaignBudget": "customers/333/campaignBudgets/55",
                            }
                        }
                    ]
                }
            ],
        ]
    )
    rows = await list_campaign_budgets(
        client,
        customer_id="333",
        login_customer_id="111",
        budget_ids=["55"],
        limit=1,
    )
    assert rows == [
        {
            "id": "55",
            "name": "Launch budget",
            "status": "ENABLED",
            "period": "DAILY",
            "amountMicros": "12500000",
            "explicitlyShared": True,
            "referenceCount": "1",
            "currencyCode": "GBP",
            "campaignLabels": ("Autumn launch",),
        }
    ]
    assert all(call[1]["policy"] is IntegrationRequestPolicy.READ for call in client.calls)
    assert "campaign_budget.id IN (55)" in client.calls[0][1]["json"]["query"]


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


@pytest.mark.parametrize(
    ("period", "amount_field", "explicitly_shared"),
    [("DAILY", "amountMicros", True), ("CUSTOM_PERIOD", "totalAmountMicros", False)],
)
async def test_create_campaign_budget_uses_pinned_amount_field(
    period, amount_field, explicitly_shared
) -> None:
    client = Client({"results": [{"resourceName": "customers/333/campaignBudgets/55"}]})
    ledger = await create_campaign_budget(
        client,
        customer_id="333",
        login_customer_id="111",
        name="Autumn launch",
        period=period,
        amount_micros=12_500_000,
        explicitly_shared=explicitly_shared,
        delivery_method="STANDARD",
    )
    assert client.path == "customers/333/campaignBudgets:mutate"
    assert client.kwargs["policy"] is IntegrationRequestPolicy.MUTATION
    assert client.kwargs["json"] == {
        "operations": [
            {
                "create": {
                    "name": "Autumn launch",
                    "period": period,
                    amount_field: "12500000",
                    "explicitlyShared": explicitly_shared,
                    "deliveryMethod": "STANDARD",
                }
            }
        ],
        "partialFailure": True,
    }
    assert ledger.external_refs == ("customers/333/campaignBudgets/55",)


async def test_create_campaign_budget_keeps_failed_and_unverified_outcomes_distinct() -> None:
    rejected = await create_campaign_budget(
        Client(
            {
                "results": [{}],
                "partialFailureError": {
                    "details": [
                        {
                            "errors": [
                                {
                                    "message": "Duplicate name",
                                    "errorCode": {"campaignBudgetError": "DUPLICATE_NAME"},
                                    "location": {
                                        "fieldPathElements": [
                                            {"fieldName": "operations", "index": 0}
                                        ]
                                    },
                                }
                            ]
                        }
                    ]
                },
            }
        ),
        customer_id="333",
        login_customer_id="111",
        name="Budget",
        period="DAILY",
        amount_micros=1_000_000,
        explicitly_shared=False,
        delivery_method="STANDARD",
    )
    ambiguous = await create_campaign_budget(
        Client({"results": [{"resourceName": "customers/999/campaignBudgets/55"}]}),
        customer_id="333",
        login_customer_id="111",
        name="Budget",
        period="DAILY",
        amount_micros=1_000_000,
        explicitly_shared=False,
        delivery_method="STANDARD",
    )
    assert rejected.effects[0].outcome == "failed"
    assert rejected.effects[0].error_code == "DUPLICATE_NAME"
    assert ambiguous.effects[0].outcome == "unverified"


async def test_create_campaign_budget_tool_returns_typed_reference_and_audit(monkeypatch) -> None:
    selected = entry()
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(selected,))),
        tool_name=DEFINITION.name,
    )
    client = Client({"results": [{"resourceName": "customers/333/campaignBudgets/55"}]})
    audit_outcomes = []

    async def passthrough_audit(_ctx, _entry, **kwargs):
        outcome = await kwargs["execute"]()
        audit_outcomes.append(outcome)
        return outcome.value

    monkeypatch.setattr(
        "integrations.google_ads.tools.create_campaign_budget.google_ads_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.create_campaign_budget.run_audited_integration_operation",
        passthrough_audit,
    )
    result = await google_ads_create_campaign_budget(
        ctx,
        "  Autumn   launch  ",
        GoogleAdsDailyBudgetAmount(daily_amount="12.50"),
        True,
        "STANDARD",
    )
    output = GoogleAdsCreateCampaignBudgetOutput.model_validate(result)
    data = output.results[0].data
    assert data is not None, result["results"][0].get("error_message")
    assert data.model_dump(exclude_none=True)["reference"] == {
        "entity_kind": "google_ads_campaign_budget",
        "version": 1,
        "label": "Autumn launch",
        "description": "Campaign budget",
        "customer_id": "333",
        "budget_id": "55",
        "status": "ENABLED",
        "period": "DAILY",
        "delivery_method": "STANDARD",
        "amount_micros": 12_500_000,
        "explicitly_shared": True,
        "reference_count": 0,
        "currency_code": "GBP",
        "campaign_labels": (),
        "scope_label": "Retail account",
    }
    detail = audit_outcomes[0].operation_detail
    assert detail.intent_counts.applied == 1
    assert detail.effect_counts.applied == 1
    assert detail.intent_groups[0].items[0].fields["amount"] == "12.5"


async def test_create_campaign_budget_tool_retains_unverified_result(monkeypatch) -> None:
    selected = entry()
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(selected,)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name=DEFINITION.name,
        tool_call_id="create-budget-call",
    )
    client = Client({"results": [{"resourceName": "customers/999/campaignBudgets/55"}]})
    monkeypatch.setattr(
        "integrations.google_ads.tools.create_campaign_budget.google_ads_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        AsyncMock(return_value=uuid4()),
    )

    result = await google_ads_create_campaign_budget(
        ctx,
        "Budget",
        GoogleAdsDailyBudgetAmount(daily_amount="12.50"),
        False,
        "STANDARD",
    )

    output = GoogleAdsCreateCampaignBudgetOutput.model_validate(result)
    item = output.results[0]
    assert item.status == "error"
    assert item.error_code == "unverified_mutation"
    assert item.data is not None
    assert item.data.outcome == "unverified"
    assert item.data.name == "Budget"
    assert item.data.amount == "12.5"
    assert item.data.reference is None


async def test_create_campaign_budget_rejects_missing_currency_before_mutation(monkeypatch) -> None:
    selected = entry()
    selected = replace(selected, permissions_metadata={"login_customer_id": "111"})
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(selected,))),
        tool_name=DEFINITION.name,
    )
    provider_client = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.create_campaign_budget.google_ads_client",
        provider_client,
    )
    result = await google_ads_create_campaign_budget(
        ctx,
        "Budget",
        GoogleAdsTotalBudgetAmount(total_amount="50"),
        False,
        "STANDARD",
    )
    assert result["results"][0]["status"] == "error"
    assert "currency information" in result["results"][0]["error_message"]
    provider_client.assert_not_awaited()


async def test_create_campaign_budget_rejects_shared_total_before_dispatch(monkeypatch) -> None:
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(entry(),))),
        tool_name=DEFINITION.name,
    )
    provider_client = AsyncMock()
    fan_out = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.create_campaign_budget.google_ads_client",
        provider_client,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.create_campaign_budget.run_context_fan_out",
        fan_out,
    )

    with pytest.raises(ModelRetry, match="can't be shared"):
        await google_ads_create_campaign_budget(
            ctx,
            "Budget",
            GoogleAdsTotalBudgetAmount(total_amount="50"),
            True,
            "STANDARD",
        )

    fan_out.assert_not_awaited()
    provider_client.assert_not_awaited()


async def test_create_campaign_budget_rejects_accelerated_total_before_dispatch(
    monkeypatch,
) -> None:
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(entry(),))),
        tool_name=DEFINITION.name,
    )
    provider_client = AsyncMock()
    fan_out = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.create_campaign_budget.google_ads_client",
        provider_client,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.create_campaign_budget.run_context_fan_out",
        fan_out,
    )

    with pytest.raises(ModelRetry, match="require standard delivery"):
        await google_ads_create_campaign_budget(
            ctx,
            "Budget",
            GoogleAdsTotalBudgetAmount(total_amount="50"),
            False,
            "ACCELERATED",
        )

    fan_out.assert_not_awaited()
    provider_client.assert_not_awaited()


def test_campaign_budget_definition_is_approval_only_and_code_eligible() -> None:
    assert DEFINITION.default_policy == "approval"
    assert DEFINITION.supports_auto is False
    assert DEFINITION.code_eligible is True
    assert "recommend" in DEFINITION.description
    delivery_method = next(
        field for field in DEFINITION.presentation.arg_fields if field.key == "delivery_method"
    )
    assert delivery_method.editable is True
    assert delivery_method.options == ("STANDARD", "ACCELERATED")
