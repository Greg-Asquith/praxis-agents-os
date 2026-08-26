"""Google Ads recommendation dismissal contracts and exact mutation evidence."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry

from core.exceptions.integration import (
    IntegrationFailureDisposition,
    IntegrationTimeoutError,
    IntegrationValidationError,
)
from integrations.google_ads.operations.dismiss_recommendations import (
    dismiss_recommendations,
)
from integrations.google_ads.references import GoogleAdsRecommendationReference
from integrations.google_ads.tools.dismiss_recommendations import (
    DEFINITION,
    _pending_operation_detail,
    google_ads_dismiss_recommendations,
)
from integrations.google_ads.tools.schemas import GoogleAdsDismissRecommendationsOutput
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
        resource_name=f"customers/{entry.external_id}/recommendations/{recommendation_id}",
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


def test_dismiss_definition_is_approval_only_and_uses_recommendation_entities() -> None:
    assert DEFINITION.effect == "write"
    assert DEFINITION.effect_scope == "external"
    assert DEFINITION.egress == "external_write"
    assert DEFINITION.default_policy == "approval"
    assert DEFINITION.supports_auto is False
    assert DEFINITION.code_eligible is True
    [field] = DEFINITION.presentation.arg_fields
    assert field.key == "recommendations"
    assert field.format == "entity_list"
    assert field.entity_kind == "google_ads_recommendation"
    assert field.editable is True
    assert "without applying" in DEFINITION.presentation.approval_prompt


async def test_dismiss_operation_skips_dismissed_and_reconciles_partial_failures() -> None:
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

    ledger = await dismiss_recommendations(
        client,
        customer_id="333",
        login_customer_id="111",
        recommendations=[
            ("customers/333/recommendations/already", "KEYWORD", True),
            ("customers/333/recommendations/one", "CAMPAIGN_BUDGET", False),
            ("customers/333/recommendations/two", "SET_TARGET_ROAS", False),
        ],
    )

    assert [parent.decision for parent in ledger.parents] == ["skipped", "submit", "submit"]
    assert [effect.outcome for effect in ledger.effects] == ["applied", "failed"]
    assert ledger.intent_counts == {"requested": 3, "submitted": 2, "skipped": 1}
    assert client.calls[0]["path"] == "customers/333/recommendations:dismiss"
    assert client.calls[0]["json"] == {
        "operations": [
            {"resourceName": "customers/333/recommendations/one"},
            {"resourceName": "customers/333/recommendations/two"},
        ],
        "partialFailure": True,
    }


async def test_dismiss_operation_does_not_write_when_every_row_is_already_dismissed() -> None:
    client = _Client({})

    ledger = await dismiss_recommendations(
        client,
        customer_id="333",
        login_customer_id="111",
        recommendations=[
            ("customers/333/recommendations/one", "CAMPAIGN_BUDGET", True),
            ("customers/333/recommendations/two", "KEYWORD", True),
        ],
    )

    assert ledger.intent_counts == {"requested": 2, "submitted": 0, "skipped": 2}
    assert ledger.effect_counts == {"applied": 0, "failed": 0, "unverified": 0}
    assert client.calls == []


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
async def test_dismiss_operation_marks_malformed_response_shapes_unverified(payload) -> None:
    ledger = await dismiss_recommendations(
        _Client(payload),
        customer_id="333",
        login_customer_id="111",
        recommendations=[
            ("customers/333/recommendations/one", "CAMPAIGN_BUDGET", False),
        ],
    )

    assert [effect.outcome for effect in ledger.effects] == ["unverified"]


async def test_dismiss_verifier_accepts_dismissed_but_rejects_changed_type() -> None:
    entry = _entry()
    reference = _reference(entry, "one")
    dismissed = _Client(
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
        ]
    )

    rows = await verify_recommendations(
        dismissed,
        entry=entry,
        references=[reference],
        allow_dismissed=True,
    )

    assert rows[reference.resource_name]["dismissed"] is True
    changed = _Client(
        [
            {
                "results": [
                    {
                        "recommendation": {
                            "resourceName": reference.resource_name,
                            "type": "SET_TARGET_CPA",
                            "dismissed": True,
                        }
                    }
                ]
            }
        ]
    )
    with pytest.raises(ModelRetry, match="has changed"):
        await verify_recommendations(
            changed,
            entry=entry,
            references=[reference],
            allow_dismissed=True,
        )


async def test_dismiss_tool_returns_every_requested_outcome_and_audit_row(monkeypatch) -> None:
    entry = _entry()
    already = _reference(entry, "already", "KEYWORD")
    dismissed = _reference(entry, "one")
    failed = _reference(entry, "two", "SET_TARGET_ROAS")
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(entry,))),
        tool_name=DEFINITION.name,
    )
    provider_client = _Client(
        {
            "results": [{"resourceName": dismissed.resource_name}, {}],
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
    live = {
        already.resource_name: {
            "resourceName": already.resource_name,
            "type": already.recommendation_type,
            "dismissed": True,
        },
        dismissed.resource_name: {
            "resourceName": dismissed.resource_name,
            "type": dismissed.recommendation_type,
            "dismissed": False,
            "campaign": "customers/333/campaigns/8",
            "affectedCampaignLabel": "Brand search",
        },
        failed.resource_name: {
            "resourceName": failed.resource_name,
            "type": failed.recommendation_type,
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
        "integrations.google_ads.tools.dismiss_recommendations.google_ads_client",
        AsyncMock(return_value=provider_client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.dismiss_recommendations.verify_recommendations",
        AsyncMock(return_value=live),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.dismiss_recommendations.run_audited_integration_operation",
        passthrough_audit,
    )

    result = await google_ads_dismiss_recommendations(ctx, [already, dismissed, failed])

    GoogleAdsDismissRecommendationsOutput.model_validate(result)
    rows = result["results"][0]["data"]["recommendations"]
    assert [row["outcome"] for row in rows] == [
        "already_dismissed",
        "dismissed",
        "failed",
    ]
    assert rows[0]["external_ref"] == already.resource_name
    assert rows[1]["affected_campaigns"] == ["customers/333/campaigns/8"]
    detail = audit_outcomes[0].operation_detail
    assert detail.intent_counts.model_dump() == {
        "applied": 1,
        "skipped": 1,
        "failed": 1,
        "unverified": 0,
    }
    assert detail.intent_groups[0].items[1].fields == {
        "recommendation_resource_name": dismissed.resource_name,
        "recommendation_type": dismissed.recommendation_type,
        "recommendation_label": dismissed.label,
        "campaign_label": "Brand search",
    }


async def test_dismiss_tool_retains_exact_row_for_unverified_outer_error(monkeypatch) -> None:
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
        "integrations.google_ads.tools.dismiss_recommendations.google_ads_client",
        AsyncMock(return_value=_Client({"results": []})),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.dismiss_recommendations.verify_recommendations",
        AsyncMock(return_value=live),
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )

    result = await google_ads_dismiss_recommendations(ctx, [reference])

    account_result = result["results"][0]
    row = account_result["data"]["recommendations"][0]
    assert account_result["status"] == "error"
    assert account_result["error_code"] == "unverified_mutation"
    assert row["outcome"] == "unverified"
    assert [call.kwargs["status"] for call in audit.await_args_list] == [
        "pending",
        "unverified",
    ]


async def test_dismiss_live_verification_failure_stops_before_mutation(monkeypatch) -> None:
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
    mutation = AsyncMock()
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "integrations.google_ads.tools.dismiss_recommendations.google_ads_client",
        AsyncMock(return_value=object()),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.dismiss_recommendations.verify_recommendations",
        AsyncMock(side_effect=ModelRetry("Recommendation is stale")),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.dismiss_recommendations.dismiss_recommendations",
        mutation,
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )

    result = await google_ads_dismiss_recommendations(ctx, [reference])

    assert result["results"][0]["status"] == "error"
    mutation.assert_not_awaited()
    audit.assert_awaited_once()
    assert audit.await_args.kwargs["status"] is AuditStatus.FAILURE
    assert audit.await_args.kwargs["operation_detail"] is None


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
            AuditStatus.PARTIAL,
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
async def test_dismiss_tool_accounts_for_every_submitted_intent_on_provider_exception(
    monkeypatch,
    provider_error,
    expected_account_status: str,
    expected_outcome: str,
    expected_audit_status: AuditStatus,
) -> None:
    entry = _entry()
    already = _reference(entry, "already")
    active = _reference(entry, "active")
    references = [already, active]
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
        already.resource_name: {
            "resourceName": already.resource_name,
            "type": already.recommendation_type,
            "dismissed": True,
        },
        active.resource_name: {
            "resourceName": active.resource_name,
            "type": active.recommendation_type,
            "dismissed": False,
        },
    }
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "integrations.google_ads.tools.dismiss_recommendations.google_ads_client",
        AsyncMock(return_value=SimpleNamespace(post=AsyncMock(side_effect=provider_error))),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.dismiss_recommendations.verify_recommendations",
        AsyncMock(return_value=live),
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )

    result = await google_ads_dismiss_recommendations(ctx, references)

    account_result = result["results"][0]
    assert account_result["status"] == expected_account_status
    assert [row["outcome"] for row in account_result["data"]["recommendations"]] == [
        "already_dismissed",
        expected_outcome,
    ]
    terminal = audit.await_args_list[1].kwargs
    assert terminal["status"] is expected_audit_status
    assert terminal["operation_detail"].intent_counts.model_dump() == {
        "applied": 0,
        "skipped": 1,
        "failed": 1 if expected_outcome == "failed" else 0,
        "unverified": 1 if expected_outcome == "unverified" else 0,
    }


async def test_dismiss_tool_rejects_duplicate_rows_before_targeting(monkeypatch) -> None:
    entry = _entry()
    reference = _reference(entry, "one")
    targeting = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.dismiss_recommendations.run_context_targets",
        targeting,
    )

    with pytest.raises(ModelRetry, match="only once"):
        await google_ads_dismiss_recommendations(
            None,  # type: ignore[arg-type]
            [reference, reference],
        )

    targeting.assert_not_awaited()


async def test_dismiss_write_denial_stops_provider_calls_and_records_failure(monkeypatch) -> None:
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
        "integrations.google_ads.tools.dismiss_recommendations.google_ads_client",
        provider_client,
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )

    result = await google_ads_dismiss_recommendations(ctx, [reference])

    assert result["results"][0]["error_code"] == "write_not_permitted"
    provider_client.assert_not_awaited()
    audit.assert_awaited_once()
    assert audit.await_args.kwargs["status"] is AuditStatus.FAILURE


def test_dismiss_pending_evidence_keeps_bounded_intent_without_provider_payload() -> None:
    entry = _entry()
    reference = _reference(entry, "one", "SET_TARGET_CPA")

    detail = _pending_operation_detail(
        entry,
        [reference],
        live_rows={
            reference.resource_name: {
                "resourceName": reference.resource_name,
                "type": reference.recommendation_type,
                "campaign": "customers/333/campaigns/9",
                "affectedCampaignLabel": "Brand search",
                "impact": {"baseMetrics": {"clicks": 10.0}},
                "opaqueProviderPayload": {"must": "not persist"},
            }
        },
    )

    assert detail.intent_groups[0].items[0].fields == {
        "recommendation_resource_name": reference.resource_name,
        "recommendation_type": "SET_TARGET_CPA",
        "recommendation_label": "Set Target Cpa",
        "campaign_label": "Brand search",
    }
