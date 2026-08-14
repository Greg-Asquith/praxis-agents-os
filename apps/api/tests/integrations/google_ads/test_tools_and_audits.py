"""Google Ads tool execution, approval, result, and audit contracts."""

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from pydantic_ai import (
    Agent,
    DeferredToolRequests,
    DeferredToolResults,
    ModelRetry,
    ToolApproved,
)
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from integrations.google_ads.references import (
    GoogleAdsCampaignReference,
    GoogleAdsSharedSetReference,
)
from integrations.google_ads.tools.add_negative_keywords import (
    _pending_negative_keyword_operation_detail,
    google_ads_add_negative_keywords,
)
from integrations.google_ads.tools.create_negative_keyword_list import (
    _pending_operation_detail as create_list_pending_operation_detail,
    google_ads_create_negative_keyword_list,
)
from integrations.google_ads.tools.link_negative_keyword_list import (
    _campaign_link_result,
    google_ads_link_negative_keyword_list,
)
from integrations.google_ads.tools.schemas.negative_keyword import (
    NegativeKeywordEntry,
    NegativeKeywordRemovalEntry,
)
from integrations.google_ads.tools.update_campaign_status import (
    _pending_operation_detail as campaign_status_pending_operation_detail,
    google_ads_update_campaign_status,
)
from integrations.google_ads.tools.utils import (
    MAX_NEGATIVE_KEYWORD_PUBLIC_RESULT_CHARS,
    MAX_NEGATIVE_KEYWORD_RESULT_CHARS,
    bounded_negative_keyword_removal_result,
    bounded_negative_keyword_result,
    complete_negative_keyword_removal_result,
    complete_negative_keyword_result,
    normalize_negative_keywords,
)
from integrations.google_ads.tools.utils.mutation_evidence import (
    audit_status,
    terminal_operation_detail,
)
from integrations.google_ads.tools.verifiers import (
    verify_ad_groups,
    verify_campaigns,
    verify_shared_sets,
)
from services.audit_events import AuditStatus
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)
from tests.integrations.google_ads.support import (
    _campaign_reference,
    _writable_google_ads_entry,
    mutation_ledger_double,
)


async def test_durable_audit_failure_after_provider_write_is_not_silenced(monkeypatch) -> None:
    pending_event_id = uuid4()
    audit = AsyncMock(side_effect=[pending_event_id, RuntimeError("database unavailable")])
    execute = AsyncMock()
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name="google_ads_add_negative_keywords",
    )
    entry = _writable_google_ads_entry()
    detail = _pending_negative_keyword_operation_detail(
        entry,
        GoogleAdsSharedSetReference(
            customer_id=entry.external_id,
            shared_set_id="50",
            label="Brand Protection",
        ),
        [{"text": "brand", "match_type": "EXACT"}],
    )
    terminal_detail = terminal_operation_detail(
        detail,
        mutation_ledger_double(
            {
                "added": [
                    {
                        "text": "brand",
                        "match_type": "EXACT",
                        "resource_name": "customers/111/sharedCriteria/50~1",
                    }
                ],
                "skipped_existing": [],
                "keyword_errors": [],
            }
        ),
    )
    execute.return_value = IntegrationAuditOutcome({"ok": True}, operation_detail=terminal_detail)
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_ads_add_negative_keywords",
            operation="add_negative_keywords",
            execute=execute,
            pending_operation_detail=detail,
        )

    execute.assert_awaited_once()
    assert [call.kwargs["status"] for call in audit.await_args_list] == [
        AuditStatus.PENDING,
        AuditStatus.SUCCESS,
    ]
    assert audit.await_args_list[1].kwargs["related_event_id"] == pending_event_id


async def test_durable_audit_requires_pending_evidence() -> None:
    execute = AsyncMock()

    with pytest.raises(ValueError, match="require pending operation detail"):
        await run_audited_integration_operation(
            SimpleNamespace(tool_name="google_ads_add_negative_keywords"),  # type: ignore[arg-type]
            _writable_google_ads_entry(),
            tool_name="google_ads_add_negative_keywords",
            operation="add_negative_keywords",
            execute=execute,
        )

    execute.assert_not_awaited()


@pytest.mark.parametrize("outcome", ["added", "skipped_existing", "failed"])
def test_negative_keyword_model_result_is_bounded_with_accurate_counts(outcome: str) -> None:
    keyword = {"text": "x" * 80, "match_type": "PHRASE"}
    provider_result = {
        "added": [],
        "skipped_existing": [],
        "keyword_errors": [],
    }
    if outcome == "added":
        provider_result["added"] = [
            {
                **keyword,
                "resource_name": f"customers/333/sharedCriteria/{'9' * 900}~{index}",
            }
            for index in range(500)
        ]
    elif outcome == "skipped_existing":
        provider_result["skipped_existing"] = [keyword.copy() for _ in range(500)]
    else:
        provider_result["keyword_errors"] = [
            {
                "scope": "keyword",
                **keyword,
                "message": "provider failure " + "y" * 2_000,
                "error_code": "INVALID_KEYWORD_TEXT",
            }
            for _ in range(500)
        ]

    result = bounded_negative_keyword_result(provider_result)
    serialized = json.dumps(
        result,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )

    assert len(serialized) <= MAX_NEGATIVE_KEYWORD_RESULT_CHARS
    assert result["counts"] == {
        "added": 500 if outcome == "added" else 0,
        "skipped_existing": 500 if outcome == "skipped_existing" else 0,
        "failed": 500 if outcome == "failed" else 0,
    }
    assert result["samples_truncated"] is True
    assert 0 < len(result["samples"][outcome]) <= 10
    assert "added_keywords" not in result
    assert "resource_names" not in result
    if outcome == "added":
        assert set(result["samples"]["added"][0]) == {
            "text",
            "match_type",
            "resource_name",
        }


