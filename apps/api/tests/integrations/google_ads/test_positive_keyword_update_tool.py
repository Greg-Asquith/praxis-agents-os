"""Google Ads positive-keyword update contracts."""

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from pydantic_ai import ModelRetry

from core.exceptions.integration import IntegrationError, IntegrationFailureDisposition
from integrations.google_ads.operations.update_positive_keywords import (
    GoogleAdsPositiveKeywordUpdate,
    positive_keyword_update_failure_ledger,
    positive_keyword_update_preflight_ledger,
    update_positive_keywords,
)
from integrations.google_ads.references import GoogleAdsKeywordReference
from integrations.google_ads.tools.create_positive_keywords import DEFINITION as CREATE_DEFINITION
from integrations.google_ads.tools.schemas import (
    GoogleAdsPositiveKeywordPatch,
    GoogleAdsUpdatePositiveKeywordsOutput,
)
from integrations.google_ads.tools.update_positive_keywords import (
    DEFINITION,
    _approval_display_args,
    _changes,
    _pending_operation_detail,
    _preflight_call,
    _split_result,
    _validate_bid_compatibility,
    _validate_patch_args,
    _validate_pre_dispatch_bounds,
    _validate_updates,
    _validate_url_dependencies,
    google_ads_update_keywords,
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


@pytest.mark.parametrize(
    ("field", "value", "provider_field", "provider_value"),
    [
        ("status", "ENABLED", "status", "ENABLED"),
        ("bid_modifier", 1.5, "bid_modifier", 1.5),
        ("cpc_bid", "2.75", "cpc_bid_micros", 2_750_000),
        ("final_urls", ["https://example.com/new"], "final_urls", ["https://example.com/new"]),
        (
            "final_mobile_urls",
            ["https://m.example.com/new"],
            "final_mobile_urls",
            ["https://m.example.com/new"],
        ),
        ("final_url_suffix", "source=ads", "final_url_suffix", "source=ads"),
        (
            "tracking_url_template",
            "{lpurl}?source=ads",
            "tracking_url_template",
            "{lpurl}?source=ads",
        ),
        (
            "url_custom_parameters",
            {"source": "ads"},
            "url_custom_parameters",
            [{"key": "source", "value": "ads"}],
        ),
    ],
)
async def test_every_supported_patch_field_builds_exact_provider_intent(
    field: str,
    value: object,
    provider_field: str,
    provider_value: object,
) -> None:
    patch = GoogleAdsPositiveKeywordPatch.model_validate({field: value})
    change = _changes([keyword()], {("333", "20", "90"): patch})[0]

    assert change.requested_fields == (provider_field,)
    assert change.requested == {provider_field: provider_value}

    client = SequencedClient(
        [{"results": [{"resourceName": "customers/333/adGroupCriteria/20~90"}]}]
    )
    ledger = await update_positive_keywords(
        client, customer_id="333", login_customer_id="111", changes=[change]
    )
    operation = client.calls[0][1]["json"]["operations"][0]
    display = _split_result(entry(), [keyword()], [change], ledger)["display_result"]
    assert display["samples"]["updated"][0]["update_mask"] == operation["updateMask"]
    assert set(operation["update"]) == {"resourceName", operation["updateMask"]}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "PAUSED"),
        ("bid_modifier", None),
        ("cpc_bid", "1.25"),
        ("final_urls", ["https://example.com/old"]),
        ("final_mobile_urls", []),
        ("final_url_suffix", None),
        ("tracking_url_template", None),
        ("url_custom_parameters", {}),
    ],
)
def test_every_supported_patch_field_can_be_an_exact_no_op(field: str, value: object) -> None:
    patch = GoogleAdsPositiveKeywordPatch.model_validate({field: value})
    change = _changes([keyword()], {("333", "20", "90"): patch})[0]
    ledger = positive_keyword_update_preflight_ledger(
        [change], customer_id="333", outcome="applied"
    )

    assert ledger.intent_counts == {"requested": 1, "submitted": 0, "skipped": 1}
    assert ledger.effects == ()


def test_approval_projection_preserves_omissions_while_rendering_explicit_clears() -> None:
    projected = _approval_display_args(  # type: ignore[arg-type]
        SimpleNamespace(active_context=ResolvedActiveContext(entries=(entry(),))),
        {"keywords": [keyword().model_dump(mode="json")], "patches": [{"cpc_bid": None}]},
    )
    assert projected["patches"] == [{"cpc_bid": ""}]
    assert projected["_account_currencies"] == [
        {"customer_id": "333", "label": "Retail account", "currency_code": "GBP"}
    ]
    assert "status" not in projected["patches"][0]


