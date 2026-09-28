"""Google Ads recommendation dismissal contracts and exact mutation evidence."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry

from integrations.google_ads.operations.dismiss_recommendations import (
    dismiss_recommendations,
)
from integrations.google_ads.references import GoogleAdsRecommendationReference
from integrations.google_ads.tools.dismiss_recommendations import (
    DEFINITION,
    google_ads_dismiss_recommendations,
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