def test_negative_keyword_display_result_retains_every_row() -> None:
    added = [
        {
            "text": f"term {index}",
            "match_type": "EXACT",
            "resource_name": f"customers/333/sharedCriteria/50~{index}",
        }
        for index in range(500)
    ]

    result = complete_negative_keyword_result(
        {"added": added, "skipped_existing": [], "keyword_errors": []}
    )

    assert result["counts"]["added"] == 500
    assert result["samples"]["added"] == added
    assert result["samples_truncated"] is False


def test_negative_keyword_removal_results_bound_model_data_and_keep_safe_display_rows() -> None:
    provider_result = {
        "removed": [
            {
                "text": f"term {index}",
                "match_type": "EXACT",
                "resource_name": f"customers/333/sharedCriteria/50~{index}",
            }
            for index in range(500)
        ],
        "not_found": [{"text": "missing", "match_type": "ANY"}],
        "keyword_errors": [
            {
                "scope": "keyword",
                "text": "failed",
                "match_type": "PHRASE",
                "message": "provider failure " + "y" * 2_000,
                "error_code": "E" * 200,
            }
        ],
    }

    model_result = bounded_negative_keyword_removal_result(provider_result)
    display_result = complete_negative_keyword_removal_result(provider_result)

    assert len(json.dumps(model_result, ensure_ascii=False)) <= MAX_NEGATIVE_KEYWORD_RESULT_CHARS
    assert model_result["counts"] == {"removed": 500, "not_found": 1, "failed": 1}
    assert model_result["samples_truncated"] is True
    assert len(display_result["samples"]["removed"]) == 500
    assert len(display_result["samples"]["failed"][0]["message"]) == 500
    assert len(display_result["samples"]["failed"][0]["error_code"]) == 100
    assert len(json.dumps(display_result, ensure_ascii=False)) < (
        MAX_NEGATIVE_KEYWORD_PUBLIC_RESULT_CHARS
    )


def test_negative_keyword_audit_detail_retains_all_applied_rows() -> None:
    entry = _writable_google_ads_entry()
    reference = GoogleAdsSharedSetReference(
        customer_id=entry.external_id,
        shared_set_id="50",
        label="Brand Protection",
    )
    provider_result = {
        "added": [
            {
                "text": f"keyword {index}",
                "match_type": "EXACT",
                "resource_name": f"customers/333/sharedCriteria/50~{index}",
            }
            for index in range(500)
        ],
        "skipped_existing": [],
        "keyword_errors": [],
    }

    pending = _pending_negative_keyword_operation_detail(
        entry,
        reference,
        [
            {"text": item["text"], "match_type": item["match_type"]}
            for item in provider_result["added"]
        ],
    )
    detail = terminal_operation_detail(pending, mutation_ledger_double(provider_result))

    assert detail.intent_counts.applied == 500
    assert len(detail.intent_groups[0].items) == 500
    assert detail.intent_groups[0].items[0].fields["text"] == "keyword 0"
    assert detail.intent_groups[0].items[-1].fields["text"] == "keyword 499"
    assert (
        detail.outcome_groups[0].outcomes[-1].effects[0].external_ref
        == "customers/333/sharedCriteria/50~499"
    )


def test_negative_keyword_normalization_is_pairwise_and_bounded() -> None:
    normalized = normalize_negative_keywords(
        [
            NegativeKeywordEntry(text="  Brand   Term ", match_type="EXACT"),
            NegativeKeywordEntry(text="brand term", match_type="EXACT"),
            NegativeKeywordEntry(text="brand term", match_type="PHRASE"),
        ]
    )

    assert [item.model_dump() for item in normalized] == [
        {"text": "Brand Term", "match_type": "EXACT"},
        {"text": "brand term", "match_type": "PHRASE"},
    ]


def test_negative_keyword_removal_any_absorbs_same_text_precise_rows() -> None:
    normalized = normalize_negative_keywords(
        [
            NegativeKeywordRemovalEntry(text="Brand Term", match_type="EXACT"),
            NegativeKeywordRemovalEntry(text="brand term", match_type="ANY"),
            NegativeKeywordRemovalEntry(text="BRAND TERM", match_type="PHRASE"),
            NegativeKeywordRemovalEntry(text="other", match_type="BROAD"),
        ]
    )

    assert [item.model_dump() for item in normalized] == [
        {"text": "brand term", "match_type": "ANY"},
        {"text": "other", "match_type": "BROAD"},
    ]


def test_negative_keyword_entry_normalizes_whitespace_before_length_validation() -> None:
    entry = NegativeKeywordEntry(
        text=f"   Brand{' ' * 81}Term   ",
        match_type="EXACT",
    )

    assert entry.text == "Brand Term"


