# apps/api/integrations/meta_ads/operations/enrich_custom_conversions.py

"""Resolve custom action names once within an account report's limits."""

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
from ..tools.schemas.custom_conversions import CUSTOM_CONVERSIONS_MAX_ROWS
from ..tools.schemas.insights import MetaAdsInsightsRow
from .list_custom_conversions import list_custom_conversions


async def enrich_custom_conversions(
    client: MetaAdsClient,
    *,
    account_id: str,
    rows: list[MetaAdsInsightsRow],
    budget: ReportResultBudget,
) -> list[str]:
    actions = [
        action
        for row in rows
        for values in row.actions.values()
        for action in values
        if re.fullmatch(r"offsite_conversion\.custom\.[0-9]{1,128}", action.action_type)
    ]
    if not actions:
        return []
    for action in actions:
        action.custom_conversion_id = action.action_type.rsplit(".", 1)[1]
    notes: list[str] = []
    names: dict[str, str | None] = {}
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
