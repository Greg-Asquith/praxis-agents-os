"""Google Ads recommendation apply contracts and exact mutation evidence."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
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
    _provider_parameters,
    _serialize_parameter,
    google_ads_apply_recommendations,
)
from integrations.google_ads.tools.schemas.recommendations import (
    GoogleAdsCampaignBudgetParameters,
    GoogleAdsKeywordParameters,
    GoogleAdsRecommendationApplyParameters,
    GoogleAdsTargetCpaOptInParameters,
    GoogleAdsTargetRoasOptInParameters,
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


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"results": "not-a-list"},
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