def test_negative_keyword_entry_accepts_exactly_80_normalized_characters() -> None:
    entry = NegativeKeywordEntry(
        text=f"  {'x' * 80}  ",
        match_type="EXACT",
    )

    assert entry.text == "x" * 80


def test_negative_keyword_entry_rejects_81_normalized_characters() -> None:
    with pytest.raises(ValidationError, match="at most 80 characters"):
        NegativeKeywordEntry(text=f"  {'x' * 81}  ", match_type="EXACT")


@pytest.mark.parametrize("text", ["one two three four five six seven eight nine ten eleven"])
def test_negative_keyword_normalization_retries_invalid_text(text: str) -> None:
    with pytest.raises(ModelRetry):
        normalize_negative_keywords([NegativeKeywordEntry(text=text, match_type="EXACT")])


def test_negative_keyword_entry_rejects_empty_normalized_text() -> None:
    with pytest.raises(ValidationError, match="at least 1 character"):
        NegativeKeywordEntry(text="   ", match_type="EXACT")


async def test_negative_keyword_approval_resume_validates_canonical_override_text() -> None:
    executed: list[NegativeKeywordEntry] = []

    def model(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        if not any(message.kind == "request" for message in messages[1:]):
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="add_keywords",
                        args={"keywords": [{"text": "original", "match_type": "EXACT"}]},
                        tool_call_id="approval-call",
                    )
                ]
            )
        return ModelResponse(parts=[TextPart(content="done")])

    agent = Agent(
        FunctionModel(model),
        output_type=[str, DeferredToolRequests],
    )

    @agent.tool_plain(requires_approval=True)
    def add_keywords(keywords: list[NegativeKeywordEntry]) -> str:
        executed.extend(keywords)
        return "added"

    suspended = await agent.run("Add a keyword")
    assert isinstance(suspended.output, DeferredToolRequests)

    resumed = await agent.run(
        message_history=suspended.all_messages(),
        deferred_tool_results=DeferredToolResults(
            approvals={
                "approval-call": ToolApproved(
                    override_args={
                        "keywords": [
                            {
                                "text": f"   Edited{' ' * 81}Brand   ",
                                "match_type": "PHRASE",
                            }
                        ]
                    }
                )
            }
        ),
    )

    assert resumed.output == "done"
    assert [entry.model_dump() for entry in executed] == [
        {"text": "Edited Brand", "match_type": "PHRASE"}
    ]


def test_negative_keyword_entry_forbids_extra_keys() -> None:
    with pytest.raises(ValidationError):
        NegativeKeywordEntry.model_validate(
            {"text": "term", "match_type": "EXACT", "provider_id": "unsafe"}
        )


async def test_add_negative_keywords_retries_above_bulk_bound() -> None:
    with pytest.raises(ModelRetry, match="at most 500"):
        await google_ads_add_negative_keywords(
            None,  # type: ignore[arg-type]
            GoogleAdsSharedSetReference(
                customer_id="111",
                shared_set_id="50",
                label="Brand Protection",
            ),
            [
                NegativeKeywordEntry(text=f"term {index}", match_type="EXACT")
                for index in range(501)
            ],
        )


async def test_create_negative_keyword_list_normalizes_and_fans_out_by_account(
    monkeypatch,
) -> None:
    entries = tuple(
        ResolvedContextEntry(
            integration_resource_id=uuid4(),
            provider_key="google_ads",
            resource_type="google_ads_account",
            external_id=customer_id,
            display_name=f"Account {customer_id}",
            connection_id=uuid4(),
            connection_label="Agency",
            connection_status="active",
            write_allowed=True,
            permissions_metadata={"login_customer_id": "999"},
        )
        for customer_id in ("111", "222")
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=entries)),
        tool_name="google_ads_create_negative_keyword_list",
    )
    provider_create = AsyncMock(
        side_effect=lambda _client, **kwargs: mutation_ledger_double(
            {
                "created_names": ["Alpha List", "Beta List"],
                "resource_names": [
                    f"customers/{kwargs['customer_id']}/sharedSets/1",
                    f"customers/{kwargs['customer_id']}/sharedSets/2",
                ],
                "skipped_existing": [],
                "list_errors": [],
            }
        )
    )
    audited_calls: list[dict[str, Any]] = []

    async def passthrough_audit(_ctx, _entry, **kwargs):
        audited_calls.append(kwargs)
        return (await kwargs["execute"]()).value

    monkeypatch.setattr(
        "integrations.google_ads.tools.create_negative_keyword_list.google_ads_client",
        AsyncMock(return_value=object()),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.create_negative_keyword_list.create_negative_keyword_list",
        provider_create,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.create_negative_keyword_list.run_audited_integration_operation",
        passthrough_audit,
    )

    result = await google_ads_create_negative_keyword_list(
        ctx,
        ["  Alpha   List  ", "", "alpha list", " Beta List "],
    )

    assert [item["status"] for item in result["results"]] == ["success", "success"]
    assert [call.kwargs["customer_id"] for call in provider_create.await_args_list] == [
        "111",
        "222",
    ]
    assert all(
        call.kwargs["names"] == ["Alpha List", "Beta List"]
        for call in provider_create.await_args_list
    )
    pending = audited_calls[0]["pending_operation_detail"]
    assert [item.fields["name"] for item in pending.intent_groups[0].items] == [
        "Alpha List",
        "Beta List",
    ]