def test_url_dependency_uses_effective_live_state() -> None:
    selected = keyword().model_copy(update={"tracking_url_template": "{lpurl}?src=ads"})
    changes = _changes(
        [selected],
        {("333", "20", "90"): GoogleAdsPositiveKeywordPatch(final_urls=[])},
    )
    with pytest.raises(ModelRetry, match="tracking template"):
        _validate_url_dependencies([selected], changes)


@pytest.mark.parametrize("status", ["ENABLED", "PAUSED"])
@pytest.mark.parametrize(
    "settings",
    [
        {"final_url_suffix": "src=ads"},
        {"url_custom_parameters": [{"key": "source", "value": "ads"}]},
        {"final_mobile_urls": ["https://m.example.com/shoes"]},
    ],
)
async def test_status_updates_preserve_inherited_destinations(status, settings) -> None:
    selected = GoogleAdsKeywordReference.model_validate(
        {**keyword().model_dump(), "final_urls": [], **settings}
    )
    changes = _changes(
        [selected], {("333", "20", "90"): GoogleAdsPositiveKeywordPatch(status=status)}
    )
    _validate_url_dependencies([selected], changes)
    client = SequencedClient(
        [{"results": [{"resourceName": "customers/333/adGroupCriteria/20~90"}]}]
    )
    ledger = await update_positive_keywords(
        client, customer_id="333", login_customer_id="111", changes=changes
    )
    assert ledger.intent_counts["skipped"] == (status == "PAUSED")
    if client.calls:
        update = client.calls[0][1]["json"]["operations"][0]
        assert update["updateMask"] == "status"


@pytest.mark.parametrize(
    "patch",
    [
        {"final_url_suffix": "src=ads"},
        {"url_custom_parameters": {"source": "ads"}},
        {"final_mobile_urls": ["https://m.example.com/shoes"]},
        {"final_urls": []},
    ],
)
async def test_independent_url_updates_allow_inherited_destinations(patch) -> None:
    selected = keyword().model_copy(update={"final_url_suffix": "existing=1"})
    changes = _changes(
        [selected], {("333", "20", "90"): GoogleAdsPositiveKeywordPatch.model_validate(patch)}
    )
    _validate_url_dependencies([selected], changes)
    client = SequencedClient(
        [{"results": [{"resourceName": "customers/333/adGroupCriteria/20~90"}]}]
    )
    ledger = await update_positive_keywords(
        client, customer_id="333", login_customer_id="111", changes=changes
    )
    assert ledger.effect_counts["applied"] == 1


def test_pending_evidence_rejects_oversized_live_state() -> None:
    long_url = "https://x/" + "a" * 2038
    references = [
        keyword(str(index + 1)).model_copy(update={"final_urls": [long_url] * 10})
        for index in range(30)
    ]
    patches = {
        (reference.customer_id, reference.ad_group_id, reference.criterion_id): (
            GoogleAdsPositiveKeywordPatch(status="ENABLED")
        )
        for reference in references
    }
    with pytest.raises(ModelRetry, match="exact audit evidence"):
        _pending_operation_detail(entry(), references, _changes(references, patches))


@pytest.mark.parametrize("field", ["text", "match_type", "ad_group_id", "criterion_id", "negative"])
def test_patch_rejects_immutable_and_output_fields(field: str) -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        GoogleAdsPositiveKeywordPatch.model_validate({field: "changed"})


def test_patch_requires_a_change_and_uses_empty_collections_for_repeated_clears() -> None:
    with pytest.raises(ValidationError, match="at least one mutable"):
        GoogleAdsPositiveKeywordPatch()
    with pytest.raises(ValidationError, match="empty list or object"):
        GoogleAdsPositiveKeywordPatch(final_urls=None)
    with pytest.raises(ValidationError, match="cannot be cleared"):
        GoogleAdsPositiveKeywordPatch(status=None)


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


def test_ambiguous_failure_accounts_for_every_submitted_patch() -> None:
    change = _changes(
        [keyword()],
        {("333", "20", "90"): GoogleAdsPositiveKeywordPatch(status="ENABLED")},
    )[0]
    ledger = positive_keyword_update_failure_ledger(
        [change], outcome="unverified", error_code="Timeout", message="Outcome unknown"
    )
    assert ledger.intent_counts == {"requested": 1, "submitted": 1, "skipped": 0}
    assert ledger.effects[0].outcome == "unverified"


