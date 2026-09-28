"""Google Ads tool execution, approval, result, and audit contracts."""

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
)
from integrations.google_ads.tools.create_negative_keyword_list import (
    google_ads_create_negative_keyword_list,
)
from integrations.google_ads.tools.get_report_field import google_ads_get_report_field
from integrations.google_ads.tools.link_negative_keyword_list import (
    _campaign_link_result,
    google_ads_link_negative_keyword_list,
)
from integrations.google_ads.tools.list_report_fields import google_ads_list_report_fields
from integrations.google_ads.tools.schemas.negative_keyword import (
    NegativeKeywordEntry,
    NegativeKeywordRemovalEntry,
)
from integrations.google_ads.tools.update_campaign_status import (
    google_ads_update_campaign_status,
)
from integrations.google_ads.tools.utils import (
    normalize_negative_keywords,
)
from integrations.google_ads.tools.utils.mutation_evidence import (
    terminal_operation_detail,
)
from services.audit_events import AuditStatus
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)
from tests.integrations.google_ads.support import (
    _writable_google_ads_entry,
    mutation_ledger,
)


def _read_entry(external_id: str = "111") -> ResolvedContextEntry:
    return ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="google_ads",
        resource_type="google_ads_account",
        external_id=external_id,
        display_name=f"Ads account {external_id}",
        connection_id=uuid4(),
        connection_label="Agency",
        connection_status="active",
        write_allowed=False,
        permissions_metadata={"login_customer_id": "999"},
    )


def _read_ctx(*entries: ResolvedContextEntry, tool_name: str):
    return SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=entries),
            workspace=SimpleNamespace(id=uuid4()),
            user=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4(), user_id=uuid4()),
        ),
        tool_name=tool_name,
        tool_call_id="call-google-ads-fields",
    )


async def test_report_field_tools_require_compatible_active_context() -> None:
    ctx = _read_ctx(tool_name="google_ads_list_report_fields")

    with pytest.raises(ModelRetry, match="includes Google Ads"):
        await google_ads_list_report_fields(ctx, "campaign")

    ctx.tool_name = "google_ads_get_report_field"
    with pytest.raises(ModelRetry, match="includes Google Ads"):
        await google_ads_get_report_field(ctx, ["campaign.id"])


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
        mutation_ledger(
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


def test_negative_keyword_entry_rejects_81_normalized_characters() -> None:
    with pytest.raises(ValidationError, match="at most 80 characters"):
        NegativeKeywordEntry(text=f"  {'x' * 81}  ", match_type="EXACT")


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
        side_effect=lambda _client, **kwargs: mutation_ledger(
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