def test_create_negative_keyword_list_audit_detail_covers_partial_and_noop_results() -> None:
    entry = _writable_google_ads_entry()
    partial_result = {
        "created_names": ["Created List"],
        "resource_names": ["customers/111/sharedSets/50"],
        "skipped_existing": ["Existing List"],
        "list_errors": [{"name": "Rejected List", "error_code": "INVALID_NAME"}],
    }

    pending = create_list_pending_operation_detail(
        entry,
        ["Created List", "Existing List", "Rejected List"],
    )
    detail = terminal_operation_detail(pending, mutation_ledger_double(partial_result))

    assert audit_status(detail) == AuditStatus.PARTIAL
    assert detail.target.external_id == "111"
    assert [outcome.status for outcome in detail.outcome_groups[0].outcomes] == [
        "applied",
        "skipped",
        "failed",
    ]
    assert (
        detail.outcome_groups[0].outcomes[0].effects[0].external_ref
        == "customers/111/sharedSets/50"
    )
    assert detail.intent_counts.model_dump() == {
        "applied": 1,
        "skipped": 1,
        "failed": 1,
        "unverified": 0,
    }

    noop_result = {
        "created_names": [],
        "resource_names": [],
        "skipped_existing": ["Existing List"],
        "list_errors": [],
    }
    noop = terminal_operation_detail(
        create_list_pending_operation_detail(entry, ["Existing List"]),
        mutation_ledger_double(noop_result),
    )
    assert audit_status(noop) == AuditStatus.SUCCESS
    assert noop.intent_counts.model_dump() == {
        "applied": 0,
        "skipped": 1,
        "failed": 0,
        "unverified": 0,
    }

    failed_result = {
        "created_names": [],
        "resource_names": [],
        "skipped_existing": [],
        "list_errors": [
            {"name": "Rejected List", "error_code": "INVALID_NAME", "message": "invalid"}
        ],
    }
    failed = terminal_operation_detail(
        create_list_pending_operation_detail(entry, ["Rejected List"]),
        mutation_ledger_double(failed_result),
    )
    assert audit_status(failed) == AuditStatus.FAILURE


async def test_create_negative_keyword_list_durable_audit_failures_are_not_success(
    monkeypatch,
) -> None:
    entry = _writable_google_ads_entry()
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(entry,)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name="google_ads_create_negative_keyword_list",
    )
    provider_client = AsyncMock(return_value=object())
    provider_create = AsyncMock(
        return_value=mutation_ledger_double(
            {
                "created_names": ["New List"],
                "resource_names": ["customers/111/sharedSets/50"],
                "skipped_existing": [],
                "list_errors": [],
            }
        )
    )
    audit = AsyncMock(side_effect=RuntimeError("pending audit unavailable"))
    monkeypatch.setattr(
        "integrations.google_ads.tools.create_negative_keyword_list.google_ads_client",
        provider_client,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.create_negative_keyword_list.create_negative_keyword_list",
        provider_create,
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )

    pending_failure = await google_ads_create_negative_keyword_list(ctx, ["New List"])

    assert pending_failure["results"][0]["status"] == "error"
    provider_client.assert_not_awaited()
    provider_create.assert_not_awaited()

    pending_event_id = uuid4()
    audit.side_effect = [pending_event_id, RuntimeError("terminal audit unavailable")]
    audit.reset_mock()

    terminal_failure = await google_ads_create_negative_keyword_list(ctx, ["New List"])

    assert terminal_failure["results"][0]["status"] == "error"
    assert "terminal audit unavailable" in terminal_failure["results"][0]["error_message"]
    provider_create.assert_awaited_once()
    assert [call.kwargs["status"] for call in audit.await_args_list] == [
        AuditStatus.PENDING,
        AuditStatus.SUCCESS,
    ]
    assert audit.await_args_list[1].kwargs["related_event_id"] == pending_event_id


@pytest.mark.parametrize("names", [[], ["  ", "\t"], ["x" * 256], ["é" * 128]])
async def test_create_negative_keyword_list_retries_invalid_names(names: list[str]) -> None:
    with pytest.raises(ModelRetry):
        await google_ads_create_negative_keyword_list(None, names)  # type: ignore[arg-type]


async def test_create_negative_keyword_list_write_denial_is_audited_before_provider_call(
    monkeypatch,
) -> None:
    entry = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="google_ads",
        resource_type="google_ads_account",
        external_id="333",
        display_name="Read-only account",
        connection_id=uuid4(),
        connection_label="Agency",
        connection_status="active",
        write_allowed=False,
        permissions_metadata={"login_customer_id": "111"},
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(entry,)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name="google_ads_create_negative_keyword_list",
        tool_call_id="call-denied",
    )
    provider_client = AsyncMock()
    audit = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.create_negative_keyword_list.google_ads_client",
        provider_client,
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )

    result = await google_ads_create_negative_keyword_list(ctx, ["New List"])

    assert result["results"][0]["error_code"] == "write_not_permitted"
    provider_client.assert_not_awaited()
    audit.assert_awaited_once()
    assert audit.await_args.kwargs["status"].value == "failure"
    assert audit.await_args.kwargs["error_code"] == "write_not_permitted"


