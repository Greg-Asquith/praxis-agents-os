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

from ..schemas.activities import MetaAdsActivitiesData, MetaAdsActivitiesInput
from ..schemas.assets import MetaAdsAssetKind, MetaAdsAssetsData
from ..schemas.conversions import MetaAdsConversionsData
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


def activities_audit_detail(
    account_id: str, request: MetaAdsActivitiesInput, result: MetaAdsActivitiesData
) -> TerminalIntegrationOperationDetail:
    return _read_audit_detail(
        account_id,
        "activities",
        {
            "since": request.since.isoformat(),
            "until": request.until.isoformat(),
            "object_id_count": len(request.object_ids or ()),
            "event_count": result.event_count,
        },
    )


def assets_audit_detail(
    account_id: str, kinds: tuple[MetaAdsAssetKind, ...], result: MetaAdsAssetsData
) -> TerminalIntegrationOperationDetail:
    fields: dict[str, Any] = {"kinds": list(kinds)}
    for kind in kinds:
        fields[f"{kind}_count"] = len(getattr(result, kind))
    return _read_audit_detail(account_id, "assets", fields)


def conversions_audit_detail(
    account_id: str, result: MetaAdsConversionsData
) -> TerminalIntegrationOperationDetail:
    events = sum(item.kind == "custom_event" for item in result.conversions)
    return _read_audit_detail(
        account_id,
        "conversions",
        {"conversion_count": result.conversion_count, "custom_event_count": events},
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
