"""Google Ads positive-keyword update contracts."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry

from core.exceptions.integration import IntegrationFailureDisposition
from integrations.google_ads.operations.update_positive_keywords import (
    GoogleAdsPositiveKeywordUpdate,
    update_positive_keywords,
)
from integrations.google_ads.references import GoogleAdsKeywordReference
from integrations.google_ads.tools.schemas import (
    GoogleAdsPositiveKeywordPatch,
    GoogleAdsUpdatePositiveKeywordsOutput,
)
from integrations.google_ads.tools.update_positive_keywords import (
    DEFINITION,
    _changes,
    _validate_bid_compatibility,
    _validate_updates,
    google_ads_update_keywords,
)
from integrations.google_ads.tools.verifiers import verify_positive_keywords
from services.audit_events import AuditStatus
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry
from services.integrations.http import IntegrationRequestPolicy


class SequencedClient:
    def __init__(self, payloads):
        self.payloads = iter(payloads)
        self.calls = []

    async def post(self, path, **kwargs):
        self.calls.append((path, kwargs))
        payload = next(self.payloads)
        if isinstance(payload, BaseException):
            raise payload
        return payload


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


def keyword(criterion_id: str = "90", *, status: str = "PAUSED") -> GoogleAdsKeywordReference:
    return GoogleAdsKeywordReference(
        customer_id="333",
        campaign_id="10",
        ad_group_id="20",
        criterion_id=criterion_id,
        text="running shoes",
        match_type="EXACT",
        status=status,
        cpc_bid_micros=1_250_000,
        final_urls=["https://example.com/old"],
        label="running shoes",
        scope_label="Search · Shoes",
    )


def provider_row(criterion_id: str = "90", *, status: str = "PAUSED") -> dict:
    return {
        "campaign": {"id": "10", "name": "Search"},
        "adGroup": {"id": "20", "name": "Shoes", "status": "ENABLED"},
        "adGroupCriterion": {
            "resourceName": f"customers/333/adGroupCriteria/20~{criterion_id}",
            "criterionId": criterion_id,
            "status": status,
            "cpcBidMicros": "1250000",
            "finalUrls": ["https://example.com/old"],
            "keyword": {"text": "running shoes", "matchType": "EXACT"},
        },
    }


async def test_live_verification_rejects_missing_or_changed_keywords() -> None:
    with pytest.raises(ModelRetry, match="no longer available"):
        await verify_positive_keywords(
            SequencedClient([[{"results": []}]]), entry=entry(), selected=[keyword()]
        )
    changed = provider_row()
    changed["adGroupCriterion"]["keyword"]["text"] = "changed text"
    with pytest.raises(ModelRetry, match="changed during verification"):
        await verify_positive_keywords(
            SequencedClient([[{"results": [changed]}]]), entry=entry(), selected=[keyword()]
        )


def test_patch_preserves_omission_and_supports_explicit_clears() -> None:
    patch = GoogleAdsPositiveKeywordPatch(cpc_bid="", final_urls=[])

    assert patch.model_fields_set == {"cpc_bid", "final_urls"}
    change = _changes(
        [keyword()],
        {("333", "20", "90"): patch},
    )[0]
    assert change.requested_fields == ("cpc_bid_micros", "final_urls")
    assert change.requested == {"cpc_bid_micros": None, "final_urls": []}
    assert "status" not in change.requested


async def test_operation_sends_only_explicit_fields_and_skips_full_no_op() -> None:
    previous = {
        "status": "PAUSED",
        "bid_modifier": None,
        "cpc_bid_micros": 1_250_000,
        "final_urls": ["https://example.com/old"],
        "final_mobile_urls": [],
        "final_url_suffix": None,
        "tracking_url_template": None,
        "url_custom_parameters": [],
    }
    client = SequencedClient(
        [
            {
                "results": [{"resourceName": "customers/333/adGroupCriteria/20~90"}],
            }
        ]
    )
    ledger = await update_positive_keywords(
        client,
        customer_id="333",
        login_customer_id="111",
        changes=[
            GoogleAdsPositiveKeywordUpdate(
                "20",
                "90",
                previous,
                {"status": "ENABLED", "cpc_bid_micros": None, "final_urls": []},
                ("status", "cpc_bid_micros", "final_urls"),
            ),
            GoogleAdsPositiveKeywordUpdate("20", "91", previous, {"status": "PAUSED"}, ("status",)),
        ],
    )

    assert ledger.intent_counts == {"requested": 2, "submitted": 1, "skipped": 1}
    path, kwargs = client.calls[0]
    assert path == "customers/333/adGroupCriteria:mutate"
    assert kwargs["policy"] is IntegrationRequestPolicy.MUTATION
    assert kwargs["json"] == {
        "operations": [
            {
                "update": {
                    "resourceName": "customers/333/adGroupCriteria/20~90",
                    "status": "ENABLED",
                    "cpcBidMicros": None,
                    "finalUrls": [],
                },
                "updateMask": "status,cpcBidMicros,finalUrls",
            }
        ],
        "partialFailure": True,
    }


async def test_operation_retains_partial_failure_and_contradictory_evidence() -> None:
    previous = _changes(
        [keyword()],
        {("333", "20", "90"): GoogleAdsPositiveKeywordPatch(status="ENABLED")},
    )[0]
    failed = SequencedClient(
        [
            {
                "results": [{}],
                "partialFailureError": {
                    "details": [
                        {
                            "errors": [
                                {
                                    "message": "Cannot modify criterion",
                                    "errorCode": {"adGroupCriterionError": "CANNOT_MODIFY"},
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
        ]
    )
    ledger = await update_positive_keywords(
        failed, customer_id="333", login_customer_id="111", changes=[previous]
    )
    assert ledger.effects[0].outcome == "failed"
    assert ledger.effects[0].error_code == "CANNOT_MODIFY"

    contradictory = await update_positive_keywords(
        SequencedClient([{"results": [{"resourceName": "customers/999/adGroupCriteria/20~90"}]}]),
        customer_id="333",
        login_customer_id="111",
        changes=[previous],
    )
    assert contradictory.effects[0].outcome == "unverified"


def test_requests_distinguish_matching_criterion_ids_across_accounts() -> None:
    second = keyword().model_copy(
        update={"customer_id": "444", "ad_group_id": "30", "campaign_id": "11"}
    )
    first_patch = GoogleAdsPositiveKeywordPatch(status="ENABLED")
    second_patch = GoogleAdsPositiveKeywordPatch(final_urls=[])
    requests = _validate_updates([keyword(), second], [first_patch, second_patch])
    assert requests == {("333", "20", "90"): first_patch, ("444", "30", "90"): second_patch}


async def test_tool_reverifies_and_returns_exact_before_and_requested_state(monkeypatch) -> None:
    selected = entry()
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(selected,))),
        tool_name=DEFINITION.name,
    )
    client = SequencedClient(
        [
            [{"results": [provider_row()]}],
            {"results": [{"resourceName": "customers/333/adGroupCriteria/20~90"}]},
        ]
    )

    async def passthrough_audit(_ctx, _entry, **kwargs):
        await kwargs["prepare_pending_operation"]()
        return (await kwargs["execute"]()).value

    monkeypatch.setattr(
        "integrations.google_ads.tools.update_positive_keywords.google_ads_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.update_positive_keywords.run_audited_integration_operation",
        passthrough_audit,
    )
    result = await google_ads_update_keywords(
        ctx,
        [keyword()],
        [GoogleAdsPositiveKeywordPatch(status="ENABLED", final_urls=[])],
    )

    output = GoogleAdsUpdatePositiveKeywordsOutput.model_validate(result.metadata["public_result"])
    data = output.results[0].data
    assert data is not None
    assert data.currency_code == "GBP"
    row = data.samples.updated[0]
    assert row.before.status == "PAUSED"
    assert row.before.final_urls == ["https://example.com/old"]
    assert row.requested.status == "ENABLED"
    assert row.requested.final_urls == []
    assert row.requested_fields == ["status", "final_urls"]
    assert row.update_mask == "status,finalUrls"
    assert row.keyword.status == "ENABLED"


async def test_tool_cancellation_records_durable_unverified_evidence(monkeypatch) -> None:
    selected = entry()
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(selected,)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name=DEFINITION.name,
        tool_call_id="keyword-update-cancelled",
    )
    cancellation = asyncio.CancelledError()
    cancellation.failure_disposition = IntegrationFailureDisposition.AMBIGUOUS
    client = SequencedClient([[{"results": [provider_row()]}], cancellation])
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "integrations.google_ads.tools.update_positive_keywords.google_ads_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )

    with pytest.raises(asyncio.CancelledError):
        await google_ads_update_keywords(
            ctx,
            [keyword()],
            [GoogleAdsPositiveKeywordPatch(status="ENABLED")],
        )

    assert [call.kwargs["status"] for call in audit.await_args_list] == [
        AuditStatus.PENDING,
        AuditStatus.UNVERIFIED,
    ]
    terminal = audit.await_args_list[1].kwargs["operation_detail"]
    assert terminal.intent_counts.unverified == 1
    assert terminal.effect_counts.unverified == 1


async def test_tool_rejects_incompatible_keyword_bid_with_live_strategy() -> None:
    selected = entry()
    client = SequencedClient(
        [
            [
                {
                    "results": [
                        {
                            "campaign": {
                                "id": "10",
                                "biddingStrategyType": "MAXIMIZE_CONVERSIONS",
                                "advertisingChannelType": "SEARCH",
                            },
                            "adGroup": {
                                "id": "20",
                                "status": "ENABLED",
                                "type": "SEARCH_STANDARD",
                            },
                        }
                    ]
                }
            ],
        ]
    )
    patch = GoogleAdsPositiveKeywordPatch(cpc_bid="2.00")
    with pytest.raises(ModelRetry, match="MAXIMIZE_CONVERSIONS"):
        await _validate_bid_compatibility(
            client,
            selected,
            [keyword()],
            {("333", "20", "90"): patch},
        )
    assert all(not path.endswith(":mutate") for path, _kwargs in client.calls)