async def test_campaign_update_groups_ids_by_referenced_customer(monkeypatch) -> None:
    entries = tuple(
        ResolvedContextEntry(
            integration_resource_id=uuid4(),
            provider_key="google_ads",
            resource_type="google_ads_account",
            external_id=customer_id,
            display_name=f"Account {customer_id}",
            connection_id=uuid4(),
            connection_label="Agency",
            connection_status="active",
            write_allowed=True,
            permissions_metadata={"login_customer_id": customer_id},
        )
        for customer_id in ("111", "222")
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=entries)),
        tool_name="google_ads_update_campaign_status",
    )
    client = AsyncMock()

    async def lookup(_path, **kwargs):
        query = kwargs["json"]["query"]
        campaign_id = "10" if "10" in query else "20"
        return {"results": [{"campaign": {"id": campaign_id}}]}

    client.post.side_effect = lookup
    provider_update = AsyncMock(
        side_effect=lambda _client, **kwargs: mutation_ledger_double(
            {
                "resource_names": [
                    f"customers/{kwargs['customer_id']}/campaigns/{campaign_id}"
                    for campaign_id in kwargs["campaign_ids"]
                ],
                "campaign_errors": [],
            }
        )
    )
    audited_calls: list[dict[str, Any]] = []

    async def passthrough_audit(_ctx, _entry, **kwargs):
        audited_calls.append(kwargs)
        return (await kwargs["execute"]()).value

    monkeypatch.setattr(
        "integrations.google_ads.tools.update_campaign_status.google_ads_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.update_campaign_status.update_campaign_status",
        provider_update,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.update_campaign_status.run_audited_integration_operation",
        passthrough_audit,
    )

    result = await google_ads_update_campaign_status(
        ctx,
        [
            GoogleAdsCampaignReference(
                customer_id=entries[0].external_id,
                campaign_id="10",
                label="First campaign",
            ),
            GoogleAdsCampaignReference(
                customer_id=entries[1].external_id,
                campaign_id="20",
                label="Second campaign",
            ),
        ],
        "PAUSED",
    )

    assert len(result["results"]) == 2
    assert [item["status"] for item in result["results"]] == ["success", "success"], [
        item["error_message"] for item in result["results"]
    ]
    assert [call.kwargs["customer_id"] for call in provider_update.await_args_list] == [
        "111",
        "222",
    ]
    assert [call.kwargs["campaign_ids"] for call in provider_update.await_args_list] == [
        ["10"],
        ["20"],
    ]
    pending = audited_calls[0]["pending_operation_detail"]
    assert pending.intent_groups[0].fields == {"status": "PAUSED"}
    assert [item.fields for item in pending.intent_groups[0].items] == [
        {"campaign_id": "10", "campaign_name": "First campaign"}
    ]


def test_campaign_status_audit_detail_covers_partial_and_noop_results() -> None:
    entry = _writable_google_ads_entry()
    campaigns = [_campaign_reference(entry, "10"), _campaign_reference(entry, "20")]
    partial_result = {
        "resource_names": ["customers/111/campaigns/10"],
        "campaign_errors": [{"campaign_id": "20", "error_code": "CANNOT_MODIFY_REMOVED_CAMPAIGN"}],
    }

    detail = terminal_operation_detail(
        campaign_status_pending_operation_detail(entry, campaigns, "PAUSED"),
        mutation_ledger_double(partial_result),
    )

    assert audit_status(detail) == AuditStatus.PARTIAL
    assert [outcome.status for outcome in detail.outcome_groups[0].outcomes] == [
        "applied",
        "failed",
    ]
    assert (
        detail.outcome_groups[0].outcomes[0].effects[0].external_ref == "customers/111/campaigns/10"
    )
    assert detail.outcome_groups[0].outcomes[1].effects[0].error_code == (
        "CANNOT_MODIFY_REMOVED_CAMPAIGN"
    )
    assert detail.intent_counts.model_dump() == {
        "applied": 1,
        "skipped": 0,
        "failed": 1,
        "unverified": 0,
    }

    failed_result = {
        "resource_names": [],
        "campaign_errors": [{"campaign_id": "10", "error_code": "NOT_ALLOWED"}],
    }
    failed = terminal_operation_detail(
        campaign_status_pending_operation_detail(entry, [campaigns[0]], "PAUSED"),
        mutation_ledger_double(failed_result),
    )
    assert audit_status(failed) == AuditStatus.FAILURE