def test_definition_replaces_status_contract_and_excludes_match_replacement() -> None:
    assert DEFINITION.name == "google_ads_update_keywords"
    assert DEFINITION.default_policy == "approval"
    assert DEFINITION.supports_auto is False
    assert DEFINITION.code_eligible is True
    assert "pause the old keyword" in DEFINITION.description
    assert "separate approval" in DEFINITION.description
    fields = {field.key: field for field in DEFINITION.presentation.arg_fields}
    assert fields["keywords"].format == "entity_list"
    assert fields["keywords"].editable is False
    patch_columns = {column.key for column in fields["patches"].columns}
    assert patch_columns == {
        "status",
        "bid_modifier",
        "cpc_bid",
        "final_urls",
        "final_mobile_urls",
        "final_url_suffix",
        "tracking_url_template",
        "url_custom_parameters",
    }
    assert not {"text", "match_type", "ad_group_id", "criterion_id"}.intersection(patch_columns)


def test_match_type_workflow_requires_two_approval_only_mutations() -> None:
    assert DEFINITION.default_policy == CREATE_DEFINITION.default_policy == "approval"
    assert DEFINITION.supports_auto is CREATE_DEFINITION.supports_auto is False
    assert DEFINITION.name == "google_ads_update_keywords"
    assert CREATE_DEFINITION.name == "google_ads_create_keywords"
    assert "pause the old keyword" in DEFINITION.description
    assert "separate approval" in DEFINITION.description
    assert "old keyword remains paused" in DEFINITION.description


def test_validator_rejects_misaligned_rows_before_approval() -> None:
    with pytest.raises(ModelRetry, match="one ordered patch"):
        _validate_patch_args(  # type: ignore[arg-type]
            None,
            [keyword(), keyword("91")],
            [GoogleAdsPositiveKeywordPatch(status="ENABLED")],
        )


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


async def test_tool_retains_unverified_rows_after_ambiguous_failure(monkeypatch) -> None:
    selected = entry()
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(selected,)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name=DEFINITION.name,
        tool_call_id="keyword-update-timeout",
    )
    failure = IntegrationError(
        "Private provider failure",
        provider_key="google_ads",
        operation="update_positive_keywords",
        failure_disposition=IntegrationFailureDisposition.AMBIGUOUS,
    )
    client = SequencedClient([[{"results": [provider_row()]}], failure])
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "integrations.google_ads.tools.update_positive_keywords.google_ads_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )

    result = await google_ads_update_keywords(
        ctx,
        [keyword()],
        [GoogleAdsPositiveKeywordPatch(status="ENABLED")],
    )

    output = GoogleAdsUpdatePositiveKeywordsOutput.model_validate(result.return_value)
    item = output.results[0]
    assert item.status == "error"
    assert item.error_code == "unverified_mutation"
    assert item.data is not None
    row = item.data.samples.unverified[0]
    assert row.before.status == "PAUSED"
    assert row.requested.status == "ENABLED"
    assert row.error_code == "IntegrationError"
    assert "Private provider failure" not in (item.error_message or "")
    assert [call.kwargs["status"] for call in audit.await_args_list] == [
        AuditStatus.PENDING,
        AuditStatus.UNVERIFIED,
    ]
    terminal = audit.await_args_list[1].kwargs["operation_detail"]
    assert terminal.intent_counts.unverified == 1
    assert terminal.effect_counts.unverified == 1


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


