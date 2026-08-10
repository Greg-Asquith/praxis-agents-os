"""Contracts for provider-neutral integration operation audit detail."""

import pytest
from pydantic import ValidationError

from services.audit_events import (
    IntegrationOperationChange,
    IntegrationOperationCounts,
    IntegrationOperationDetail,
    IntegrationOperationTarget,
)


def test_integration_operation_detail_accepts_nested_provider_fields() -> None:
    detail = IntegrationOperationDetail(
        target=IntegrationOperationTarget(
            entity_type="campaign",
            external_id="campaign-1",
            attributes={"channel": "search"},
        ),
        changes=[
            IntegrationOperationChange(
                action="update",
                entity_type="campaign_targeting",
                external_ref="campaigns/1",
                fields={
                    "locations": ["GB", "IE"],
                    "bid_adjustments": {"mobile": -0.2, "desktop": 0.1},
                },
            )
        ],
        counts=IntegrationOperationCounts(applied=1, skipped=0, failed=0),
    )

    assert detail.changes[0].fields["locations"] == ["GB", "IE"]


def test_integration_operation_detail_rejects_unbounded_payloads() -> None:
    with pytest.raises(ValidationError, match="1,000,000-byte limit"):
        IntegrationOperationDetail(
            target=IntegrationOperationTarget(
                entity_type="campaign",
                external_id="campaign-1",
            ),
            changes=[
                IntegrationOperationChange(
                    action="update",
                    entity_type="campaign",
                    fields={"provider_payload": "x" * 1_000_000},
                )
            ],
            counts=IntegrationOperationCounts(applied=1, skipped=0, failed=0),
        )
