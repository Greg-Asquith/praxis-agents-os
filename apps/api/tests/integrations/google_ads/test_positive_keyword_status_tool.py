"""Google Ads positive-keyword status action contracts."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry

from core.exceptions.integration import IntegrationError, IntegrationFailureDisposition
from integrations.google_ads.operations.list_positive_keywords import list_positive_keywords
from integrations.google_ads.operations.update_positive_keyword_status import (
    GoogleAdsPositiveKeywordStatusChange,
    positive_keyword_status_failure_ledger,
    update_positive_keyword_status,
)
from integrations.google_ads.references import GoogleAdsKeywordReference
from integrations.google_ads.tools.schemas import GoogleAdsUpdatePositiveKeywordStatusOutput
from integrations.google_ads.tools.update_positive_keyword_status import (
    DEFINITION,
    GoogleAdsKeywordStatusSelection,
    _pending_operation_detail,
    _validate_status_args,
    _validate_updates,
    google_ads_update_keyword_status,
)
from integrations.google_ads.tools.utils.mutation_evidence import terminal_operation_detail
from integrations.google_ads.tools.verifiers import verify_positive_keywords
from services.audit_events import AuditStatus
from services.audit_events.integration_operation_detail import (
    MAX_INTEGRATION_OPERATION_DETAIL_BYTES,
)
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


def keyword(
    criterion_id: str = "90",
    *,
    text: str = "running shoes",
    status: str = "PAUSED",
) -> GoogleAdsKeywordReference:
    return GoogleAdsKeywordReference(
        customer_id="333",
        campaign_id="10",
        ad_group_id="20",
        criterion_id=criterion_id,
        text=text,
        match_type="EXACT",
        status=status,
        label=text,
        scope_label="Search · Shoes",
    )


def provider_row(
    criterion_id: str = "90",
    *,
    ad_group_id: str = "20",
    campaign_id: str = "10",
    text: str = "running shoes",
    status: str = "PAUSED",
) -> dict:
    return {
        "campaign": {"id": campaign_id, "name": "Search"},
        "adGroup": {"id": ad_group_id, "name": "Shoes", "status": "ENABLED"},
        "adGroupCriterion": {
            "resourceName": f"customers/333/adGroupCriteria/{ad_group_id}~{criterion_id}",
            "criterionId": criterion_id,
            "status": status,
            "cpcBidMicros": "1250000",
            "keyword": {"text": text, "matchType": "EXACT"},
        },
    }


async def test_status_operation_updates_only_changed_rows_with_partial_failure() -> None:
    client = SequencedClient(
        [
            {
                "results": [{"resourceName": "customers/333/adGroupCriteria/20~90"}, {}],
                "partialFailureError": {
                    "details": [
                        {
                            "errors": [
                                {
                                    "message": "Criterion cannot be changed",
                                    "errorCode": {"adGroupCriterionError": "CANNOT_MODIFY"},
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
        ]
    )
    ledger = await update_positive_keyword_status(
        client,
        customer_id="333",
        login_customer_id="111",
        changes=[
            GoogleAdsPositiveKeywordStatusChange("20", "90", "PAUSED", "ENABLED"),
            GoogleAdsPositiveKeywordStatusChange("20", "91", "PAUSED", "ENABLED"),
            GoogleAdsPositiveKeywordStatusChange("20", "92", "ENABLED", "ENABLED"),
        ],
    )

    assert ledger.intent_counts == {"requested": 3, "submitted": 2, "skipped": 1}
    assert [effect.outcome for effect in ledger.effects] == ["applied", "failed"]
    assert ledger.effects[1].error_code == "CANNOT_MODIFY"
    path, kwargs = client.calls[0]
    assert path == "customers/333/adGroupCriteria:mutate"
    assert kwargs["policy"] is IntegrationRequestPolicy.MUTATION
    assert kwargs["json"] == {
        "operations": [
            {
                "update": {
                    "resourceName": "customers/333/adGroupCriteria/20~90",
                    "status": "ENABLED",
                },
                "updateMask": "status",
            },
            {
                "update": {
                    "resourceName": "customers/333/adGroupCriteria/20~91",
                    "status": "ENABLED",
                },
                "updateMask": "status",
            },
        ],
        "partialFailure": True,
    }


async def test_status_operation_marks_contradictory_response_unverified() -> None:
    ledger = await update_positive_keyword_status(
        SequencedClient([{"results": [{"resourceName": "customers/999/adGroupCriteria/20~90"}]}]),
        customer_id="333",
        login_customer_id="111",
        changes=[GoogleAdsPositiveKeywordStatusChange("20", "90", "PAUSED", "ENABLED")],
    )

    assert ledger.effects[0].outcome == "unverified"


async def test_live_verifier_rejects_missing_and_changed_criteria() -> None:
    selected = entry()
    with pytest.raises(ModelRetry, match="no longer available"):
        await verify_positive_keywords(
            SequencedClient([[{"results": []}]]),
            entry=selected,
            selected=[keyword()],
        )
    with pytest.raises(ModelRetry, match="changed during verification"):
        await verify_positive_keywords(
            SequencedClient([[{"results": [provider_row(text="changed text")]}]]),
            entry=selected,
            selected=[keyword()],
        )


async def test_live_verifier_distinguishes_matching_criterion_ids_by_ad_group() -> None:
    selected = entry()
    first = keyword()
    second = keyword().model_copy(
        update={"ad_group_id": "30", "campaign_id": "11", "scope_label": "Search · Other"}
    )
    client = SequencedClient(
        [
            [
                {
                    "results": [
                        provider_row(),
                        provider_row(ad_group_id="30", campaign_id="11"),
                    ]
                }
            ]
        ]
    )

    live = await verify_positive_keywords(client, entry=selected, selected=[first, second])

    assert [(reference.ad_group_id, reference.criterion_id) for reference in live] == [
        ("20", "90"),
        ("30", "90"),
    ]
    query = client.calls[0][1]["json"]["query"]
    assert "ad_group.id IN (20, 30)" in query
    assert "ad_group_criterion.criterion_id IN (90)" in query


async def test_keyword_search_cursor_orders_and_filters_composite_identity() -> None:
    client = SequencedClient([[{"results": []}]])

    await list_positive_keywords(
        client,
        customer_id="333",
        login_customer_id="111",
        minimum_id=90,
        minimum_ad_group_id=20,
        limit=25,
    )

    query = client.calls[0][1]["json"]["query"]
    assert (
        "(ad_group_criterion.criterion_id > 90 OR "
        "(ad_group_criterion.criterion_id = 90 AND ad_group.id > 20))" in query
    )
    assert "ORDER BY ad_group_criterion.criterion_id, ad_group.id" in query


def test_status_definition_is_bounded_approval_only_and_selection_free() -> None:
    assert DEFINITION.default_policy == "approval"
    assert DEFINITION.supports_auto is False
    assert DEFINITION.code_eligible is True
    assert "does not recommend or choose" in DEFINITION.description
    fields = {field.key: field for field in DEFINITION.presentation.arg_fields}
    assert fields["keywords"].format == "entity_list"
    assert fields["keywords"].entity_kind == "google_ads_keyword"
    assert fields["keywords"].editable is False
    assert fields["statuses"].format == "records"
    assert fields["statuses"].editable is True
    assert fields["statuses"].columns[0].key == "status"
    assert DEFINITION.args_validator is not None


def test_status_requests_distinguish_matching_criterion_ids_across_accounts() -> None:
    first = keyword()
    second = keyword().model_copy(
        update={"customer_id": "444", "ad_group_id": "30", "campaign_id": "11"}
    )

    requests = _validate_updates(
        [first, second],
        [
            GoogleAdsKeywordStatusSelection(status="ENABLED"),
            GoogleAdsKeywordStatusSelection(status="PAUSED"),
        ],
    )

    assert requests == {
        ("333", "20", "90"): "ENABLED",
        ("444", "30", "90"): "PAUSED",
    }


def test_status_args_validator_rejects_misaligned_rows_before_approval() -> None:
    with pytest.raises(ModelRetry, match="one requested status"):
        _validate_status_args(  # type: ignore[arg-type]
            None,
            [keyword(), keyword("91")],
            [GoogleAdsKeywordStatusSelection(status="ENABLED")],
        )


async def test_status_tool_rejects_duplicate_keywords_before_targeting(monkeypatch) -> None:
    targeting = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.update_positive_keyword_status.run_context_targets",
        targeting,
    )

    with pytest.raises(ModelRetry, match="only once"):
        await google_ads_update_keyword_status(  # type: ignore[arg-type]
            None,
            [keyword(), keyword()],
            [GoogleAdsKeywordStatusSelection(status="ENABLED")],
        )

    targeting.assert_not_awaited()


async def test_status_tool_reverifies_after_approval_and_returns_exact_transitions(
    monkeypatch,
) -> None:
    selected = entry()
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(selected,))),
        tool_name=DEFINITION.name,
    )
    client = SequencedClient(
        [
            [{"results": [provider_row(), provider_row("91", status="ENABLED")]}],
            {
                "results": [
                    {"resourceName": "customers/333/adGroupCriteria/20~90"},
                    {"resourceName": "customers/333/adGroupCriteria/20~91"},
                ]
            },
        ]
    )
    audit_outcomes = []

    async def passthrough_audit(_ctx, _entry, **kwargs):
        await kwargs["prepare_pending_operation"]()
        outcome = await kwargs["execute"]()
        audit_outcomes.append(outcome)
        return outcome.value

    monkeypatch.setattr(
        "integrations.google_ads.tools.update_positive_keyword_status.google_ads_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.update_positive_keyword_status."
        "run_audited_integration_operation",
        passthrough_audit,
    )
    result = await google_ads_update_keyword_status(
        ctx,
        [keyword(), keyword("91", status="PAUSED")],
        [
            GoogleAdsKeywordStatusSelection(status="ENABLED"),
            GoogleAdsKeywordStatusSelection(status="PAUSED"),
        ],
    )

    model_output = GoogleAdsUpdatePositiveKeywordStatusOutput.model_validate(result.return_value)
    display_output = GoogleAdsUpdatePositiveKeywordStatusOutput.model_validate(
        result.metadata["public_result"]
    )
    data = display_output.results[0].data
    assert data is not None
    assert data.counts.model_dump() == {
        "updated": 2,
        "already_set": 0,
        "failed": 0,
        "unverified": 0,
    }
    assert data.samples.updated[0].previous_status == "PAUSED"
    assert data.samples.updated[0].keyword.status == "ENABLED"
    assert data.samples.updated[1].previous_status == "ENABLED"
    assert data.samples.updated[1].keyword.status == "PAUSED"
    assert model_output.results[0].data is not None
    detail = audit_outcomes[0].operation_detail
    assert detail.intent_counts.applied == 2
    assert detail.intent_counts.skipped == 0
    assert detail.effect_counts.applied == 2


async def test_status_tool_retains_unverified_rows_after_ambiguous_failure(monkeypatch) -> None:
    selected = entry()
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(selected,)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name=DEFINITION.name,
        tool_call_id="keyword-status-timeout",
    )
    failure = IntegrationError(
        "Private provider failure",
        provider_key="google_ads",
        operation="update_positive_keyword_status",
        failure_disposition=IntegrationFailureDisposition.AMBIGUOUS,
    )
    client = SequencedClient([[{"results": [provider_row()]}], failure])
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "integrations.google_ads.tools.update_positive_keyword_status.google_ads_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )

    result = await google_ads_update_keyword_status(
        ctx,
        [keyword()],
        [GoogleAdsKeywordStatusSelection(status="ENABLED")],
    )

    output = GoogleAdsUpdatePositiveKeywordStatusOutput.model_validate(result.return_value)
    item = output.results[0]
    assert item.status == "error"
    assert item.error_code == "unverified_mutation"
    assert item.data is not None
    row = item.data.samples.unverified[0]
    assert row.previous_status == "PAUSED"
    assert row.requested_status == "ENABLED"
    assert row.error_code == "IntegrationError"
    assert "Private provider failure" not in (item.error_message or "")
    assert [call.kwargs["status"] for call in audit.await_args_list] == [
        AuditStatus.PENDING,
        AuditStatus.UNVERIFIED,
    ]
    terminal = audit.await_args_list[1].kwargs["operation_detail"]
    assert terminal.intent_counts.unverified == 1
    assert terminal.effect_counts.unverified == 1


async def test_status_tool_cancellation_records_durable_unverified_evidence(monkeypatch) -> None:
    selected = entry()
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(selected,)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name=DEFINITION.name,
        tool_call_id="keyword-status-cancelled",
    )
    cancellation = asyncio.CancelledError()
    cancellation.failure_disposition = IntegrationFailureDisposition.AMBIGUOUS
    client = SequencedClient([[{"results": [provider_row()]}], cancellation])
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "integrations.google_ads.tools.update_positive_keyword_status.google_ads_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )

    with pytest.raises(asyncio.CancelledError):
        await google_ads_update_keyword_status(
            ctx,
            [keyword()],
            [GoogleAdsKeywordStatusSelection(status="ENABLED")],
        )

    assert [call.kwargs["status"] for call in audit.await_args_list] == [
        AuditStatus.PENDING,
        AuditStatus.UNVERIFIED,
    ]
    terminal = audit.await_args_list[1].kwargs["operation_detail"]
    assert terminal.intent_counts.unverified == 1
    assert terminal.effect_counts.unverified == 1


def test_maximum_status_terminal_evidence_stays_bounded() -> None:
    selected = entry()
    references = [keyword(str(index + 1), text=f"{index:03d}{'k' * 77}") for index in range(500)]
    statuses = {
        (reference.customer_id, reference.ad_group_id, reference.criterion_id): "ENABLED"
        for reference in references
    }
    pending = _pending_operation_detail(selected, references, statuses)
    changes = [
        GoogleAdsPositiveKeywordStatusChange(
            reference.ad_group_id,
            reference.criterion_id,
            "PAUSED",
            "ENABLED",
        )
        for reference in references
    ]
    detail = terminal_operation_detail(
        pending,
        positive_keyword_status_failure_ledger(
            changes,
            outcome="failed",
            error_code="E" * 100,
            message="m" * 1_000,
        ),
    )

    serialized = json.dumps(
        detail.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    assert len(serialized) <= MAX_INTEGRATION_OPERATION_DETAIL_BYTES
