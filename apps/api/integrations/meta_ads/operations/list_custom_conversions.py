# apps/api/integrations/meta_ads/operations/list_custom_conversions.py

"""Read bounded custom conversion metadata for one selected account."""

from pydantic import ValidationError

from services.integrations.report_results import ReportResultBudget

from ..client import MetaAdsClient, ad_account_path
from ..tools.schemas.conversions import (
    CUSTOM_CONVERSION_PREFIX,
    CUSTOM_CONVERSIONS_MAX_ROWS,
    MetaAdsConversion,
    MetaAdsConversionsData,
)
from .paging import read_pages
from .values import bounded_string, invalid_response

_OPERATION = "list_custom_conversions"


async def list_custom_conversions(
    client: MetaAdsClient,
    *,
    account_id: str,
    limit: int = 100,
    budget: ReportResultBudget | None = None,
) -> MetaAdsConversionsData:
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= CUSTOM_CONVERSIONS_MAX_ROWS
    ):
        raise invalid_response(
            f"limit must be between 1 and {CUSTOM_CONVERSIONS_MAX_ROWS}.", operation=_OPERATION
        )
    rows, truncated = await read_pages(
        client,
        path=f"{ad_account_path(account_id)}/customconversions",
        account_id=account_id,
        params={"fields": "id,name,description,is_archived,is_unavailable"},
        limit=limit,
        budget=budget or ReportResultBudget("meta_ads", _OPERATION),
        operation=_OPERATION,
    )
    try:
        conversions = [
            MetaAdsConversion(
                kind="custom_conversion",
                action_type=f"{CUSTOM_CONVERSION_PREFIX}{row.get('id')}",
                id=row.get("id"),
                name=bounded_string(row.get("name"), operation=_OPERATION),
                description=bounded_string(row.get("description"), operation=_OPERATION),
                is_archived=row.get("is_archived"),
                is_unavailable=row.get("is_unavailable"),
            )
            for row in rows
        ]
    except ValidationError:
        raise invalid_response(
            "Meta Ads returned invalid custom conversion metadata.", operation=_OPERATION
        ) from None
    return MetaAdsConversionsData(
        conversions=conversions,
        conversion_count=len(conversions),
        truncated=truncated,
        notes=["Custom conversion discovery reached its row or pagination limit."]
        if truncated
        else [],
    )
