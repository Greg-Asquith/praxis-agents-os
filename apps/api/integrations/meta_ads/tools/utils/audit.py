# apps/api/integrations/meta_ads/tools/utils/audit.py

"""Counts and request parameters for Meta Insights audit evidence."""

from services.audit_events import (
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    IntegrationOperationTarget,
    PendingIntegrationOperationDetail,
    TerminalIntegrationOperationDetail,
    terminal_applied_operation_detail,
)

from ..schemas.insights import MetaAdsInsightsData, MetaAdsInsightsInput


def insights_audit_detail(
    account_id: str, request: MetaAdsInsightsInput, result: MetaAdsInsightsData
) -> TerminalIntegrationOperationDetail:
    """Returns report parameters and counts without advertiser-authored text."""
    return terminal_applied_operation_detail(
        PendingIntegrationOperationDetail(
            target=IntegrationOperationTarget(entity_type="ad_account", external_id=account_id),
            intent_groups=[
                IntegrationOperationIntentGroup(
                    key="insights",
                    action="read",
                    entity_type="ad_account",
                    items=[
                        IntegrationOperationIntent(
                            fields={
                                "level": request.level,
                                "since": str(request.since),
                                "until": str(request.until),
                                "field_count": len(request.fields),
                                "breakdowns": list(request.breakdowns),
                                "attribution_mode": "explicit"
                                if request.attribution_windows
                                else "unified",
                                "mode": result.mode,
                                "row_count": result.row_count,
                            }
                        )
                    ],
                )
            ],
        )
    )
