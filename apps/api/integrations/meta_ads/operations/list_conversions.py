# apps/api/integrations/meta_ads/operations/list_conversions.py

"""List custom conversions and custom events with recent counts for one account."""

from typing import Any

from pydantic import ValidationError

from core.exceptions.integration import (
    IntegrationConnectionError,
    IntegrationNotFoundError,
    IntegrationPermissionError,
    IntegrationReportTooLargeError,
    IntegrationValidationError,
)
from services.integrations.report_results import ReportResultBudget

from ..client import MetaAdsClient, ad_account_path
from ..tools.schemas.conversions import (
    CUSTOM_EVENT_PREFIX,
    MetaAdsConversion,
    MetaAdsConversionsData,
)
from .list_custom_conversions import list_custom_conversions
from .paging import read_pages
from .values import invalid_response, iso_date, numeric_value

_OPERATION = "list_conversions"
# Custom events exist only as named Insights conversions, so discovery reads recent delivery.
_RECENT_PARAMS = {
    "fields": "actions,conversions,date_start,date_stop",
    "level": "account",
    "date_preset": "last_90d",
    "use_unified_attribution_setting": "true",
}
_SOURCE_ERRORS = (
    IntegrationConnectionError,
    IntegrationPermissionError,
    IntegrationNotFoundError,
    IntegrationValidationError,
)


async def list_conversions(
    client: MetaAdsClient,
    *,
    account_id: str,
    limit: int,
    budget: ReportResultBudget,
) -> MetaAdsConversionsData:
    # Definitions and recent events are separate edges, so either can fail alone.
    definitions_error: Exception | None = None
    try:
        result = await list_custom_conversions(
            client, account_id=account_id, limit=limit, budget=budget
        )
    except IntegrationReportTooLargeError:
        raise
    except _SOURCE_ERRORS as error:
        definitions_error = error
        result = MetaAdsConversionsData(
            conversions=[],
            conversion_count=0,
            truncated=False,
            notes=["Custom conversion definitions are unavailable for this account."],
        )
    try:
        rows, _ = await read_pages(
            client,
            path=f"{ad_account_path(account_id)}/insights",
            account_id=account_id,
            params=_RECENT_PARAMS,
            limit=1,
            budget=budget,
            operation=_OPERATION,
        )
        if rows:
            return _with_recent(result, rows[0])
        note = "The account had no delivery in the last 90 days, so no custom events are listed."
    except IntegrationReportTooLargeError:
        raise
    except _SOURCE_ERRORS:
        if definitions_error is not None:
            raise definitions_error from None
        note = "Custom events and recent conversion counts are unavailable for this account."
    return result.model_copy(update={"notes": [*result.notes, note]})


def _with_recent(result: MetaAdsConversionsData, row: dict[str, Any]) -> MetaAdsConversionsData:
    counts = _action_values(row.get("actions"))
    events = sorted(
        (action_type, value)
        for action_type, value in _action_values(row.get("conversions")).items()
        if action_type.startswith(CUSTOM_EVENT_PREFIX) and action_type != CUSTOM_EVENT_PREFIX
    )
    try:
        conversions = [
            *(
                item.model_copy(update={"recent_conversions": counts.get(item.action_type)})
                for item in result.conversions
            ),
            *(
                MetaAdsConversion(
                    kind="custom_event",
                    action_type=action_type,
                    name=action_type.removeprefix(CUSTOM_EVENT_PREFIX),
                    recent_conversions=value,
                )
                for action_type, value in events
            ),
        ]
    except ValidationError:
        raise invalid_response(
            "Meta Ads returned invalid custom event names.", operation=_OPERATION
        ) from None
    return result.model_copy(
        update={
            "conversions": conversions,
            "conversion_count": len(conversions),
            "recent_since": iso_date(row.get("date_start"), operation=_OPERATION),
            "recent_until": iso_date(row.get("date_stop"), operation=_OPERATION),
        }
    )


def _action_values(value: Any) -> dict[str, float | None]:
    if value is None:
        return {}
    if not isinstance(value, list) or len(value) > 1000:
        raise invalid_response("Meta Ads returned invalid action values.", operation=_OPERATION)
    values: dict[str, float | None] = {}
    for item in value:
        action_type = item.get("action_type") if isinstance(item, dict) else None
        if not isinstance(action_type, str) or len(action_type) > 256:
            raise invalid_response(
                "Meta Ads returned an invalid action type.", operation=_OPERATION
            )
        values[action_type] = numeric_value(item.get("value"), operation=_OPERATION)
    return values
