# apps/api/integrations/meta_ads/tools/utils/audit.py

"""Counts and request parameters for Meta read audit evidence."""

from typing import Any

from services.audit_events import (
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    IntegrationOperationTarget,
    PendingIntegrationOperationDetail,
    TerminalIntegrationOperationDetail,
    terminal_applied_operation_detail,
)

from ..schemas.custom_conversions import MetaAdsCustomConversionsData
from ..schemas.insights import MetaAdsInsightsData, MetaAdsInsightsInput
from ..schemas.objects import DEFAULT_STATUSES, MetaAdsObjectsData, MetaAdsObjectsInput


def _read_audit_detail(
    account_id: str, key: str, fields: dict[str, Any]
) -> TerminalIntegrationOperationDetail:
    """Builds read evidence from caller-selected counts and request parameters."""
    return terminal_applied_operation_detail(
        PendingIntegrationOperationDetail(
            target=IntegrationOperationTarget(entity_type="ad_account", external_id=account_id),
            intent_groups=[
                IntegrationOperationIntentGroup(
                    key=key,
                    action="read",
                    entity_type="ad_account",
                    items=[IntegrationOperationIntent(fields=fields)],
                )
            ],
        )
    )


def accounts_audit_detail(account_id: str) -> TerminalIntegrationOperationDetail:
    return _read_audit_detail(account_id, "accounts", {"account_count": 1})


def custom_conversions_audit_detail(
    account_id: str, result: MetaAdsCustomConversionsData
) -> TerminalIntegrationOperationDetail:
    return _read_audit_detail(
        account_id, "custom_conversions", {"conversion_count": result.conversion_count}
    )


def objects_audit_detail(
    account_id: str, request: MetaAdsObjectsInput, result: MetaAdsObjectsData
) -> TerminalIntegrationOperationDetail:
    return _read_audit_detail(
        account_id,
        "objects",
        {
            "object_type": request.object_type,
            "statuses": request.statuses or DEFAULT_STATUSES[request.object_type],
            "object_count": result.object_count,
        },
    )


def insights_audit_detail(
    account_id: str, request: MetaAdsInsightsInput, result: MetaAdsInsightsData
) -> TerminalIntegrationOperationDetail:
    """Returns report parameters and counts without advertiser-authored text."""
    return _read_audit_detail(
        account_id,
        "insights",
        {
            "level": request.level,
            "since": str(request.since),
            "until": str(request.until),
            "field_count": len(request.fields),
            "breakdowns": list(request.breakdowns),
            "attribution_mode": "explicit" if request.attribution_windows else "unified",
            "mode": result.mode,
            "row_count": result.row_count,
        },
    )
