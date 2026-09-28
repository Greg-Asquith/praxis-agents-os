"""Google Ads campaign budget action contracts."""

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
    GoogleAdsCampaignBudgetAmountUpdate,
    GoogleAdsCreateCampaignBudgetOutput,
    GoogleAdsDailyBudgetAmount,
    GoogleAdsUpdateCampaignBudgetAmountsOutput,
)
from integrations.google_ads.tools.update_campaign_budget_amounts import (
    DEFINITION as UPDATE_DEFINITION,
    google_ads_update_campaign_budget_amounts,
)
from integrations.google_ads.tools.utils.money import money_to_micros
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


class FailingMutationClient:
    async def post(self, _path, **_kwargs):
        raise TimeoutError("The mutation response timed out")


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
        ("9223372036854.775808", "too large"),
    ],
)
def test_money_to_micros_rejects_invalid_provider_values(value: str, message: str) -> None:
    with pytest.raises(ModelRetry, match=message):
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


async def test_create_campaign_budget_tool_retains_intent_after_ambiguous_failure(
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
        tool_name=DEFINITION.name,
        tool_call_id="create-budget-timeout-call",
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.create_campaign_budget.google_ads_client",
        AsyncMock(return_value=FailingMutationClient()),
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
    assert item.error_code == "unverified_mutation"
    assert item.data is not None
    assert item.data.outcome == "unverified"
    assert item.data.amount == "12.5"
    assert item.data.amount_micros == "12500000"
    assert item.data.error_code == "TimeoutError"


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
        (False, 1, "BASE", True, "DAILY", "DAILY", "running or scheduled trial"),
        (False, 1, "BASE", False, "CUSTOM_PERIOD", "DAILY", "same period"),
    ],
    ids=("base-active-trial", "period-mismatch"),
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