@pytest.mark.parametrize(("count", "status"), [(100, "ENABLED"), (500, "PAUSED")])
def test_accepted_batch_fits_every_terminal_and_public_outcome(count, status) -> None:
    references = [
        keyword(str(index + 1)).model_copy(update={"text": f"keyword {index:03d}"})
        for index in range(count)
    ]
    patches = {
        (reference.customer_id, reference.ad_group_id, reference.criterion_id): (
            GoogleAdsPositiveKeywordPatch(status=status)
        )
        for reference in references
    }
    changes = _changes(references, patches)
    pending = _pending_operation_detail(entry(), references, changes)

    _validate_pre_dispatch_bounds(entry(), references, changes, pending)
    for outcome in ("applied", "failed", "unverified"):
        ledger = positive_keyword_update_preflight_ledger(
            changes,
            customer_id="333",
            outcome=outcome,
        )
        detail = terminal_operation_detail(
            pending,
            ledger,
            identity_keys=("ad_group_id", "criterion_id"),
        )
        serialized = json.dumps(
            detail.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        assert len(serialized) <= MAX_INTEGRATION_OPERATION_DETAIL_BYTES
        display = _split_result(entry(), references, changes, ledger)["display_result"]
        assert display["samples_truncated"] is False
        assert sum(len(rows) for rows in display["samples"].values()) == count


def test_oversized_terminal_boundary_is_rejected_before_dispatch() -> None:
    long_url = "https://example.com/" + "x" * 545
    references = [
        keyword(str(index + 1)).model_copy(update={"final_urls": [long_url]})
        for index in range(500)
    ]
    patches = {
        (reference.customer_id, reference.ad_group_id, reference.criterion_id): (
            GoogleAdsPositiveKeywordPatch(status="ENABLED")
        )
        for reference in references
    }
    changes = _changes(references, patches)
    pending = _pending_operation_detail(entry(), references, changes)

    with pytest.raises(ModelRetry, match="complete audit and result evidence"):
        _validate_pre_dispatch_bounds(entry(), references, changes, pending)


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


@pytest.mark.parametrize(
    ("patch", "channel", "ad_group_type", "dimension"),
    [
        pytest.param(
            GoogleAdsPositiveKeywordPatch(cpc_bid="2.00"),
            "SEARCH",
            "SEARCH_STANDARD",
            "",
            id="search-cpc",
        ),
        pytest.param(
            GoogleAdsPositiveKeywordPatch(cpc_bid="2.00"),
            "DISPLAY",
            "DISPLAY_STANDARD",
            "KEYWORD",
            id="display-cpc",
        ),
        pytest.param(
            GoogleAdsPositiveKeywordPatch(bid_modifier=1.25),
            "DISPLAY",
            "DISPLAY_STANDARD",
            "PLACEMENT",
            id="display-bid-adjustment",
        ),
    ],
)
async def test_tool_allows_supported_live_bid_combinations(
    patch: GoogleAdsPositiveKeywordPatch,
    channel: str,
    ad_group_type: str,
    dimension: str,
) -> None:
    client = SequencedClient(
        [
            [
                {
                    "results": [
                        {
                            "campaign": {
                                "id": "10",
                                "biddingStrategyType": "MANUAL_CPC",
                                "advertisingChannelType": channel,
                            },
                            "adGroup": {
                                "id": "20",
                                "status": "ENABLED",
                                "type": ad_group_type,
                                "displayCustomBidDimension": dimension,
                            },
                        }
                    ]
                }
            ]
        ]
    )

    await _validate_bid_compatibility(
        client,
        entry(),
        [keyword()],
        {("333", "20", "90"): patch},
    )


@pytest.mark.parametrize(
    ("channel", "dimension"),
    [("SEARCH", ""), ("DISPLAY", "KEYWORD")],
)
async def test_tool_rejects_incompatible_live_bid_adjustment(
    channel: str,
    dimension: str,
) -> None:
    client = SequencedClient(
        [
            [
                {
                    "results": [
                        {
                            "campaign": {
                                "id": "10",
                                "biddingStrategyType": "MANUAL_CPC",
                                "advertisingChannelType": channel,
                            },
                            "adGroup": {
                                "id": "20",
                                "status": "ENABLED",
                                "type": (
                                    "SEARCH_STANDARD" if channel == "SEARCH" else "DISPLAY_STANDARD"
                                ),
                                "displayCustomBidDimension": dimension,
                            },
                        }
                    ]
                }
            ]
        ]
    )

    with pytest.raises(ModelRetry, match="bid modifier"):
        await _validate_bid_compatibility(
            client,
            entry(),
            [keyword()],
            {("333", "20", "90"): GoogleAdsPositiveKeywordPatch(bid_modifier=1.25)},
        )


async def test_bid_clear_does_not_require_live_bid_context() -> None:
    client = SequencedClient([])
    await _validate_bid_compatibility(
        client,
        entry(),
        [keyword()],
        {("333", "20", "90"): GoogleAdsPositiveKeywordPatch(bid_modifier=None)},
    )
    assert client.calls == []


async def test_bid_context_lookup_batches_ad_groups_and_detects_changed_campaign() -> None:
    references = [
        keyword(str(index + 1)).model_copy(
            update={"ad_group_id": str(index + 1), "campaign_id": "10"}
        )
        for index in range(101)
    ]
    patches = {
        (reference.customer_id, reference.ad_group_id, reference.criterion_id): (
            GoogleAdsPositiveKeywordPatch(cpc_bid="2")
        )
        for reference in references
    }

    def rows(selected: list[GoogleAdsKeywordReference]) -> list[dict]:
        return [
            {
                "campaign": {
                    "id": "10",
                    "biddingStrategyType": "MANUAL_CPC",
                    "advertisingChannelType": "SEARCH",
                },
                "adGroup": {
                    "id": reference.ad_group_id,
                    "status": "ENABLED",
                    "type": "SEARCH_STANDARD",
                },
            }
            for reference in selected
        ]

    client = SequencedClient(
        [[{"results": rows(references[:100])}], [{"results": rows(references[100:])}]]
    )
    await _validate_bid_compatibility(client, entry(), references, patches)
    assert len(client.calls) == 2

    changed = rows([references[0]])
    changed[0]["campaign"]["id"] = "11"
    with pytest.raises(ModelRetry, match="changed campaigns"):
        await _validate_bid_compatibility(
            SequencedClient([[{"results": changed}]]),
            entry(),
            [references[0]],
            {next(iter(patches)): GoogleAdsPositiveKeywordPatch(cpc_bid="2")},
        )


async def test_whole_call_budget_rejects_two_large_accounts_before_any_provider_call(
    monkeypatch,
) -> None:
    first = entry()
    second = replace(first, external_id="444")
    references = [
        keyword(str(index + 1)).model_copy(
            update={"customer_id": account, "final_urls": ["https://example.com/" + "x" * 400]}
        )
        for account in ("333", "444")
        for index in range(250)
    ]
    client_factory = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.update_positive_keywords.google_ads_client", client_factory
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(first, second))),
        tool_name=DEFINITION.name,
    )
    with pytest.raises(ModelRetry, match="complete audit and result evidence"):
        await google_ads_update_keywords(
            ctx, references, [GoogleAdsPositiveKeywordPatch(status="ENABLED") for _ in references]
        )
    client_factory.assert_not_awaited()


