"""Google Ads account-level negative-keyword tool contracts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import (
    ModelRetry,
)

from integrations.google_ads.references import (
    GoogleAdsSharedSetReference,
)
from integrations.google_ads.tools.add_negative_keywords import (
    google_ads_add_negative_keywords,
)
from integrations.google_ads.tools.remove_negative_keywords import (
    google_ads_remove_negative_keywords,
)
from integrations.google_ads.tools.schemas.negative_keyword import (
    NegativeKeywordEntry,
    NegativeKeywordRemovalEntry,
)
from services.audit_events import AuditStatus
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry
from tests.integrations.google_ads.support import mutation_ledger


async def test_add_negative_keywords_targets_one_account_and_uses_normalized_rows(
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
        tool_name="google_ads_add_negative_keywords",
    )
    client = AsyncMock()
    client.post.return_value = {"results": [{"sharedSet": {"id": "50"}}]}
    provider_add = AsyncMock(
        return_value=mutation_ledger(
            {
                "added": [
                    {
                        "text": "Brand Term",
                        "match_type": "EXACT",
                        "resource_name": "criteria/1",
                    }
                ],
                "skipped_existing": [{"text": "brand term", "match_type": "PHRASE"}],
                "keyword_errors": [],
            }
        )
    )

    async def passthrough_audit(_ctx, _entry, **kwargs):
        return (await kwargs["execute"]()).value

    monkeypatch.setattr(
        "integrations.google_ads.tools.add_negative_keywords.google_ads_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.add_negative_keywords.add_negative_keywords",
        provider_add,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.add_negative_keywords.run_audited_integration_operation",
        passthrough_audit,
    )

    result = await google_ads_add_negative_keywords(
        ctx,
        GoogleAdsSharedSetReference(
            customer_id=entry.external_id,
            shared_set_id="50",
            label="Brand Protection",
        ),
        [
            NegativeKeywordEntry(text="  Brand   Term ", match_type="EXACT"),
            NegativeKeywordEntry(text="brand term", match_type="EXACT"),
            NegativeKeywordEntry(text="brand term", match_type="PHRASE"),
        ],
    )

    assert result.return_value["results"][0]["status"] == "success"
    assert result.metadata["public_result"]["results"][0]["data"]["samples"] == {
        "added": [
            {
                "text": "Brand Term",
                "match_type": "EXACT",
                "resource_name": "criteria/1",
            }
        ],
        "skipped_existing": [{"text": "brand term", "match_type": "PHRASE"}],
        "failed": [],
    }
    assert provider_add.await_args.kwargs["shared_set_id"] == "50"
    assert provider_add.await_args.kwargs["keywords"] == [
        {"text": "Brand Term", "match_type": "EXACT"},
        {"text": "brand term", "match_type": "PHRASE"},
    ]


@pytest.mark.parametrize(
    ("provider_result", "requested", "expected_status", "expected_counts"),
    [
        pytest.param(
            {
                "added": [],
                "skipped_existing": [{"text": "existing", "match_type": "EXACT"}],
                "keyword_errors": [],
            },
            [{"text": "existing", "match_type": "EXACT"}],
            AuditStatus.SUCCESS,
            {"applied": 0, "skipped": 1, "failed": 0, "unverified": 0},
            id="all-skipped-no-op",
        ),
        pytest.param(
            {
                "added": [
                    {
                        "text": "accepted",
                        "match_type": "EXACT",
                        "resource_name": "customers/111/sharedCriteria/50~1",
                    }
                ],
                "skipped_existing": [],
                "keyword_errors": [
                    {
                        "scope": "keyword",
                        "text": "rejected",
                        "match_type": "PHRASE",
                        "message": "invalid",
                        "error_code": "INVALID_KEYWORD_TEXT",
                    }
                ],
            },
            [
                {"text": "accepted", "match_type": "EXACT"},
                {"text": "rejected", "match_type": "PHRASE"},
            ],
            AuditStatus.PARTIAL,
            {"applied": 1, "skipped": 0, "failed": 1, "unverified": 0},
            id="mixed-partial-success",
        ),
    ],
)
async def test_add_negative_keywords_classifies_audit_outcome(
    monkeypatch,
    provider_result,
    requested: list[dict[str, str]],
    expected_status: AuditStatus,
    expected_counts: dict[str, int],
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
        tool_name="google_ads_add_negative_keywords",
    )
    client = AsyncMock()
    client.post.return_value = {"results": [{"sharedSet": {"id": "50"}}]}
    audit = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.add_negative_keywords.google_ads_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.add_negative_keywords.add_negative_keywords",
        AsyncMock(return_value=mutation_ledger(provider_result)),
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )

    await google_ads_add_negative_keywords(
        ctx,
        GoogleAdsSharedSetReference(
            customer_id=entry.external_id,
            shared_set_id="50",
            label="Brand Protection",
        ),
        [NegativeKeywordEntry(**item) for item in requested],
    )

    assert audit.await_count == 2
    pending_kwargs, audit_kwargs = [call.kwargs for call in audit.await_args_list]
    assert pending_kwargs["status"] == AuditStatus.PENDING
    assert pending_kwargs["raise_on_error"] is True
    assert audit_kwargs["status"] == expected_status
    assert audit_kwargs["raise_on_error"] is True
    detail = audit_kwargs["operation_detail"].model_dump(mode="json")
    assert detail["intent_counts"] == expected_counts
    assert sum(len(group["outcomes"]) for group in detail["outcome_groups"]) == len(requested)


async def test_add_negative_keywords_fails_closed_when_list_is_missing(monkeypatch) -> None:
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
        tool_name="google_ads_add_negative_keywords",
    )
    client = AsyncMock()
    client.post.return_value = {"results": []}
    provider_add = AsyncMock()

    async def passthrough_audit(_ctx, _entry, **kwargs):
        return (await kwargs["execute"]()).value

    monkeypatch.setattr(
        "integrations.google_ads.tools.add_negative_keywords.google_ads_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.add_negative_keywords.add_negative_keywords",
        provider_add,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.add_negative_keywords.run_audited_integration_operation",
        passthrough_audit,
    )

    result = await google_ads_add_negative_keywords(
        ctx,
        GoogleAdsSharedSetReference(
            customer_id=entry.external_id,
            shared_set_id="50",
            label="Removed list",
        ),
        [NegativeKeywordEntry(text="term", match_type="EXACT")],
    )

    assert result.return_value["results"][0]["error_code"] == "ModelRetry"
    assert "list is unavailable" in result.return_value["results"][0]["error_message"]
    provider_add.assert_not_awaited()


async def test_add_negative_keywords_rejects_target_outside_active_context() -> None:
    active = ResolvedContextEntry(
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
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(active,)))
    )

    with pytest.raises(ModelRetry, match="no longer in the active integration context"):
        await google_ads_add_negative_keywords(
            ctx,
            GoogleAdsSharedSetReference(
                customer_id="999",
                shared_set_id="50",
                label="Other account list",
            ),
            [NegativeKeywordEntry(text="term", match_type="EXACT")],
        )


async def test_remove_negative_keywords_normalizes_any_and_targets_one_account(
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
        tool_name="google_ads_remove_negative_keywords",
    )
    client = AsyncMock()
    client.post.return_value = {"results": [{"sharedSet": {"id": "50"}}]}
    provider_remove = AsyncMock(
        return_value={
            "removed": [],
            "resource_names": [],
            "not_found": [{"text": "Brand Term", "match_type": "ANY"}],
            "keyword_errors": [],
        }
    )

    async def passthrough_audit(_ctx, _entry, **kwargs):
        return (await kwargs["execute"]()).value

    monkeypatch.setattr(
        "integrations.google_ads.tools.remove_negative_keywords.google_ads_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.remove_negative_keywords.remove_negative_keywords",
        provider_remove,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.remove_negative_keywords.run_audited_integration_operation",
        passthrough_audit,
    )

    await google_ads_remove_negative_keywords(
        ctx,
        GoogleAdsSharedSetReference(
            customer_id=entry.external_id,
            shared_set_id="50",
            label="Brand Protection",
        ),
        [
            NegativeKeywordRemovalEntry(text="Brand Term", match_type="EXACT"),
            NegativeKeywordRemovalEntry(text=" brand   term ", match_type="ANY"),
            NegativeKeywordRemovalEntry(text="brand term", match_type="PHRASE"),
        ],
    )

    assert provider_remove.await_args.kwargs["keywords"] == [
        {"text": "brand term", "match_type": "ANY"}
    ]