async def test_campaign_status_durable_audit_failures_are_not_success(monkeypatch) -> None:
    entry = _writable_google_ads_entry()
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(entry,)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name="google_ads_update_campaign_status",
    )
    campaign = _campaign_reference(entry, "10")
    provider_client = AsyncMock(return_value=object())
    verifier = AsyncMock()
    provider_update = AsyncMock(
        return_value=mutation_ledger_double(
            {
                "resource_names": ["customers/111/campaigns/10"],
                "campaign_errors": [],
            }
        )
    )
    audit = AsyncMock(side_effect=RuntimeError("pending audit unavailable"))
    monkeypatch.setattr(
        "integrations.google_ads.tools.update_campaign_status.google_ads_client",
        provider_client,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.update_campaign_status.verify_campaigns",
        verifier,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.update_campaign_status.update_campaign_status",
        provider_update,
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )

    pending_failure = await google_ads_update_campaign_status(ctx, [campaign], "PAUSED")

    assert pending_failure["results"][0]["status"] == "error"
    provider_client.assert_not_awaited()
    verifier.assert_not_awaited()
    provider_update.assert_not_awaited()

    pending_event_id = uuid4()
    audit.side_effect = [pending_event_id, RuntimeError("terminal audit unavailable")]
    audit.reset_mock()

    terminal_failure = await google_ads_update_campaign_status(ctx, [campaign], "PAUSED")

    assert terminal_failure["results"][0]["status"] == "error"
    assert "terminal audit unavailable" in terminal_failure["results"][0]["error_message"]
    provider_update.assert_awaited_once()
    assert [call.kwargs["status"] for call in audit.await_args_list] == [
        AuditStatus.PENDING,
        AuditStatus.SUCCESS,
    ]
    assert audit.await_args_list[1].kwargs["related_event_id"] == pending_event_id


async def test_campaign_verification_can_ignore_removed_campaigns() -> None:
    entry = _writable_google_ads_entry()
    client = AsyncMock()
    client.post.return_value = {"results": [{"campaign": {"id": "10", "status": "REMOVED"}}]}

    with pytest.raises(ModelRetry, match="campaign is unavailable"):
        await verify_campaigns(
            client,
            entry=entry,
            campaign_ids=["10"],
            ignore_removed=True,
        )

    assert "campaign.status != 'REMOVED'" in client.post.await_args.kwargs["json"]["query"]

    await verify_campaigns(
        client,
        entry=entry,
        campaign_ids=["10"],
        ignore_removed=False,
    )

    assert "campaign.status != 'REMOVED'" not in client.post.await_args.kwargs["json"]["query"]


async def test_execution_verifiers_share_canonical_operation_layer(monkeypatch) -> None:
    entry = _writable_google_ads_entry()
    client = AsyncMock()
    campaign_operation = AsyncMock(
        return_value=[
            {"id": "10", "status": "ENABLED"},
            {"id": "20", "status": "ENABLED"},
        ]
    )
    ad_group_operation = AsyncMock(
        return_value=[
            {"adGroup": {"id": "30"}, "campaign": {"name": "Brand"}},
        ]
    )
    shared_set_operation = AsyncMock(return_value=[{"id": "50"}])
    monkeypatch.setattr(
        "integrations.google_ads.tools.verifiers.campaign.list_campaigns",
        campaign_operation,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.verifiers.ad_group.list_ad_groups",
        ad_group_operation,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.verifiers.shared_set.list_shared_sets",
        shared_set_operation,
    )

    await verify_campaigns(
        client,
        entry=entry,
        campaign_ids=["20", "10", "20"],
        ignore_removed=True,
    )
    await verify_ad_groups(client, entry=entry, ad_group_ids=["30"])
    await verify_shared_sets(client, entry=entry, shared_set_ids=["50"])

    assert campaign_operation.await_args.kwargs["campaign_ids"] == ("10", "20")
    assert campaign_operation.await_args.kwargs["exclude_removed"] is True
    assert ad_group_operation.await_args.kwargs["ad_group_ids"] == ("30",)
    assert shared_set_operation.await_args.kwargs == {
        "customer_id": "111",
        "login_customer_id": "999",
        "shared_set_type": "NEGATIVE_KEYWORDS",
        "shared_set_ids": ("50",),
        "limit": 1,
    }

    campaign_operation.return_value = [{"id": "10", "status": "ENABLED"}]
    with pytest.raises(ModelRetry, match="campaign is unavailable"):
        await verify_campaigns(
            client,
            entry=entry,
            campaign_ids=["10", "20"],
            ignore_removed=True,
        )

    calls_before_invalid = shared_set_operation.await_count
    with pytest.raises(ModelRetry, match="list is unavailable"):
        await verify_shared_sets(client, entry=entry, shared_set_ids=["not-digits"])
    assert shared_set_operation.await_count == calls_before_invalid


async def test_campaign_update_fails_closed_when_pre_mutation_lookup_is_stale(
    monkeypatch,
) -> None:
    entry = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="google_ads",
        resource_type="google_ads_account",
        external_id="111",
        display_name="Ads account",
        connection_id=uuid4(),
        connection_label="Agency",
        connection_status="active",
        write_allowed=True,
        permissions_metadata={"login_customer_id": "999"},
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(entry,)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name="google_ads_update_campaign_status",
        tool_call_id="call-denied",
    )
    client = AsyncMock()
    client.post.return_value = {"results": [{"campaign": {"id": "10", "name": "Still available"}}]}
    provider_update = AsyncMock()

    async def passthrough_audit(_ctx, _entry, **kwargs):
        return (await kwargs["execute"]()).value

    monkeypatch.setattr(
        "integrations.google_ads.tools.update_campaign_status.google_ads_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.update_campaign_status.update_campaign_status",
        provider_update,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.update_campaign_status.run_audited_integration_operation",
        passthrough_audit,
    )

    result = await google_ads_update_campaign_status(
        ctx,
        [
            GoogleAdsCampaignReference(
                customer_id=entry.external_id,
                campaign_id="10",
                label="Still available",
            ),
            GoogleAdsCampaignReference(
                customer_id=entry.external_id,
                campaign_id="20",
                label="Deleted before approval",
            ),
        ],
        "PAUSED",
    )

    assert result["results"][0]["status"] == "error"
    assert result["results"][0]["error_code"] == "ModelRetry"
    assert "campaign is unavailable" in result["results"][0]["error_message"]
    provider_update.assert_not_awaited()


