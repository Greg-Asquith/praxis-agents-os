"""Google Ads campaign budget action contracts."""

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from pydantic_ai import ModelRetry

from integrations.google_ads.operations.assign_campaign_budgets import (
    GoogleAdsCampaignBudgetAssignment,
    assign_campaign_budgets,
)
from integrations.google_ads.operations.create_campaign_budget import create_campaign_budget
from integrations.google_ads.operations.list_campaign_budgets import list_campaign_budgets
from integrations.google_ads.operations.mutation_outcomes import (
    GoogleAdsMutationProjection,
    build_mutation_ledger,
)
from integrations.google_ads.operations.remove_campaign_budgets import remove_campaign_budgets
from integrations.google_ads.operations.update_campaign_budget_amounts import (
    GoogleAdsCampaignBudgetAmountChange,
    update_campaign_budget_amounts,
)
from integrations.google_ads.references import (
    GoogleAdsCampaignBudgetReference,
    GoogleAdsCampaignReference,
)
from integrations.google_ads.tools.assign_campaign_budgets import (
    DEFINITION as ASSIGN_DEFINITION,
    google_ads_assign_campaign_budgets,
)
from integrations.google_ads.tools.create_campaign_budget import (
    DEFINITION,
    google_ads_create_campaign_budget,
)
from integrations.google_ads.tools.remove_campaign_budgets import (
    DEFINITION as REMOVE_DEFINITION,
    google_ads_remove_campaign_budgets,
)
from integrations.google_ads.tools.schemas import (
    GoogleAdsAssignCampaignBudgetsOutput,
    GoogleAdsCampaignBudgetAmountUpdate,
    GoogleAdsCreateCampaignBudgetOutput,
    GoogleAdsDailyBudgetAmount,
    GoogleAdsRemoveCampaignBudgetsOutput,
    GoogleAdsTotalBudgetAmount,
    GoogleAdsUpdateCampaignBudgetAmountsOutput,
)
from integrations.google_ads.tools.update_campaign_budget_amounts import (
    DEFINITION as UPDATE_DEFINITION,
    google_ads_update_campaign_budget_amounts,
)
from integrations.google_ads.tools.utils.campaign_budget_assignment_results import (
    MAX_CAMPAIGN_BUDGET_ASSIGNMENT_DISPLAY_DATA_CHARS,
    MAX_CAMPAIGN_BUDGET_ASSIGNMENT_PUBLIC_RESULT_CHARS,
    MAX_CAMPAIGN_BUDGET_ASSIGNMENT_RESULT_CHARS,
    bounded_campaign_budget_assignment_result,
    display_campaign_budget_assignment_result,
)
from integrations.google_ads.tools.utils.campaign_budget_removal_results import (
    MAX_CAMPAIGN_BUDGET_REMOVAL_DISPLAY_DATA_CHARS,
    MAX_CAMPAIGN_BUDGET_REMOVAL_PUBLIC_RESULT_CHARS,
    MAX_CAMPAIGN_BUDGET_REMOVAL_RESULT_CHARS,
    bounded_campaign_budget_removal_result,
    display_campaign_budget_removal_result,
)
from integrations.google_ads.tools.utils.campaign_budget_results import (
    MAX_CAMPAIGN_BUDGET_AMOUNT_DISPLAY_DATA_CHARS,
    MAX_CAMPAIGN_BUDGET_AMOUNT_PUBLIC_RESULT_CHARS,
    MAX_CAMPAIGN_BUDGET_AMOUNT_RESULT_CHARS,
    bounded_campaign_budget_amount_result,
    display_campaign_budget_amount_result,
)
from integrations.google_ads.tools.utils.money import money_to_micros
from integrations.google_ads.tools.verifiers.campaign import (
    verify_campaigns_for_budget_assignment,
)
from integrations.google_ads.tools.verifiers.campaign_budget import verify_campaign_budgets
from services.agent_runs.validate_override_args import validate_and_canonicalize_override_args
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