@pytest.mark.parametrize("diagnostic", ['"', "\x00", "\n", "\\", "界"])
@pytest.mark.parametrize("outcome", ["failed", "unverified", "applied", "mixed", "noop"])
async def test_accepted_multi_account_results_pass_real_runtime_serialization(
    diagnostic, outcome
) -> None:
    from services.agents.runtime.dispatch import prepare_public_result
    from services.integrations.context.results import (
        IntegrationContextResult,
        split_fan_out_tool_return,
    )

    entries = [entry(), replace(entry(), external_id="444")]
    references = [
        keyword(str(index + 1)).model_copy(update={"customer_id": selected.external_id})
        for selected in entries
        for index in range(30)
    ]
    status = "PAUSED" if outcome == "noop" else "ENABLED"
    patches = _validate_updates(
        references, [GoogleAdsPositiveKeywordPatch(status=status) for _ in references]
    )
    budgets = _preflight_call(
        SimpleNamespace(active_context=ResolvedActiveContext(entries=tuple(entries))),
        references,
        patches,
    )
    results = []
    for selected in entries:
        scoped = [ref for ref in references if ref.customer_id == selected.external_id]
        changes = _changes(scoped, patches)
        if outcome in {"failed", "unverified"}:
            ledger = positive_keyword_update_failure_ledger(
                changes, outcome=outcome, error_code=diagnostic * 100, message=diagnostic * 500
            )
        else:
            payload = {
                "results": [
                    {
                        "resourceName": f"customers/{selected.external_id}/adGroupCriteria/20~{ref.criterion_id}"
                    }
                    for ref in scoped
                ]
            }
            if outcome == "mixed":
                payload["results"][0] = {}
            ledger = await update_positive_keywords(
                SequencedClient([payload]),
                customer_id=selected.external_id,
                login_customer_id="111",
                changes=changes,
            )
        pending = _pending_operation_detail(selected, scoped, changes)
        detail = terminal_operation_detail(
            pending, ledger, identity_keys=("ad_group_id", "criterion_id")
        )
        assert (
            len(
                json.dumps(
                    detail.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
                ).encode()
            )
            <= MAX_INTEGRATION_OPERATION_DETAIL_BYTES
        )
        split = _split_result(selected, scoped, changes, ledger)
        display = split["display_result"]
        assert sum(map(len, display["samples"].values())) == len(scoped)
        assert not display["samples_truncated"]
        assert (
            len(json.dumps(display, ensure_ascii=False, separators=(",", ":")))
            <= budgets[selected.external_id]
        )
        results.append(IntegrationContextResult(entry=selected, status="success", data=split))
    result = split_fan_out_tool_return(results)
    assert prepare_public_result(DEFINITION, result) <= DEFINITION.max_public_result_chars
