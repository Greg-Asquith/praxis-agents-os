"""Google Ads recommendation apply contracts and exact mutation evidence."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError
from pydantic_ai import ModelRetry

from core.exceptions.integration import (
    IntegrationFailureDisposition,
    IntegrationTimeoutError,
    IntegrationValidationError,
)
from integrations.google_ads.entity_resolvers.recommendation import (
    resolve_google_ads_recommendations,
)
from integrations.google_ads.operations.apply_recommendations import apply_recommendations
from integrations.google_ads.operations.list_recommendations import list_recommendations
from integrations.google_ads.references import GoogleAdsRecommendationReference
from integrations.google_ads.tools.apply_recommendations import (
    DEFINITION,
    _pending_operation_detail,
    _provider_parameters,
    _serialize_parameter,
    google_ads_apply_recommendations,
)
from integrations.google_ads.tools.schemas.recommendations import (
    GoogleAdsApplyRecommendationsOutput,
    GoogleAdsCampaignBudgetParameters,
    GoogleAdsForecastingSetTargetCpaParameters,
    GoogleAdsForecastingSetTargetRoasParameters,
    GoogleAdsKeywordParameters,
    GoogleAdsLowerTargetRoasParameters,
    GoogleAdsMoveUnusedBudgetParameters,
    GoogleAdsRaiseTargetCpaBidTooLowParameters,
    GoogleAdsRaiseTargetCpaParameters,
    GoogleAdsRecommendationApplyParameters,
    GoogleAdsSetTargetCpaParameters,
    GoogleAdsSetTargetRoasParameters,
    GoogleAdsTargetCpaOptInParameters,
    GoogleAdsTargetRoasOptInParameters,
    GoogleAdsUseBroadMatchKeywordParameters,
)
from integrations.google_ads.tools.verifiers.recommendation import verify_recommendations
from services.audit_events import AuditStatus
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry


def _entry(customer_id: str = "333", *, write_allowed: bool = True) -> ResolvedContextEntry:
    return ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="google_ads",
        resource_type="google_ads_account",
        external_id=customer_id,
        display_name="Ads account",
        connection_id=uuid4(),
        connection_label="Agency",
        connection_status="active",
        write_allowed=write_allowed,
        permissions_metadata={"login_customer_id": "111"},
    )


def _reference(
    entry: ResolvedContextEntry,
    recommendation_id: str,
    recommendation_type: str = "CAMPAIGN_BUDGET",
) -> GoogleAdsRecommendationReference:
    return GoogleAdsRecommendationReference(
        customer_id=entry.external_id,
        resource_name=(f"customers/{entry.external_id}/recommendations/{recommendation_id}"),
        recommendation_type=recommendation_type,
        label=recommendation_type.replace("_", " ").title(),
    )


class _Client:
    def __init__(self, payload):
        self.payload = payload
        self.calls: list[dict] = []

    async def post(self, path: str, **kwargs):
        self.calls.append({"path": path, **kwargs})
        return self.payload


def test_recommendation_reference_rejects_cross_account_resource_name() -> None:
    with pytest.raises(ValidationError, match="must belong to its customer"):
        GoogleAdsRecommendationReference(
            customer_id="333",
            resource_name="customers/444/recommendations/abc~1",
            recommendation_type="CAMPAIGN_BUDGET",
            label="Campaign Budget",
        )


def test_apply_definition_is_approval_only_and_uses_recommendation_entities() -> None:
    assert DEFINITION.effect == "write"
    assert DEFINITION.effect_scope == "external"
    assert DEFINITION.egress == "external_write"
    assert DEFINITION.default_policy == "approval"
    assert DEFINITION.supports_auto is False
    assert DEFINITION.code_eligible is True
    fields = {field.key: field for field in DEFINITION.presentation.arg_fields}
    assert fields["recommendations"].format == "entity_list"
    assert fields["recommendations"].entity_kind == "google_ads_recommendation"
    assert fields["recommendations"].editable is True
    assert fields["parameters"].editable is True


@pytest.mark.parametrize(
    ("parameter", "expected"),
    [
        (
            GoogleAdsCampaignBudgetParameters(
                recommendation_resource_name="customers/333/recommendations/1",
                new_budget_amount_micros=2_000_000,
            ),
            ("campaignBudget", {"newBudgetAmountMicros": "2000000"}),
        ),
        (
            GoogleAdsKeywordParameters(
                recommendation_resource_name="customers/333/recommendations/2",
                ad_group="customers/333/adGroups/9",
                match_type="PHRASE",
                cpc_bid_micros=500_000,
            ),
            (
                "keyword",
                {
                    "adGroup": "customers/333/adGroups/9",
                    "matchType": "PHRASE",
                    "cpcBidMicros": "500000",
                },
            ),
        ),
        (
            GoogleAdsTargetCpaOptInParameters(
                recommendation_resource_name="customers/333/recommendations/3",
                target_cpa_micros=4_000_000,
                new_campaign_budget_amount_micros=8_000_000,
            ),
            (
                "targetCpaOptIn",
                {
                    "targetCpaMicros": "4000000",
                    "newCampaignBudgetAmountMicros": "8000000",
                },
            ),
        ),
        (
            GoogleAdsTargetRoasOptInParameters(
                recommendation_resource_name="customers/333/recommendations/4",
                target_roas=2.5,
            ),
            ("targetRoasOptIn", {"targetRoas": 2.5}),
        ),
        (
            GoogleAdsMoveUnusedBudgetParameters(
                recommendation_resource_name="customers/333/recommendations/5",
                budget_micros_to_move=1_000_000,
            ),
            ("moveUnusedBudget", {"budgetMicrosToMove": "1000000"}),
        ),
        (
            GoogleAdsUseBroadMatchKeywordParameters(
                recommendation_resource_name="customers/333/recommendations/6",
                new_budget_amount_micros=3_000_000,
            ),
            ("useBroadMatchKeyword", {"newBudgetAmountMicros": "3000000"}),
        ),
        (
            GoogleAdsRaiseTargetCpaBidTooLowParameters(
                recommendation_resource_name="customers/333/recommendations/7",
                target_multiplier=1.2,
            ),
            ("raiseTargetCpaBidTooLow", {"targetMultiplier": 1.2}),
        ),
        (
            GoogleAdsForecastingSetTargetRoasParameters(
                recommendation_resource_name="customers/333/recommendations/8",
                target_roas=3.0,
                campaign_budget_amount_micros=9_000_000,
            ),
            (
                "forecastingSetTargetRoas",
                {"targetRoas": 3.0, "campaignBudgetAmountMicros": "9000000"},
            ),
        ),
        (
            GoogleAdsRaiseTargetCpaParameters(
                recommendation_resource_name="customers/333/recommendations/9",
                target_cpa_multiplier=1.1,
            ),
            ("raiseTargetCpa", {"targetCpaMultiplier": 1.1}),
        ),
        (
            GoogleAdsLowerTargetRoasParameters(
                recommendation_resource_name="customers/333/recommendations/10",
                target_roas_multiplier=0.9,
            ),
            ("lowerTargetRoas", {"targetRoasMultiplier": 0.9}),
        ),
        (
            GoogleAdsForecastingSetTargetCpaParameters(
                recommendation_resource_name="customers/333/recommendations/11",
                target_cpa_micros=2_000_000,
            ),
            ("forecastingSetTargetCpa", {"targetCpaMicros": "2000000"}),
        ),
        (
            GoogleAdsSetTargetCpaParameters(
                recommendation_resource_name="customers/333/recommendations/12",
                campaign_budget_amount_micros=7_000_000,
            ),
            ("setTargetCpa", {"campaignBudgetAmountMicros": "7000000"}),
        ),
        (
            GoogleAdsSetTargetRoasParameters(
                recommendation_resource_name="customers/333/recommendations/13",
                target_roas=4.0,
            ),
            ("setTargetRoas", {"targetRoas": 4.0}),
        ),
    ],
)
def test_every_supported_parameter_serializes_to_exact_v24_fields(
    parameter: GoogleAdsRecommendationApplyParameters,
    expected: tuple[str, dict],
) -> None:
    assert _serialize_parameter(parameter) == expected


def test_live_recommendation_type_controls_parameter_compatibility() -> None:
    entry = _entry()
    reference = _reference(entry, "one", "FORECASTING_CAMPAIGN_BUDGET")
    parameter = GoogleAdsCampaignBudgetParameters(
        recommendation_resource_name=reference.resource_name,
        new_budget_amount_micros=2_000_000,
    )

    provider_parameters = _provider_parameters(
        [reference],
        {reference.resource_name: parameter},
        {reference.resource_name: {"type": "FORECASTING_CAMPAIGN_BUDGET"}},
    )

    assert provider_parameters == {
        reference.resource_name: ("campaignBudget", {"newBudgetAmountMicros": "2000000"})
    }


def test_parameter_union_rejects_unknown_or_empty_variants() -> None:
    adapter = TypeAdapter(GoogleAdsRecommendationApplyParameters)
    with pytest.raises(ValidationError):
        adapter.validate_python(
            {
                "parameter_type": "textAd",
                "recommendation_resource_name": "customers/333/recommendations/1",
                "ad": {},
            }
        )


@pytest.mark.parametrize(
    ("parameter_type", "field_name"),
    [
        ("raiseTargetCpaBidTooLow", "target_multiplier"),
        ("raiseTargetCpa", "target_cpa_multiplier"),
        ("lowerTargetRoas", "target_roas_multiplier"),
    ],
)
def test_multiplier_parameters_reject_non_finite_values(
    parameter_type: str,
    field_name: str,
) -> None:
    adapter = TypeAdapter(GoogleAdsRecommendationApplyParameters)

    with pytest.raises(ValidationError, match="finite number"):
        adapter.validate_python(
            {
                "parameter_type": parameter_type,
                "recommendation_resource_name": "customers/333/recommendations/1",
                field_name: float("inf"),
            }
        )
    with pytest.raises(ValidationError, match="require a target or budget"):
        adapter.validate_python(
            {
                "parameter_type": "setTargetRoas",
                "recommendation_resource_name": "customers/333/recommendations/1",
            }
        )


def test_keyword_parameters_reject_cross_account_ad_group() -> None:
    with pytest.raises(ValidationError, match="must belong to the recommendation customer"):
        GoogleAdsKeywordParameters(
            recommendation_resource_name="customers/333/recommendations/1",
            ad_group="customers/444/adGroups/9",
            match_type="BROAD",
        )


async def test_apply_operation_reconciles_partial_failures_by_index() -> None:
    client = _Client(
        {
            "results": [
                {"resourceName": "customers/333/recommendations/one"},
                {},
            ],
            "partialFailureError": {
                "details": [
                    {
                        "errors": [
                            {
                                "message": "Recommendation expired",
                                "errorCode": {"recommendationError": "RECOMMENDATION_NOT_FOUND"},
                                "location": {
                                    "fieldPathElements": [{"fieldName": "operations", "index": 1}]
                                },
                            }
                        ]
                    }
                ]
            },
        }
    )

    ledger = await apply_recommendations(
        client,
        customer_id="333",
        login_customer_id="111",
        recommendations=[
            ("customers/333/recommendations/one", "CAMPAIGN_BUDGET", None),
            (
                "customers/333/recommendations/two",
                "SET_TARGET_ROAS",
                ("setTargetRoas", {"targetRoas": 3.0}),
            ),
        ],
    )

    assert [effect.outcome for effect in ledger.effects] == ["applied", "failed"]
    assert client.calls[0]["path"] == "customers/333/recommendations:apply"
    assert client.calls[0]["json"] == {
        "operations": [
            {"resourceName": "customers/333/recommendations/one"},
            {
                "resourceName": "customers/333/recommendations/two",
                "setTargetRoas": {"targetRoas": 3.0},
            },
        ],
        "partialFailure": True,
    }


async def test_apply_operation_preserves_indexed_failures_with_unattributed_diagnostics() -> None:
    client = _Client(
        {
            "results": [{}, {}],
            "partialFailureError": {
                "details": [
                    {
                        "errors": [
                            {
                                "message": "First recommendation was rejected",
                                "errorCode": {"recommendationError": "INVALID_VALUE"},
                                "location": {
                                    "fieldPathElements": [{"fieldName": "operations", "index": 0}]
                                },
                            },
                            {
                                "message": "Provider response was incomplete",
                                "errorCode": {"internalError": "INTERNAL_ERROR"},
                            },
                        ]
                    }
                ]
            },
        }
    )

    ledger = await apply_recommendations(
        client,
        customer_id="333",
        login_customer_id="111",
        recommendations=[
            ("customers/333/recommendations/one", "CAMPAIGN_BUDGET", None),
            ("customers/333/recommendations/two", "SET_TARGET_CPA", None),
        ],
    )

    assert [effect.outcome for effect in ledger.effects] == ["failed", "unverified"]
    assert ledger.effects[0].error_code == "INVALID_VALUE"
    assert ledger.effects[1].error_code == "INTERNAL_ERROR"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"results": "not-a-list"},
        {"results": []},
        {"results": [{"resourceName": "customers/333/recommendations/wrong"}]},
        {"results": [None]},
    ],
)
async def test_apply_operation_marks_malformed_response_shapes_unverified(payload) -> None:
    ledger = await apply_recommendations(
        _Client(payload),
        customer_id="333",
        login_customer_id="111",
        recommendations=[
            ("customers/333/recommendations/one", "CAMPAIGN_BUDGET", None),
        ],
    )

    assert [effect.outcome for effect in ledger.effects] == ["unverified"]


async def test_list_recommendations_uses_exact_account_scoped_gaql() -> None:
    resource_name = "customers/333/recommendations/one~1"
    client = _Client(
        [
            {
                "results": [
                    {
                        "campaign": {"name": "Brand search"},
                        "recommendation": {"resourceName": resource_name},
                    }
                ]
            }
        ]
    )

    rows = await list_recommendations(
        client,
        customer_id="333",
        login_customer_id="111",
        resource_names=[resource_name],
        include_dismissed=True,
        limit=1,
    )

    assert rows == [{"resourceName": resource_name, "affectedCampaignLabel": "Brand search"}]
    query = client.calls[0]["json"]["query"]
    assert "recommendation.resource_name IN ('customers/333/recommendations/one~1')" in query
    assert "recommendation.dismissed = FALSE" not in query
    assert "recommendation.impact" in query
    assert "campaign.name" in query
    assert " OFFSET " not in query
    assert " ORDER BY " not in query
    assert client.calls[0]["operation"] == "list_recommendations"


async def test_recommendation_resolver_hydrates_only_active_account_values(
    monkeypatch,
) -> None:
    active = _entry("333")
    inactive = _entry("444")
    ctx = SimpleNamespace(
        db=object(),
        actor=object(),
        workspace=object(),
        active_context=ResolvedActiveContext(entries=(active,)),
    )
    reference = _reference(active, "one")
    query = AsyncMock(
        return_value=[
            {
                "resourceName": reference.resource_name,
                "type": reference.recommendation_type,
                "dismissed": False,
                "campaign": "customers/333/campaigns/9",
            }
        ]
    )
    monkeypatch.setattr(
        "integrations.google_ads.entity_resolvers.recommendation._query",
        query,
    )

    choices = await resolve_google_ads_recommendations(
        ctx,
        [reference, _reference(inactive, "other")],
        {},
    )

    assert len(choices) == 1
    assert choices[0].value["resource_name"] == reference.resource_name
    assert choices[0].scope_label == active.display_name
    query.assert_awaited_once()
    assert query.await_args.kwargs["resource_names"] == (reference.resource_name,)


async def test_apply_operation_marks_unaccounted_results_unverified() -> None:
    client = _Client({"results": []})

    ledger = await apply_recommendations(
        client,
        customer_id="333",
        login_customer_id="111",
        recommendations=[
            ("customers/333/recommendations/one", "CAMPAIGN_BUDGET", None),
        ],
    )

    [effect] = ledger.effects
    assert effect.outcome == "unverified"
    assert effect.error_code == "UNACCOUNTED_OPERATION"


async def test_verifier_rejects_missing_dismissed_and_changed_recommendations() -> None:
    entry = _entry()
    reference = _reference(entry, "one")

    for payload, message in (
        ([{"results": []}], "no longer available"),
        (
            [
                {
                    "results": [
                        {
                            "recommendation": {
                                "resourceName": reference.resource_name,
                                "type": reference.recommendation_type,
                                "dismissed": True,
                            }
                        }
                    ]
                }
            ],
            "has been dismissed",
        ),
        (
            [
                {
                    "results": [
                        {
                            "recommendation": {
                                "resourceName": reference.resource_name,
                                "type": "SET_TARGET_CPA",
                                "dismissed": False,
                            }
                        }
                    ]
                }
            ],
            "has changed",
        ),
    ):
        with pytest.raises(ModelRetry, match=message):
            await verify_recommendations(
                _Client(payload),
                entry=entry,
                references=[reference],
            )


async def test_apply_tool_returns_exact_partial_outcomes(monkeypatch) -> None:
    entry = _entry()
    first = _reference(entry, "one")
    second = _reference(entry, "two", "SET_TARGET_ROAS")
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(entry,))),
        tool_name=DEFINITION.name,
    )
    provider_client = _Client(
        {
            "results": [
                {"resourceName": first.resource_name},
                {},
            ],
            "partialFailureError": {
                "details": [
                    {
                        "errors": [
                            {
                                "message": "Target rejected",
                                "errorCode": {"recommendationError": "INVALID_VALUE"},
                                "location": {
                                    "fieldPathElements": [{"fieldName": "operations", "index": 1}]
                                },
                            }
                        ]
                    }
                ]
            },
        }
    )
    live = {
        first.resource_name: {
            "resourceName": first.resource_name,
            "type": first.recommendation_type,
            "dismissed": False,
            "campaign": "customers/333/campaigns/8",
            "impact": {
                "baseMetrics": {"clicks": 10.0, "costMicros": "1000000"},
                "potentialMetrics": {"clicks": 14.0, "costMicros": "1200000"},
            },
        },
        second.resource_name: {
            "resourceName": second.resource_name,
            "type": second.recommendation_type,
            "dismissed": False,
            "campaigns": ["customers/333/campaigns/9"],
        },
    }
    audit_outcomes = []

    async def passthrough_audit(_ctx, _entry, **kwargs):
        await kwargs["prepare_pending_operation"]()
        outcome = await kwargs["execute"]()
        audit_outcomes.append(outcome)
        return outcome.value

    monkeypatch.setattr(
        "integrations.google_ads.tools.apply_recommendations.google_ads_client",
        AsyncMock(return_value=provider_client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.apply_recommendations.verify_recommendations",
        AsyncMock(return_value=live),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.apply_recommendations.run_audited_integration_operation",
        passthrough_audit,
    )
    parameter = GoogleAdsSetTargetRoasParameters(
        recommendation_resource_name=second.resource_name,
        target_roas=3.0,
    )

    result = await google_ads_apply_recommendations(ctx, [first, second], [parameter])

    GoogleAdsApplyRecommendationsOutput.model_validate(result)
    rows = result["results"][0]["data"]["recommendations"]
    assert [row["outcome"] for row in rows] == ["applied", "failed"]
    assert rows[0]["affected_campaigns"] == ["customers/333/campaigns/8"]
    assert rows[0]["impact"]["potential_metrics"]["clicks"] == 14.0
    assert rows[1]["requested_parameters"]["parameter_type"] == "setTargetRoas"
    detail = audit_outcomes[0].operation_detail
    assert detail.intent_counts.model_dump() == {
        "applied": 1,
        "skipped": 0,
        "failed": 1,
        "unverified": 0,
    }
    assert detail.intent_groups[0].items[1].fields["parameters"] == {
        "parameter_type": "setTargetRoas",
        "target_roas": 3.0,
    }


async def test_apply_tool_retains_exact_rows_for_unverified_outer_error(monkeypatch) -> None:
    entry = _entry()
    reference = _reference(entry, "one")
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(entry,)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name=DEFINITION.name,
        tool_call_id="call-unverified",
    )
    live = {
        reference.resource_name: {
            "resourceName": reference.resource_name,
            "type": reference.recommendation_type,
            "dismissed": False,
        }
    }
    audit = AsyncMock(return_value=uuid4())

    monkeypatch.setattr(
        "integrations.google_ads.tools.apply_recommendations.google_ads_client",
        AsyncMock(return_value=_Client({"results": []})),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.apply_recommendations.verify_recommendations",
        AsyncMock(return_value=live),
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )

    result = await google_ads_apply_recommendations(ctx, [reference])

    account_result = result["results"][0]
    row = account_result["data"]["recommendations"][0]
    assert account_result["status"] == "error"
    assert account_result["error_code"] == "unverified_mutation"
    assert row["outcome"] == "unverified"
    assert [call.kwargs["status"] for call in audit.await_args_list] == [
        "pending",
        "unverified",
    ]


@pytest.mark.parametrize(
    ("provider_error", "expected_account_status", "expected_outcome", "expected_audit_status"),
    [
        (
            IntegrationValidationError(
                "Google Ads rejected the request",
                failure_disposition=IntegrationFailureDisposition.REJECTED,
            ),
            "success",
            "failed",
            AuditStatus.FAILURE,
        ),
        (
            IntegrationTimeoutError(
                "Google Ads did not confirm the request",
                failure_disposition=IntegrationFailureDisposition.AMBIGUOUS,
            ),
            "error",
            "unverified",
            AuditStatus.UNVERIFIED,
        ),
    ],
)
async def test_apply_tool_accounts_for_every_intent_on_provider_exception(
    monkeypatch,
    provider_error,
    expected_account_status: str,
    expected_outcome: str,
    expected_audit_status: AuditStatus,
) -> None:
    entry = _entry()
    references = [_reference(entry, "one"), _reference(entry, "two")]
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(entry,)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name=DEFINITION.name,
        tool_call_id="call-provider-error",
    )
    live = {
        reference.resource_name: {
            "resourceName": reference.resource_name,
            "type": reference.recommendation_type,
            "dismissed": False,
        }
        for reference in references
    }
    provider_client = SimpleNamespace(post=AsyncMock(side_effect=provider_error))
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "integrations.google_ads.tools.apply_recommendations.google_ads_client",
        AsyncMock(return_value=provider_client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.apply_recommendations.verify_recommendations",
        AsyncMock(return_value=live),
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )

    result = await google_ads_apply_recommendations(ctx, references)

    account_result = result["results"][0]
    assert account_result["status"] == expected_account_status
    assert [row["outcome"] for row in account_result["data"]["recommendations"]] == [
        expected_outcome,
        expected_outcome,
    ]
    terminal = audit.await_args_list[1].kwargs
    assert terminal["status"] is expected_audit_status
    assert terminal["operation_detail"].intent_counts.model_dump() == {
        "applied": 0,
        "skipped": 0,
        "failed": 2 if expected_outcome == "failed" else 0,
        "unverified": 2 if expected_outcome == "unverified" else 0,
    }


async def test_live_verification_failure_is_audited_before_pending_or_mutation(monkeypatch) -> None:
    entry = _entry()
    reference = _reference(entry, "one")
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(entry,)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name=DEFINITION.name,
        tool_call_id="call-stale-recommendation",
    )
    provider_client = object()
    mutation = AsyncMock()
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "integrations.google_ads.tools.apply_recommendations.google_ads_client",
        AsyncMock(return_value=provider_client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.apply_recommendations.verify_recommendations",
        AsyncMock(side_effect=ModelRetry("Recommendation is stale")),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.apply_recommendations.apply_recommendations",
        mutation,
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )

    result = await google_ads_apply_recommendations(ctx, [reference])

    assert result["results"][0]["status"] == "error"
    mutation.assert_not_awaited()
    audit.assert_awaited_once()
    terminal = audit.await_args.kwargs
    assert terminal["status"] is AuditStatus.FAILURE
    assert terminal["operation_detail"] is None
    assert terminal["related_event_id"] is None


async def test_apply_tool_rejects_duplicate_and_unselected_parameter_rows(monkeypatch) -> None:
    entry = _entry()
    reference = _reference(entry, "one")
    targeting = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.apply_recommendations.run_context_targets",
        targeting,
    )
    parameter = GoogleAdsCampaignBudgetParameters(
        recommendation_resource_name=reference.resource_name,
        new_budget_amount_micros=2_000_000,
    )
    other = parameter.model_copy(
        update={"recommendation_resource_name": "customers/333/recommendations/other"}
    )

    with pytest.raises(ModelRetry, match="only once"):
        await google_ads_apply_recommendations(None, [reference, reference])  # type: ignore[arg-type]
    with pytest.raises(ModelRetry, match="at most one parameter row"):
        await google_ads_apply_recommendations(
            None,  # type: ignore[arg-type]
            [reference],
            [parameter, parameter],
        )
    with pytest.raises(ModelRetry, match="must name one of the selected"):
        await google_ads_apply_recommendations(None, [reference], [other])  # type: ignore[arg-type]

    targeting.assert_not_awaited()


async def test_apply_tool_rejects_parameter_type_mismatch_before_mutation(monkeypatch) -> None:
    entry = _entry()
    reference = _reference(entry, "one", "CAMPAIGN_BUDGET")
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(entry,))),
        tool_name=DEFINITION.name,
    )
    mutation = AsyncMock()

    async def passthrough_audit(_ctx, _entry, **kwargs):
        await kwargs["prepare_pending_operation"]()
        return (await kwargs["execute"]()).value

    monkeypatch.setattr(
        "integrations.google_ads.tools.apply_recommendations.google_ads_client",
        AsyncMock(return_value=object()),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.apply_recommendations.verify_recommendations",
        AsyncMock(
            return_value={
                reference.resource_name: {
                    "resourceName": reference.resource_name,
                    "type": reference.recommendation_type,
                }
            }
        ),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.apply_recommendations.apply_recommendations",
        mutation,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.apply_recommendations.run_audited_integration_operation",
        passthrough_audit,
    )
    parameter = GoogleAdsSetTargetRoasParameters(
        recommendation_resource_name=reference.resource_name,
        target_roas=3.0,
    )

    result = await google_ads_apply_recommendations(ctx, [reference], [parameter])

    assert result["results"][0]["status"] == "error"
    assert "do not match" in result["results"][0]["error_message"]
    mutation.assert_not_awaited()


async def test_apply_write_denial_stops_provider_calls_and_records_failure(monkeypatch) -> None:
    entry = _entry(write_allowed=False)
    reference = _reference(entry, "one")
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(entry,)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name=DEFINITION.name,
        tool_call_id="call-denied",
    )
    provider_client = AsyncMock()
    audit = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.apply_recommendations.google_ads_client",
        provider_client,
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )

    result = await google_ads_apply_recommendations(ctx, [reference])

    assert result["results"][0]["error_code"] == "write_not_permitted"
    provider_client.assert_not_awaited()
    audit.assert_awaited_once()
    assert audit.await_args.kwargs["status"].value == "failure"
    assert audit.await_args.kwargs["error_code"] == "write_not_permitted"


def test_pending_evidence_keeps_intent_and_parameters_without_provider_payload() -> None:
    entry = _entry()
    reference = _reference(entry, "one", "SET_TARGET_CPA")
    parameter = GoogleAdsSetTargetCpaParameters(
        recommendation_resource_name=reference.resource_name,
        target_cpa_micros=2_000_000,
    )

    detail = _pending_operation_detail(
        entry,
        [reference],
        {reference.resource_name: parameter},
        live_rows={
            reference.resource_name: {
                "resourceName": reference.resource_name,
                "type": reference.recommendation_type,
                "campaign": "customers/333/campaigns/9",
                "affectedCampaignLabel": "Brand search",
            }
        },
    )

    assert detail.intent_groups[0].items[0].fields == {
        "recommendation_resource_name": reference.resource_name,
        "recommendation_type": "SET_TARGET_CPA",
        "recommendation_label": "Set Target Cpa",
        "campaign_label": "Brand search",
        "parameters": {
            "parameter_type": "setTargetCpa",
            "target_cpa_micros": 2_000_000,
        },
    }