def campaign(campaign_id: str, *, label: str = "Campaign") -> GoogleAdsCampaignReference:
    return GoogleAdsCampaignReference(
        customer_id="333",
        campaign_id=campaign_id,
        label=label,
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


@pytest.mark.parametrize(
    ("amount_type", "field_name"),
    [
        (GoogleAdsDailyBudgetAmount, "daily_amount"),
        (GoogleAdsTotalBudgetAmount, "total_amount"),
    ],
)
def test_campaign_budget_amount_schema_describes_currency_decimal_contract(
    amount_type, field_name
) -> None:
    description = amount_type.model_json_schema()["properties"][field_name]["description"]
    assert "positive decimal" in description.lower()
    assert "account currency" in description
    assert "up to six decimal places" in description
    assert "not micros" in description


def test_campaign_budget_amount_results_bound_rows_and_campaign_labels() -> None:
    labels = tuple(f"Campaign {index}: {'x' * 500}" for index in range(50))
    budgets = [
        {
            "reference": GoogleAdsCampaignBudgetReference(
                customer_id="333",
                budget_id=str(index + 1),
                label=f"Budget {index}",
                campaign_labels=labels,
            ),
            "previous_amount": "1",
            "requested_amount": "2",
            "previous_amount_micros": 1_000_000,
            "requested_amount_micros": 2_000_000,
            "outcome": "updated",
            "external_ref": f"customers/333/campaignBudgets/{index + 1}",
            "error_code": None,
            "message": None,
        }
        for index in range(100)
    ]

    model_result = bounded_campaign_budget_amount_result({"budgets": budgets})
    display_result = display_campaign_budget_amount_result({"budgets": budgets})

    assert len(json.dumps(model_result, ensure_ascii=False)) <= (
        MAX_CAMPAIGN_BUDGET_AMOUNT_RESULT_CHARS
    )
    assert len(json.dumps(display_result, ensure_ascii=False)) <= (
        MAX_CAMPAIGN_BUDGET_AMOUNT_DISPLAY_DATA_CHARS
    )
    assert model_result["counts"] == {
        "updated": 100,
        "already_set": 0,
        "failed": 0,
        "unverified": 0,
    }
    assert model_result["samples_truncated"] is True
    assert model_result["campaign_labels_truncated"] is True
    sample = model_result["samples"]["updated"][0]
    assert sample["campaign_label_count"] == 50
    assert sample["campaign_labels_truncated"] is True
    assert len(sample["reference"]["campaign_labels"]) == 3
    assert all(len(label) <= 80 for label in sample["reference"]["campaign_labels"])
    assert display_result["samples_truncated"] is True


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


async def test_update_campaign_budget_amounts_uses_live_period_masks_and_skips_noop() -> None:
    client = Client(
        {
            "results": [
                {"resourceName": "customers/333/campaignBudgets/55"},
                {"resourceName": "customers/333/campaignBudgets/77"},
            ]
        }
    )

    ledger = await update_campaign_budget_amounts(
        client,
        customer_id="333",
        login_customer_id="111",
        changes=[
            GoogleAdsCampaignBudgetAmountChange("44", "DAILY", 1_000_000, 1_000_000),
            GoogleAdsCampaignBudgetAmountChange("55", "DAILY", 1_000_000, 2_500_000),
            GoogleAdsCampaignBudgetAmountChange("77", "CUSTOM_PERIOD", 30_000_000, 45_000_000),
        ],
    )

    assert client.path == "customers/333/campaignBudgets:mutate"
    assert client.kwargs["policy"] is IntegrationRequestPolicy.MUTATION
    assert client.kwargs["json"] == {
        "operations": [
            {
                "update": {
                    "resourceName": "customers/333/campaignBudgets/55",
                    "amountMicros": "2500000",
                },
                "updateMask": "amountMicros",
            },
            {
                "update": {
                    "resourceName": "customers/333/campaignBudgets/77",
                    "totalAmountMicros": "45000000",
                },
                "updateMask": "totalAmountMicros",
            },
        ],
        "partialFailure": True,
    }
    assert ledger.result()["already_set"] == [{"budget_id": "44"}]
    assert ledger.skipped_external_ref(ledger.parents[0]) == ("customers/333/campaignBudgets/44")
    assert [item["budget_id"] for item in ledger.result()["updated"]] == ["55", "77"]


async def test_update_campaign_budget_amounts_avoids_request_when_all_amounts_match() -> None:
    client = Client({})

    ledger = await update_campaign_budget_amounts(
        client,
        customer_id="333",
        login_customer_id="111",
        changes=[GoogleAdsCampaignBudgetAmountChange("55", "DAILY", 1_000_000, 1_000_000)],
    )

    assert client.path is None
    assert ledger.result()["already_set"] == [{"budget_id": "55"}]


async def test_update_campaign_budget_amounts_keeps_failed_and_unverified_distinct() -> None:
    rejected = await update_campaign_budget_amounts(
        Client(
            {
                "results": [
                    {"resourceName": "customers/333/campaignBudgets/44"},
                    {},
                ],
                "partialFailureError": {
                    "details": [
                        {
                            "errors": [
                                {
                                    "message": "Budget is read only",
                                    "errorCode": {"campaignBudgetError": "CANNOT_MODIFY"},
                                    "location": {
                                        "fieldPathElements": [
                                            {"fieldName": "operations", "index": 1}
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
        changes=[
            GoogleAdsCampaignBudgetAmountChange("44", "DAILY", 1, 2),
            GoogleAdsCampaignBudgetAmountChange("55", "DAILY", 1, 2),
        ],
    )
    ambiguous = await update_campaign_budget_amounts(
        Client({"results": [{"resourceName": "customers/999/campaignBudgets/55"}]}),
        customer_id="333",
        login_customer_id="111",
        changes=[GoogleAdsCampaignBudgetAmountChange("55", "DAILY", 1, 2)],
    )

    assert rejected.effects[0].outcome == "applied"
    assert rejected.effects[1].outcome == "failed"
    assert rejected.effects[1].error_code == "CANNOT_MODIFY"
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


async def test_update_campaign_budget_amounts_uses_live_state_for_result_and_audit(
    monkeypatch,
) -> None:
    selected = entry()
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(selected,))),
        tool_name=UPDATE_DEFINITION.name,
    )
    reference = GoogleAdsCampaignBudgetReference(
        customer_id="333",
        budget_id="55",
        label="Stale name",
    )
    provider_client = Client({"results": [{"resourceName": "customers/333/campaignBudgets/55"}]})
    verifier = AsyncMock(
        return_value={
            "55": {
                "id": "55",
                "name": "Current name",
                "status": "ENABLED",
                "period": "DAILY",
                "deliveryMethod": "STANDARD",
                "amountMicros": "12500000",
                "explicitlyShared": True,
                "referenceCount": "2",
                "currencyCode": "GBP",
                "campaignLabels": ("Brand", "Search"),
            }
        }
    )
    audit_outcomes = []
    pending_details = []

    async def passthrough_audit(_ctx, _entry, **kwargs):
        pending_details.append(await kwargs["prepare_pending_operation"]())
        outcome = await kwargs["execute"]()
        audit_outcomes.append(outcome)
        return outcome.value

    monkeypatch.setattr(
        "integrations.google_ads.tools.update_campaign_budget_amounts.google_ads_client",
        AsyncMock(return_value=provider_client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.update_campaign_budget_amounts.verify_campaign_budgets",
        verifier,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.update_campaign_budget_amounts.run_audited_integration_operation",
        passthrough_audit,
    )

    result = await google_ads_update_campaign_budget_amounts(
        ctx,
        [GoogleAdsCampaignBudgetAmountUpdate(budget=reference, amount="15.25")],
    )

    output = GoogleAdsUpdateCampaignBudgetAmountsOutput.model_validate(result.return_value)
    data = output.results[0].data
    assert data is not None, result.return_value["results"][0].get("error_message")
    assert data.counts.model_dump() == {
        "updated": 1,
        "already_set": 0,
        "failed": 0,
        "unverified": 0,
    }
    budget = data.samples.updated[0]
    assert budget.outcome == "updated"
    assert budget.previous_amount == "12.5"
    assert budget.requested_amount == "15.25"
    assert budget.reference.label == "Current name"
    assert budget.reference.amount_micros == 15_250_000
    assert budget.reference.reference_count == 2
    assert budget.reference.campaign_labels == ("Brand", "Search")
    fields = pending_details[0].intent_groups[0].items[0].fields
    assert fields["previous_amount_micros"] == "12500000"
    assert fields["requested_amount_micros"] == "15250000"
    assert fields["campaign_label_count"] == 2
    assert fields["campaign_label_sample"] == ["Brand", "Search"]
    assert fields["campaign_labels_truncated"] is False
    assert audit_outcomes[0].operation_detail.intent_counts.applied == 1
    verifier.assert_awaited_once()


async def test_update_campaign_budget_amounts_rejects_duplicates_before_dispatch(
    monkeypatch,
) -> None:
    reference = GoogleAdsCampaignBudgetReference(
        customer_id="333",
        budget_id="55",
        label="Budget",
    )
    fan_out = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.update_campaign_budget_amounts.run_context_targets",
        fan_out,
    )

    with pytest.raises(ModelRetry, match="only once"):
        await google_ads_update_campaign_budget_amounts(
            SimpleNamespace(),
            [
                GoogleAdsCampaignBudgetAmountUpdate(budget=reference, amount="1"),
                GoogleAdsCampaignBudgetAmountUpdate(budget=reference, amount="2"),
            ],
        )

    fan_out.assert_not_awaited()


async def test_update_campaign_budget_amounts_retains_unverified_before_after_result(
    monkeypatch,
) -> None:
    selected = entry()
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(selected,)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name=UPDATE_DEFINITION.name,
        tool_call_id="update-budget-call",
    )
    reference = GoogleAdsCampaignBudgetReference(
        customer_id="333",
        budget_id="55",
        label="Budget",
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.update_campaign_budget_amounts.google_ads_client",
        AsyncMock(
            return_value=Client({"results": [{"resourceName": "customers/999/campaignBudgets/55"}]})
        ),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.update_campaign_budget_amounts.verify_campaign_budgets",
        AsyncMock(
            return_value={
                "55": {
                    "id": "55",
                    "name": "Budget",
                    "status": "ENABLED",
                    "period": "DAILY",
                    "deliveryMethod": "STANDARD",
                    "amountMicros": "1000000",
                    "explicitlyShared": False,
                    "referenceCount": "0",
                    "currencyCode": "GBP",
                    "campaignLabels": (),
                }
            }
        ),
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        AsyncMock(return_value=uuid4()),
    )

    result = await google_ads_update_campaign_budget_amounts(
        ctx,
        [GoogleAdsCampaignBudgetAmountUpdate(budget=reference, amount="2")],
    )

    output = GoogleAdsUpdateCampaignBudgetAmountsOutput.model_validate(result.return_value)
    item = output.results[0]
    assert item.status == "error"
    assert item.error_code == "unverified_mutation"
    assert item.data is not None
    budget = item.data.samples.unverified[0]
    assert budget.outcome == "unverified"
    assert budget.previous_amount_micros == 1_000_000
    assert budget.requested_amount_micros == 2_000_000
    assert budget.reference.amount_micros == 1_000_000


def test_update_campaign_budget_definition_is_approval_only_and_bounded() -> None:
    assert UPDATE_DEFINITION.default_policy == "approval"
    assert UPDATE_DEFINITION.supports_auto is False
    assert UPDATE_DEFINITION.code_eligible is True
    schema = UPDATE_DEFINITION.to_pydantic_tool().function_schema.json_schema
    updates = schema["properties"]["updates"]
    assert updates["minItems"] == 1
    assert updates["maxItems"] == 100
    update_schema = schema["$defs"]["GoogleAdsCampaignBudgetAmountUpdate"]
    amount_description = update_schema["properties"]["amount"]["description"]
    assert "positive decimal" in amount_description.lower()
    assert "account currency" in amount_description
    assert "up to six decimal places" in amount_description
    assert "not micros" in amount_description
    assert (
        UPDATE_DEFINITION.max_public_result_chars == MAX_CAMPAIGN_BUDGET_AMOUNT_PUBLIC_RESULT_CHARS
    )
    assert UPDATE_DEFINITION.presentation.arg_fields[0].editable is False


async def test_assign_campaign_budgets_uses_fixed_mask_and_skips_noop() -> None:
    client = Client({"results": [{"resourceName": "customers/333/campaigns/20"}]})

    ledger = await assign_campaign_budgets(
        client,
        customer_id="333",
        login_customer_id="111",
        assignments=[
            GoogleAdsCampaignBudgetAssignment("10", "55", "55"),
            GoogleAdsCampaignBudgetAssignment("20", "44", "55"),
        ],
    )

    assert client.path == "customers/333/campaigns:mutate"
    assert client.kwargs["policy"] is IntegrationRequestPolicy.MUTATION
    assert client.kwargs["json"] == {
        "operations": [
            {
                "update": {
                    "resourceName": "customers/333/campaigns/20",
                    "campaignBudget": "customers/333/campaignBudgets/55",
                },
                "updateMask": "campaignBudget",
            }
        ],
        "partialFailure": True,
    }
    assert ledger.result()["already_set"] == [{"campaign_id": "10"}]
    assert ledger.skipped_external_ref(ledger.parents[0]) == "customers/333/campaigns/10"
    assert ledger.result()["assigned"] == [
        {
            "campaign_id": "20",
            "resource_name": "customers/333/campaigns/20",
        }
    ]


def test_campaign_budget_assignment_results_bound_before_after_routes() -> None:
    destination = GoogleAdsCampaignBudgetReference(
        customer_id="333",
        budget_id="55",
        label="Destination budget",
    )
    campaigns = [
        {
            "campaign": campaign(str(index + 1), label=f"Campaign {index}"),
            "previous_budget": GoogleAdsCampaignBudgetReference(
                customer_id="333",
                budget_id=str(index + 100),
                label=f"Previous budget {index}",
            ),
            "requested_budget": destination,
            "outcome": "assigned",
            "external_ref": f"customers/333/campaigns/{index + 1}",
            "error_code": None,
            "message": None,
        }
        for index in range(50)
    ]

    model_result = bounded_campaign_budget_assignment_result(
        {"destination_budget": destination, "campaigns": campaigns}
    )
    display_result = display_campaign_budget_assignment_result(
        {"destination_budget": destination, "campaigns": campaigns}
    )

    assert len(json.dumps(model_result, ensure_ascii=False)) <= (
        MAX_CAMPAIGN_BUDGET_ASSIGNMENT_RESULT_CHARS
    )
    assert len(json.dumps(display_result, ensure_ascii=False)) <= (
        MAX_CAMPAIGN_BUDGET_ASSIGNMENT_DISPLAY_DATA_CHARS
    )
    assert model_result["counts"] == {
        "assigned": 50,
        "already_set": 0,
        "failed": 0,
        "unverified": 0,
    }
    assert model_result["samples_truncated"] is True
    assert display_result["samples_truncated"] is False
    assert len(display_result["samples"]["assigned"]) == 50
    first = display_result["samples"]["assigned"][0]
    assert first["previous_budget"]["budget_id"] == "100"
    assert first["requested_budget"]["budget_id"] == "55"


async def test_assign_campaign_budgets_keeps_failed_and_unverified_distinct() -> None:
    rejected = await assign_campaign_budgets(
        Client(
            {
                "results": [
                    {"resourceName": "customers/333/campaigns/10"},
                    {},
                ],
                "partialFailureError": {
                    "details": [
                        {
                            "errors": [
                                {
                                    "message": "Campaign cannot use shared budget",
                                    "errorCode": {
                                        "campaignError": "CAMPAIGN_CANNOT_USE_SHARED_BUDGET"
                                    },
                                    "location": {
                                        "fieldPathElements": [
                                            {"fieldName": "operations", "index": 1}
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
        assignments=[
            GoogleAdsCampaignBudgetAssignment("10", "44", "55"),
            GoogleAdsCampaignBudgetAssignment("20", "44", "55"),
        ],
    )
    ambiguous = await assign_campaign_budgets(
        Client({"results": [{"resourceName": "customers/999/campaigns/10"}]}),
        customer_id="333",
        login_customer_id="111",
        assignments=[GoogleAdsCampaignBudgetAssignment("10", "44", "55")],
    )

    assert rejected.effects[0].outcome == "applied"
    assert rejected.effects[1].outcome == "failed"
    assert rejected.effects[1].error_code == "CAMPAIGN_CANNOT_USE_SHARED_BUDGET"
    assert ambiguous.effects[0].outcome == "unverified"


async def test_budget_assignment_verifier_marks_base_campaign_with_active_trial() -> None:
    client = SequencedClient(
        [
            {
                "results": [
                    {
                        "campaign": {
                            "id": "10",
                            "name": "Base campaign",
                            "status": "ENABLED",
                            "campaignBudget": "customers/333/campaignBudgets/44",
                            "experimentType": "BASE",
                        }
                    }
                ]
            },
            {
                "results": [
                    {
                        "experimentArm": {
                            "campaigns": ["customers/333/campaigns/10"],
                            "control": True,
                        },
                        "experiment": {"status": "INITIATED"},
                    }
                ]
            },
        ]
    )

    rows = await verify_campaigns_for_budget_assignment(
        client,
        entry=entry(),
        campaign_ids=["10"],
    )

    assert rows["10"]["hasRunningOrScheduledTrials"] is True
    assert len(client.calls) == 2


async def test_assign_campaign_budget_tool_uses_live_before_after_state_and_audit(
    monkeypatch,
) -> None:
    selected = entry()
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(selected,))),
        tool_name=ASSIGN_DEFINITION.name,
    )
    destination = GoogleAdsCampaignBudgetReference(
        customer_id="333",
        budget_id="55",
        label="Stale destination",
    )
    selected_campaign = campaign("10", label="Stale campaign")
    provider_client = Client({"results": [{"resourceName": "customers/333/campaigns/10"}]})
    pending_details = []
    audit_outcomes = []

    async def passthrough_audit(_ctx, _entry, **kwargs):
        pending_details.append(await kwargs["prepare_pending_operation"]())
        outcome = await kwargs["execute"]()
        audit_outcomes.append(outcome)
        return outcome.value

    monkeypatch.setattr(
        "integrations.google_ads.tools.assign_campaign_budgets.google_ads_client",
        AsyncMock(return_value=provider_client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.assign_campaign_budgets.verify_campaigns_for_budget_assignment",
        AsyncMock(
            return_value={
                "10": {
                    "id": "10",
                    "name": "Live campaign",
                    "status": "ENABLED",
                    "campaignBudget": "customers/333/campaignBudgets/44",
                    "experimentType": "BASE",
                }
            }
        ),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.assign_campaign_budgets.verify_campaign_budgets",
        AsyncMock(
            return_value={
                "55": budget_row(
                    "55",
                    name="Live destination",
                    explicitly_shared=True,
                    reference_count=2,
                ),
                "44": budget_row(
                    "44",
                    name="Previous budget",
                    explicitly_shared=False,
                    reference_count=1,
                ),
            }
        ),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.assign_campaign_budgets.run_audited_integration_operation",
        passthrough_audit,
    )

    result = await google_ads_assign_campaign_budgets(
        ctx,
        destination,
        [selected_campaign],
    )

    output = GoogleAdsAssignCampaignBudgetsOutput.model_validate(result.return_value)
    data = output.results[0].data
    assert data is not None, result.return_value["results"][0].get("error_message")
    assert data.destination_budget.label == "Live destination"
    assert data.destination_budget.reference_count == 3
    assert data.counts.model_dump() == {
        "assigned": 1,
        "already_set": 0,
        "failed": 0,
        "unverified": 0,
    }
    assignment = data.samples.assigned[0]
    assert assignment.campaign.label == "Live campaign"
    assert assignment.previous_budget.label == "Previous budget"
    assert assignment.requested_budget.label == "Live destination"
    assert assignment.outcome == "assigned"
    fields = pending_details[0].intent_groups[0].items[0].fields
    assert fields["previous_budget_id"] == "44"
    assert fields["previous_budget_name"] == "Previous budget"
    assert fields["requested_budget_id"] == "55"
    assert fields["requested_budget_name"] == "Live destination"
    assert audit_outcomes[0].operation_detail.intent_counts.applied == 1


async def test_assign_campaign_budget_tool_omits_count_for_mixed_unverified_result(
    monkeypatch,
) -> None:
    selected = entry()
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(selected,)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name=ASSIGN_DEFINITION.name,
        tool_call_id="assign-budgets-call",
    )
    destination = GoogleAdsCampaignBudgetReference(
        customer_id="333",
        budget_id="55",
        label="Destination",
    )
    ledger = build_mutation_ledger(
        family="campaign_budget_assignments",
        action="assign",
        parent_fields=[{"campaign_id": "10"}, {"campaign_id": "20"}],
        skipped_indices={},
        submitted=[(0, {"campaign_id": "10"}), (1, {"campaign_id": "20"})],
        outcomes=[
            ("applied", "customers/333/campaigns/10", None, None),
            (
                "unverified",
                None,
                "UNACCOUNTED_OPERATION",
                "Google Ads did not account for this submitted operation",
            ),
        ],
        projection=GoogleAdsMutationProjection(
            applied_key="assigned",
            skipped_key="already_set",
            errors_key="campaign_errors",
        ),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.assign_campaign_budgets.google_ads_client",
        AsyncMock(return_value=Client({})),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.assign_campaign_budgets.verify_campaigns_for_budget_assignment",
        AsyncMock(
            return_value={
                campaign_id: {
                    "id": campaign_id,
                    "name": f"Campaign {campaign_id}",
                    "status": "ENABLED",
                    "campaignBudget": "customers/333/campaignBudgets/44",
                    "experimentType": "BASE",
                }
                for campaign_id in ("10", "20")
            }
        ),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.assign_campaign_budgets.verify_campaign_budgets",
        AsyncMock(
            return_value={
                "55": budget_row(
                    "55",
                    name="Destination",
                    explicitly_shared=True,
                    reference_count=2,
                ),
                "44": budget_row(
                    "44",
                    name="Previous",
                    explicitly_shared=False,
                    reference_count=2,
                ),
            }
        ),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.assign_campaign_budgets.assign_campaign_budgets",
        AsyncMock(return_value=ledger),
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        AsyncMock(return_value=uuid4()),
    )

    result = await google_ads_assign_campaign_budgets(
        ctx,
        destination,
        [campaign("10"), campaign("20")],
    )

    output = GoogleAdsAssignCampaignBudgetsOutput.model_validate(result.return_value)
    item = output.results[0]
    assert item.status == "error"
    assert item.error_code == "unverified_mutation"
    assert item.data is not None
    assert item.data.counts.model_dump() == {
        "assigned": 1,
        "already_set": 0,
        "failed": 0,
        "unverified": 1,
    }
    assert item.data.destination_budget.reference_count is None


async def test_edited_assignment_approval_reauthorizes_resolves_and_verifies_live_state(
    monkeypatch,
) -> None:
    selected = entry()
    original_destination = GoogleAdsCampaignBudgetReference(
        customer_id="333", budget_id="55", label="Original destination"
    )
    edited_destination = GoogleAdsCampaignBudgetReference(
        customer_id="333", budget_id="66", label="Edited destination"
    )
    original_campaign = campaign("10", label="Original campaign")
    edited_campaign = campaign("20", label="Edited campaign")
    canonical_destination = edited_destination.model_copy(update={"label": "Live destination"})
    canonical_campaign = edited_campaign.model_copy(update={"label": "Live campaign"})
    authorize = AsyncMock(return_value=SimpleNamespace())
    resolve = AsyncMock(
        side_effect=[
            [canonical_destination.model_dump(mode="json")],
            [canonical_campaign.model_dump(mode="json")],
        ]
    )
    monkeypatch.setattr(
        "services.agents.runtime.tools.registry.get_runtime_tool_definition",
        lambda _tool_name: ASSIGN_DEFINITION,
    )
    monkeypatch.setattr(
        "services.agents.runtime.entity_references.service.authorize_entity_field",
        authorize,
    )
    monkeypatch.setattr(
        "services.agents.runtime.entity_references.service.resolve_authorized_references",
        resolve,
    )

    approved_args = await validate_and_canonicalize_override_args(
        AsyncMock(),
        actor=SimpleNamespace(),
        workspace=SimpleNamespace(),
        membership=SimpleNamespace(),
        run=SimpleNamespace(conversation_id=uuid4()),
        tool_call=SimpleNamespace(
            tool_name=ASSIGN_DEFINITION.name,
            args={
                "destination_budget": original_destination.model_dump(mode="json"),
                "campaigns": [original_campaign.model_dump(mode="json")],
            },
        ),
        override_args={
            "destination_budget": edited_destination.model_dump(mode="json"),
            "campaigns": [edited_campaign.model_dump(mode="json")],
        },
    )
    assert approved_args is not None
    approved_destination = GoogleAdsCampaignBudgetReference.model_validate(
        approved_args["destination_budget"]
    )
    approved_campaigns = [
        GoogleAdsCampaignReference.model_validate(value) for value in approved_args["campaigns"]
    ]
    verify_campaigns = AsyncMock(
        return_value={
            "20": {
                "id": "20",
                "name": "Verified campaign",
                "status": "ENABLED",
                "campaignBudget": "customers/333/campaignBudgets/44",
                "experimentType": "BASE",
                "hasRunningOrScheduledTrials": False,
            }
        }
    )
    verify_budgets = AsyncMock(
        return_value={
            "66": budget_row(
                "66", name="Verified destination", explicitly_shared=True, reference_count=1
            ),
            "44": budget_row("44", name="Previous", explicitly_shared=False, reference_count=1),
        }
    )
    provider_client = Client({"results": [{"resourceName": "customers/333/campaigns/20"}]})

    async def passthrough_audit(_ctx, _entry, **kwargs):
        await kwargs["prepare_pending_operation"]()
        return (await kwargs["execute"]()).value

    monkeypatch.setattr(
        "integrations.google_ads.tools.assign_campaign_budgets.google_ads_client",
        AsyncMock(return_value=provider_client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.assign_campaign_budgets.verify_campaigns_for_budget_assignment",
        verify_campaigns,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.assign_campaign_budgets.verify_campaign_budgets",
        verify_budgets,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.assign_campaign_budgets.run_audited_integration_operation",
        passthrough_audit,
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(selected,))),
        tool_name=ASSIGN_DEFINITION.name,
    )

    result = await google_ads_assign_campaign_budgets(
        ctx,
        approved_destination,
        approved_campaigns,
    )

    assert result.return_value["results"][0]["status"] == "success"
    assert authorize.await_count == 2
    assert resolve.await_count == 2
    verify_campaigns.assert_awaited_once()
    assert verify_campaigns.await_args.kwargs["campaign_ids"] == ["20"]
    verify_budgets.assert_awaited_once()
    assert verify_budgets.await_args.kwargs["budget_ids"] == ("66", "44")
    assert provider_client.kwargs["json"]["operations"][0]["update"] == {
        "resourceName": "customers/333/campaigns/20",
        "campaignBudget": "customers/333/campaignBudgets/66",
    }


@pytest.mark.parametrize(
    (
        "explicitly_shared",
        "reference_count",
        "experiment_type",
        "has_active_trials",
        "previous_period",
        "destination_period",
        "message",
    ),
    [
        (False, 1, "DRAFT", False, "DAILY", "DAILY", "cannot change budgets"),
        (False, 1, "EXPERIMENT", False, "DAILY", "DAILY", "cannot change budgets"),
        (False, 1, "BASE", True, "DAILY", "DAILY", "running or scheduled trial"),
        (False, 1, "BASE", False, "CUSTOM_PERIOD", "DAILY", "same period"),
        (False, 1, "BASE", False, "DAILY", "DAILY", "more than one campaign"),
    ],
    ids=("draft", "experiment", "base-active-trial", "period-mismatch", "non-shared"),
)
async def test_assign_campaign_budget_tool_rejects_live_provider_constraints(
    monkeypatch,
    explicitly_shared,
    reference_count,
    experiment_type,
    has_active_trials,
    previous_period,
    destination_period,
    message,
) -> None:
    selected = entry()
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(selected,))),
        tool_name=ASSIGN_DEFINITION.name,
    )
    destination = GoogleAdsCampaignBudgetReference(
        customer_id="333",
        budget_id="55",
        label="Destination",
    )
    provider_client = Client({})

    async def passthrough_audit(_ctx, _entry, **kwargs):
        await kwargs["prepare_pending_operation"]()
        return await kwargs["execute"]()

    monkeypatch.setattr(
        "integrations.google_ads.tools.assign_campaign_budgets.google_ads_client",
        AsyncMock(return_value=provider_client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.assign_campaign_budgets.verify_campaigns_for_budget_assignment",
        AsyncMock(
            return_value={
                "10": {
                    "id": "10",
                    "name": "Campaign",
                    "status": "ENABLED",
                    "campaignBudget": "customers/333/campaignBudgets/44",
                    "experimentType": experiment_type,
                    "hasRunningOrScheduledTrials": has_active_trials,
                }
            }
        ),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.assign_campaign_budgets.verify_campaign_budgets",
        AsyncMock(
            return_value={
                "55": budget_row(
                    "55",
                    name="Destination",
                    explicitly_shared=explicitly_shared,
                    reference_count=reference_count,
                    period=destination_period,
                ),
                "44": budget_row(
                    "44",
                    name="Previous",
                    explicitly_shared=False,
                    reference_count=1,
                    period=previous_period,
                ),
            }
        ),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.assign_campaign_budgets.run_audited_integration_operation",
        passthrough_audit,
    )

    result = await google_ads_assign_campaign_budgets(
        ctx,
        destination,
        [campaign("10")],
    )

    assert result.return_value["results"][0]["status"] == "error"
    assert message in result.return_value["results"][0]["error_message"]
    assert provider_client.path is None


def test_assign_campaign_budget_definition_is_approval_only_editable_and_bounded() -> None:
    assert ASSIGN_DEFINITION.default_policy == "approval"
    assert ASSIGN_DEFINITION.supports_auto is False
    assert ASSIGN_DEFINITION.code_eligible is True
    assert "recommend" in ASSIGN_DEFINITION.description
    assert (
        ASSIGN_DEFINITION.max_public_result_chars
        == MAX_CAMPAIGN_BUDGET_ASSIGNMENT_PUBLIC_RESULT_CHARS
    )
    fields = {field.key: field for field in ASSIGN_DEFINITION.presentation.arg_fields}
    assert fields["destination_budget"].format == "entity"
    assert fields["destination_budget"].editable is True
    assert fields["campaigns"].format == "entity_list"
    assert fields["campaigns"].editable is True
    schema = ASSIGN_DEFINITION.to_pydantic_tool().function_schema.json_schema
    assert schema["properties"]["campaigns"]["minItems"] == 1
    assert schema["properties"]["campaigns"]["maxItems"] == 50


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


async def test_remove_campaign_budgets_keeps_failed_and_unverified_distinct() -> None:
    rejected = await remove_campaign_budgets(
        Client(
            {
                "results": [
                    {"resourceName": "customers/333/campaignBudgets/44"},
                    {},
                ],
                "partialFailureError": {
                    "details": [
                        {
                            "errors": [
                                {
                                    "message": "Budget is in use",
                                    "errorCode": {"campaignBudgetError": "CAMPAIGN_BUDGET_IN_USE"},
                                    "location": {
                                        "fieldPathElements": [
                                            {"fieldName": "operations", "index": 1}
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
        budget_ids=["44", "55"],
    )
    ambiguous = await remove_campaign_budgets(
        Client({"results": [{"resourceName": "customers/999/campaignBudgets/44"}]}),
        customer_id="333",
        login_customer_id="111",
        budget_ids=["44"],
    )

    assert rejected.effects[0].outcome == "applied"
    assert rejected.effects[1].outcome == "failed"
    assert rejected.effects[1].error_code == "CAMPAIGN_BUDGET_IN_USE"
    assert ambiguous.effects[0].outcome == "unverified"


def test_campaign_budget_removal_results_are_bounded() -> None:
    budgets = [
        {
            "reference": GoogleAdsCampaignBudgetReference(
                customer_id="333",
                budget_id=str(index + 1),
                label=f"Budget {index}: {'x' * 480}",
                status="ENABLED",
                reference_count=0,
            ),
            "previous_status": "ENABLED",
            "resulting_status": "REMOVED",
            "outcome": "removed",
            "external_ref": f"customers/333/campaignBudgets/{index + 1}",
            "error_code": None,
            "message": None,
        }
        for index in range(50)
    ]

    model_result = bounded_campaign_budget_removal_result({"budgets": budgets})
    display_result = display_campaign_budget_removal_result({"budgets": budgets})

    assert len(json.dumps(model_result, ensure_ascii=False)) <= (
        MAX_CAMPAIGN_BUDGET_REMOVAL_RESULT_CHARS
    )
    assert len(json.dumps(display_result, ensure_ascii=False)) <= (
        MAX_CAMPAIGN_BUDGET_REMOVAL_DISPLAY_DATA_CHARS
    )
    assert model_result["counts"] == {"removed": 50, "failed": 0, "unverified": 0}
    assert model_result["samples_truncated"] is True
    assert display_result["samples_truncated"] is False


async def test_remove_campaign_budget_tool_uses_live_unused_state_and_audit(monkeypatch) -> None:
    selected = entry()
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(selected,))),
        tool_name=REMOVE_DEFINITION.name,
    )
    stale_reference = GoogleAdsCampaignBudgetReference(
        customer_id="333",
        budget_id="55",
        label="Stale budget",
    )
    provider_client = Client({"results": [{"resourceName": "customers/333/campaignBudgets/55"}]})
    pending_details = []
    audit_outcomes = []

    async def passthrough_audit(_ctx, _entry, **kwargs):
        pending_details.append(await kwargs["prepare_pending_operation"]())
        outcome = await kwargs["execute"]()
        audit_outcomes.append(outcome)
        return outcome.value

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
                    name="Live unused budget",
                    explicitly_shared=True,
                    reference_count=0,
                )
            }
        ),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.remove_campaign_budgets.run_audited_integration_operation",
        passthrough_audit,
    )

    result = await google_ads_remove_campaign_budgets(ctx, [stale_reference])

    output = GoogleAdsRemoveCampaignBudgetsOutput.model_validate(result.return_value)
    data = output.results[0].data
    assert data is not None, result.return_value["results"][0].get("error_message")
    assert data.counts.model_dump() == {"removed": 1, "failed": 0, "unverified": 0}
    removed = data.samples.removed[0]
    assert removed.reference.label == "Live unused budget"
    assert removed.reference.reference_count == 0
    assert removed.previous_status == "ENABLED"
    assert removed.resulting_status == "REMOVED"
    fields = pending_details[0].intent_groups[0].items[0].fields
    assert fields["budget_name"] == "Live unused budget"
    assert fields["reference_count"] == 0
    assert audit_outcomes[0].operation_detail.intent_counts.applied == 1


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


async def test_remove_campaign_budget_tool_retains_unverified_prior_state(monkeypatch) -> None:
    selected = entry()
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(selected,)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name=REMOVE_DEFINITION.name,
        tool_call_id="remove-budget-call",
    )
    reference = GoogleAdsCampaignBudgetReference(
        customer_id="333",
        budget_id="55",
        label="Selected budget",
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.remove_campaign_budgets.google_ads_client",
        AsyncMock(
            return_value=Client({"results": [{"resourceName": "customers/999/campaignBudgets/55"}]})
        ),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.remove_campaign_budgets.verify_campaign_budgets",
        AsyncMock(
            return_value={
                "55": budget_row(
                    "55",
                    name="Live unused budget",
                    explicitly_shared=False,
                    reference_count=0,
                )
            }
        ),
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        AsyncMock(return_value=uuid4()),
    )

    result = await google_ads_remove_campaign_budgets(ctx, [reference])

    output = GoogleAdsRemoveCampaignBudgetsOutput.model_validate(result.return_value)
    item = output.results[0]
    assert item.status == "error"
    assert item.error_code == "unverified_mutation"
    assert item.data is not None
    budget = item.data.samples.unverified[0]
    assert budget.reference.label == "Live unused budget"
    assert budget.reference.reference_count == 0
    assert budget.previous_status == "ENABLED"
    assert budget.resulting_status is None


async def test_remove_campaign_budget_tool_accounts_for_ambiguous_transport_failure(
    monkeypatch,
) -> None:
    selected = entry()
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(selected,)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name=REMOVE_DEFINITION.name,
        tool_call_id="remove-budget-timeout-call",
    )
    reference = GoogleAdsCampaignBudgetReference(
        customer_id="333",
        budget_id="55",
        label="Selected budget",
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.remove_campaign_budgets.google_ads_client",
        AsyncMock(return_value=Client({})),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.remove_campaign_budgets.verify_campaign_budgets",
        AsyncMock(
            return_value={
                "55": budget_row(
                    "55",
                    name="Live unused budget",
                    explicitly_shared=False,
                    reference_count=0,
                )
            }
        ),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.remove_campaign_budgets.remove_campaign_budgets",
        AsyncMock(side_effect=TimeoutError("The mutation response timed out")),
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        AsyncMock(return_value=uuid4()),
    )

    result = await google_ads_remove_campaign_budgets(ctx, [reference])

    output = GoogleAdsRemoveCampaignBudgetsOutput.model_validate(result.return_value)
    item = output.results[0]
    assert item.status == "error"
    assert item.error_code == "unverified_mutation"
    assert item.data is not None
    budget = item.data.samples.unverified[0]
    assert budget.error_code == "TimeoutError"
    assert budget.message == "The mutation response timed out"
    assert budget.previous_status == "ENABLED"
    assert budget.resulting_status is None


async def test_remove_campaign_budget_tool_rejects_duplicates_before_dispatch(
    monkeypatch,
) -> None:
    reference = GoogleAdsCampaignBudgetReference(
        customer_id="333",
        budget_id="55",
        label="Budget",
    )
    fan_out = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.remove_campaign_budgets.run_context_targets",
        fan_out,
    )

    with pytest.raises(ModelRetry, match="only once"):
        await google_ads_remove_campaign_budgets(
            SimpleNamespace(),
            [reference, reference],
        )

    fan_out.assert_not_awaited()


async def test_edited_removal_approval_reauthorizes_and_resolves_budget_references(
    monkeypatch,
) -> None:
    original = GoogleAdsCampaignBudgetReference(
        customer_id="333",
        budget_id="55",
        label="Original budget",
    )
    edited = GoogleAdsCampaignBudgetReference(
        customer_id="333",
        budget_id="66",
        label="Edited budget",
    )
    canonical = edited.model_copy(update={"label": "Live budget"})
    authorize = AsyncMock(return_value=SimpleNamespace())
    resolve = AsyncMock(return_value=[canonical.model_dump(mode="json")])
    monkeypatch.setattr(
        "services.agents.runtime.tools.registry.get_runtime_tool_definition",
        lambda _tool_name: REMOVE_DEFINITION,
    )
    monkeypatch.setattr(
        "services.agents.runtime.entity_references.service.authorize_entity_field",
        authorize,
    )
    monkeypatch.setattr(
        "services.agents.runtime.entity_references.service.resolve_authorized_references",
        resolve,
    )

    approved_args = await validate_and_canonicalize_override_args(
        AsyncMock(),
        actor=SimpleNamespace(),
        workspace=SimpleNamespace(),
        membership=SimpleNamespace(),
        run=SimpleNamespace(conversation_id=uuid4()),
        tool_call=SimpleNamespace(
            tool_name=REMOVE_DEFINITION.name,
            args={"budgets": [original.model_dump(mode="json")]},
        ),
        override_args={"budgets": [edited.model_dump(mode="json")]},
    )

    assert approved_args == {"budgets": [canonical.model_dump(mode="json")]}
    authorize.assert_awaited_once()
    resolve.assert_awaited_once()
    assert resolve.await_args.kwargs["values"] == [edited.model_dump(mode="json")]


def test_remove_campaign_budget_definition_is_destructive_approval_only_and_bounded() -> None:
    assert REMOVE_DEFINITION.default_policy == "approval"
    assert REMOVE_DEFINITION.supports_auto is False
    assert REMOVE_DEFINITION.code_eligible is True
    assert "does not recommend" in REMOVE_DEFINITION.description
    assert "cannot be undone" in REMOVE_DEFINITION.presentation.approval_prompt
    assert (
        REMOVE_DEFINITION.max_public_result_chars == MAX_CAMPAIGN_BUDGET_REMOVAL_PUBLIC_RESULT_CHARS
    )
    fields = {field.key: field for field in REMOVE_DEFINITION.presentation.arg_fields}
    assert fields["budgets"].format == "entity_list"
    assert fields["budgets"].editable is True
    schema = REMOVE_DEFINITION.to_pydantic_tool().function_schema.json_schema
    assert schema["properties"]["budgets"]["minItems"] == 1
    assert schema["properties"]["budgets"]["maxItems"] == 50
