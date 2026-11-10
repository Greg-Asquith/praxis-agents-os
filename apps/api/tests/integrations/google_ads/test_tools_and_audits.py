# apps/api/tests/integrations/google_ads/test_tools_and_audits.py

"""Google Ads tool execution, approval, result, and audit contracts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry

from integrations.google_ads.operations.mutation_outcomes import (
    GoogleAdsMutationProjection,
    build_mutation_ledger,
)
from integrations.google_ads.tools.get_report_field import google_ads_get_report_field
from integrations.google_ads.tools.list_report_fields import google_ads_list_report_fields
from integrations.google_ads.tools.schemas.negative_keywords import NegativeKeywordEntry
from integrations.google_ads.tools.utils.mutation_evidence import (
    google_ads_account_target,
    terminal_operation_detail,
)
from services.audit_events import (
    AuditStatus,
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    PendingIntegrationOperationDetail,
)
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)
from tests.integrations.google_ads.support import _writable_google_ads_entry


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
        tool_name="google_ads_update_negative_keywords",
    )
    entry = _writable_google_ads_entry()
    key = "customers/111/campaigns/10/negative/EXACT/brand"
    detail = PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key="campaign:keyword:add",
                action="add",
                entity_type="google_ads_campaign_negative_keyword",
                items=[IntegrationOperationIntent(fields={"object": key})],
            )
        ],
    )
    fields = {"object": key, "settings": "add"}
    terminal_detail = terminal_operation_detail(
        detail,
        build_mutation_ledger(
            family="negative_keywords",
            action="update",
            parent_fields=[fields],
            skipped_indices={},
            submitted=[(0, fields)],
            outcomes=[("applied", "customers/111/campaignCriteria/10~1", None, None)],
            projection=GoogleAdsMutationProjection(
                applied_key="updated", skipped_key="already_set", errors_key="errors"
            ),
        ),
        identity_keys=("object",),
    )
    execute.return_value = IntegrationAuditOutcome({"ok": True}, operation_detail=terminal_detail)
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_ads_update_negative_keywords",
            operation="update_negative_keywords",
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
            SimpleNamespace(tool_name="google_ads_update_negative_keywords"),  # type: ignore[arg-type]
            _writable_google_ads_entry(),
            tool_name="google_ads_update_negative_keywords",
            operation="update_negative_keywords",
            execute=execute,
        )

    execute.assert_not_awaited()


def test_negative_keyword_entry_normalizes_whitespace_before_length_validation() -> None:
    entry = NegativeKeywordEntry(
        text=f"   Brand{' ' * 81}Term   ",
        match_type="EXACT",
    )

    assert entry.text == "Brand Term"