async def test_negative_list_campaign_links_reject_cross_account_references(
    monkeypatch,
) -> None:
    ctx = SimpleNamespace(deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=())))
    provider_client = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.link_negative_keyword_list.google_ads_client",
        provider_client,
    )

    with pytest.raises(ModelRetry, match="must belong to the same Google Ads account"):
        await google_ads_link_negative_keyword_list(
            ctx,
            GoogleAdsSharedSetReference(
                customer_id="111",
                shared_set_id="50",
                label="Brand Protection",
            ),
            [
                GoogleAdsCampaignReference(
                    customer_id="222",
                    campaign_id="10",
                    label="Search",
                )
            ],
            "LINK",
        )

    provider_client.assert_not_awaited()


@pytest.mark.parametrize(
    ("shared_sets", "campaign_payload", "message"),
    [
        ([], None, "list is unavailable"),
        ([{"id": "50"}], {"results": []}, "campaign is unavailable"),
        (
            [{"id": "50"}],
            {"results": [{"campaign": {"id": "10", "status": "REMOVED"}}]},
            "campaign is unavailable",
        ),
    ],
)
async def test_negative_list_campaign_links_fail_closed_for_stale_references(
    monkeypatch,
    shared_sets,
    campaign_payload,
    message,
) -> None:
    entry = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="google_ads",
        resource_type="google_ads_account",
        external_id="111",
        display_name="Ads account",
        connection_id=uuid4(),
        connection_label="Agency",
        connection_status="active",
        write_allowed=True,
        permissions_metadata={"login_customer_id": "999"},
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(entry,))),
        tool_name="google_ads_link_negative_keyword_list",
    )
    client = AsyncMock()
    if campaign_payload is not None:
        client.post.return_value = campaign_payload
    provider_link = AsyncMock()

    async def passthrough_audit(_ctx, _entry, **kwargs):
        return (await kwargs["execute"]()).value

    monkeypatch.setattr(
        "integrations.google_ads.tools.link_negative_keyword_list.google_ads_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.verifiers.shared_set.list_shared_sets",
        AsyncMock(return_value=shared_sets),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.link_negative_keyword_list.link_negative_keyword_list",
        provider_link,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.link_negative_keyword_list.run_audited_integration_operation",
        passthrough_audit,
    )

    result = await google_ads_link_negative_keyword_list(
        ctx,
        GoogleAdsSharedSetReference(
            customer_id=entry.external_id,
            shared_set_id="50",
            label="Brand Protection",
        ),
        [
            GoogleAdsCampaignReference(
                customer_id=entry.external_id,
                campaign_id="10",
                label="Search",
            )
        ],
        "LINK",
    )

    assert result["results"][0]["error_code"] == "ModelRetry"
    assert message in result["results"][0]["error_message"]
    provider_link.assert_not_awaited()


async def test_negative_list_campaign_links_reverify_and_mutate_one_account(
    monkeypatch,
) -> None:
    entry = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="google_ads",
        resource_type="google_ads_account",
        external_id="111",
        display_name="Ads account",
        connection_id=uuid4(),
        connection_label="Agency",
        connection_status="active",
        write_allowed=True,
        permissions_metadata={"login_customer_id": "999"},
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(entry,))),
        tool_name="google_ads_link_negative_keyword_list",
    )
    client = AsyncMock()
    client.post.return_value = {
        "results": [
            {"campaign": {"id": "10"}},
            {"campaign": {"id": "20"}},
            {"campaign": {"id": "30"}},
        ]
    }
    provider_link = AsyncMock(
        return_value=mutation_ledger_double(
            {
                "resource_names": ["customers/111/campaignSharedSets/10~50"],
                "skipped_existing": ["20"],
                "campaign_errors": [
                    {
                        "campaign_id": "30",
                        "message": "Campaign is removed",
                        "error_code": "CAMPAIGN_REMOVED",
                    }
                ],
            }
        )
    )
    audited_kwargs: dict[str, Any] = {}

    async def passthrough_audit(_ctx, _entry, **kwargs):
        audited_kwargs.update(kwargs)
        outcome = await kwargs["execute"]()
        audited_kwargs["outcome"] = outcome
        return outcome.value

    monkeypatch.setattr(
        "integrations.google_ads.tools.link_negative_keyword_list.google_ads_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.verifiers.shared_set.list_shared_sets",
        AsyncMock(return_value=[{"id": "50"}]),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.link_negative_keyword_list.link_negative_keyword_list",
        provider_link,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.link_negative_keyword_list.run_audited_integration_operation",
        passthrough_audit,
    )

    result = await google_ads_link_negative_keyword_list(
        ctx,
        GoogleAdsSharedSetReference(
            customer_id=entry.external_id,
            shared_set_id="50",
            label="Brand Protection",
            member_count=17,
        ),
        [
            GoogleAdsCampaignReference(
                customer_id=entry.external_id,
                campaign_id="20",
                label="Shopping",
            ),
            GoogleAdsCampaignReference(
                customer_id=entry.external_id,
                campaign_id="10",
                label="Search",
            ),
            GoogleAdsCampaignReference(
                customer_id=entry.external_id,
                campaign_id="30",
                label="Legacy",
            ),
        ],
        "LINK",
    )

    assert result["results"][0]["status"] == "success"
    assert provider_link.await_args.kwargs == {
        "customer_id": "111",
        "login_customer_id": "999",
        "shared_set_id": "50",
        "campaign_ids": ["10", "20", "30"],
        "action": "LINK",
    }
    assert result["results"][0]["data"] == {
        "action": "LINK",
        "negative_list": {
            "reference": GoogleAdsSharedSetReference(
                customer_id="111",
                shared_set_id="50",
                label="Brand Protection",
                member_count=17,
            ),
            "name": "Brand Protection",
            "member_count": 17,
        },
        "campaigns": [
            {
                "campaign_id": "20",
                "campaign_name": "Shopping",
                "outcome": "already_linked",
                "external_ref": None,
            },
            {
                "campaign_id": "10",
                "campaign_name": "Search",
                "outcome": "linked",
                "external_ref": "customers/111/campaignSharedSets/10~50",
            },
            {
                "campaign_id": "30",
                "campaign_name": "Legacy",
                "outcome": "failed",
                "external_ref": None,
                "message": "Campaign is removed",
                "error_code": "CAMPAIGN_REMOVED",
            },
        ],
    }
    outcome = audited_kwargs["outcome"]
    assert outcome.external_ref == "customers/111/campaignSharedSets/10~50"
    detail = outcome.operation_detail
    assert detail is not None
    assert (
        detail.outcome_groups[0].outcomes[1].effects[0].external_ref
        == "customers/111/campaignSharedSets/10~50"
    )


