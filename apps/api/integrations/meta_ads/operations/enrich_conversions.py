# apps/api/integrations/meta_ads/operations/enrich_conversions.py

"""Name custom events and resolve custom conversions within an account report's limits."""

import re

from core.exceptions.integration import (
    IntegrationConnectionError,
    IntegrationNotFoundError,
    IntegrationPermissionError,
    IntegrationReportTooLargeError,
    IntegrationValidationError,
)
from services.integrations.report_results import ReportResultBudget

from ..client import MetaAdsClient
from ..tools.schemas.conversions import (
    CUSTOM_CONVERSION_PREFIX,
    CUSTOM_CONVERSIONS_MAX_ROWS,
    CUSTOM_EVENT_PREFIX,
)
from ..tools.schemas.insights import MetaAdsInsightsAction, MetaAdsInsightsRow
from .list_custom_conversions import list_custom_conversions


async def enrich_conversion_names(
    client: MetaAdsClient,
    *,
    account_id: str,
    rows: list[MetaAdsInsightsRow],
    budget: ReportResultBudget,
) -> list[str]:
    actions = [action for row in rows for values in row.actions.values() for action in values]
    for action in actions:
        # Custom events carry their name in the action type, so they need no lookup.
        if action.action_type.startswith(CUSTOM_EVENT_PREFIX):
            action.custom_event_name = action.action_type.removeprefix(CUSTOM_EVENT_PREFIX) or None
    custom = [
        action
        for action in actions
        if re.fullmatch(rf"{re.escape(CUSTOM_CONVERSION_PREFIX)}[0-9]{{1,128}}", action.action_type)
    ]
    if not custom:
        return []
    return await _resolve_custom_conversions(client, account_id, custom, budget)


async def _resolve_custom_conversions(
    client: MetaAdsClient,
    account_id: str,
    actions: list[MetaAdsInsightsAction],
    budget: ReportResultBudget,
) -> list[str]:
    for action in actions:
        action.custom_conversion_id = action.action_type.rsplit(".", 1)[1]
    notes: list[str] = []
    names: dict[str | None, str | None] = {}
    try:
        metadata = await list_custom_conversions(
            client, account_id=account_id, limit=CUSTOM_CONVERSIONS_MAX_ROWS, budget=budget
        )
    except IntegrationReportTooLargeError:
        raise
    except (
        IntegrationConnectionError,
        IntegrationPermissionError,
        IntegrationNotFoundError,
        IntegrationValidationError,
    ):
        notes.append("Custom conversion metadata is unavailable for this account.")
    else:
        names = {item.id: item.name for item in metadata.conversions}
        notes.extend(metadata.notes)
    unresolved = set()
    for action in actions:
        name = names.get(action.custom_conversion_id)
        action.custom_conversion_name = name if name and name.strip() else None
        if action.custom_conversion_name is None:
            unresolved.add(action.custom_conversion_id)
    if unresolved:
        notes.append(
            f"Names remain unresolved for {len(unresolved)} custom conversions. "
            "Use their IDs; all reported metrics and attribution values are preserved."
        )
    return notes