def test_negative_list_campaign_link_result_uses_unlink_outcomes() -> None:
    result = _campaign_link_result(
        GoogleAdsSharedSetReference(
            customer_id="111",
            shared_set_id="50",
            label="Brand Protection",
        ),
        [
            GoogleAdsCampaignReference(
                customer_id="111",
                campaign_id="10",
                label="Search",
            ),
            GoogleAdsCampaignReference(
                customer_id="111",
                campaign_id="20",
                label="Shopping",
            ),
            GoogleAdsCampaignReference(
                customer_id="111",
                campaign_id="30",
                label="Legacy",
            ),
        ],
        "UNLINK",
        {
            "resource_names": ["customers/111/campaignSharedSets/10~50"],
            "not_found": ["20"],
            "campaign_errors": [
                {
                    "campaign_id": "30",
                    "message": "Campaign is removed",
                    "error_code": "CAMPAIGN_REMOVED",
                }
            ],
        },
    )

    assert [campaign["outcome"] for campaign in result["campaigns"]] == [
        "unlinked",
        "not_linked",
        "failed",
    ]
    assert result["campaigns"][0]["external_ref"] == "customers/111/campaignSharedSets/10~50"


def test_negative_list_campaign_link_result_rejects_contradictory_accounting() -> None:
    negative_list = GoogleAdsSharedSetReference(
        customer_id="111",
        shared_set_id="50",
        label="Brand Protection",
    )
    campaigns = [
        GoogleAdsCampaignReference(
            customer_id="111",
            campaign_id="10",
            label="Search",
        ),
        GoogleAdsCampaignReference(
            customer_id="111",
            campaign_id="20",
            label="Shopping",
        ),
    ]
    contradictory_results = [
        {
            "resource_names": ["customers/111/campaignSharedSets/10~50"],
            "skipped_existing": ["10", "20"],
            "campaign_errors": [],
        },
        {
            "resource_names": ["customers/111/campaignSharedSets/10~50"],
            "skipped_existing": [],
            "campaign_errors": [],
        },
    ]

    for provider_result in contradictory_results:
        with pytest.raises(ValueError, match="contradictory campaign link accounting"):
            _campaign_link_result(
                negative_list,
                campaigns,
                "LINK",
                provider_result,
            )


async def test_negative_list_campaign_links_audit_write_denial_before_provider(
    monkeypatch,
) -> None:
    entry = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="google_ads",
        resource_type="google_ads_account",
        external_id="111",
        display_name="Read-only account",
        connection_id=uuid4(),
        connection_label="Agency",
        connection_status="active",
        write_allowed=False,
        permissions_metadata={"login_customer_id": "999"},
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(entry,)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name="google_ads_link_negative_keyword_list",
        tool_call_id="call-denied",
    )
    provider_client = AsyncMock()
    audit = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.link_negative_keyword_list.google_ads_client",
        provider_client,
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )

    result = await google_ads_link_negative_keyword_list(
        ctx,
        GoogleAdsSharedSetReference(
            customer_id=entry.external_id,
            shared_set_id="50",
            label="Brand Protection",
        ),
        [
            GoogleAdsCampaignReference(
                customer_id=entry.external_id,
                campaign_id="10",
                label="Search",
            )
        ],
        "UNLINK",
    )

    assert result["results"][0]["error_code"] == "write_not_permitted"
    provider_client.assert_not_awaited()
    assert audit.await_args.kwargs["status"] == AuditStatus.FAILURE
    assert audit.await_args.kwargs["error_code"] == "write_not_permitted"
