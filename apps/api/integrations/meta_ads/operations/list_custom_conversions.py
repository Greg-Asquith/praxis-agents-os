# apps/api/integrations/meta_ads/operations/list_custom_conversions.py

"""Read bounded custom conversion metadata for one selected account."""

from pydantic import ValidationError

from core.exceptions.integration import IntegrationValidationError
from services.integrations.report_results import ReportResultBudget

from ..client import MetaAdsClient, ad_account_path
from ..tools.schemas.custom_conversions import (
    CUSTOM_CONVERSIONS_MAX_ROWS,
    MetaAdsCustomConversion,
    MetaAdsCustomConversionsData,
)
from .paging import read_pages
from .values import bounded_string

_OPERATION = "list_custom_conversions"


async def list_custom_conversions(
    client: MetaAdsClient,
    *,
    account_id: str,
    limit: int = 100,
    budget: ReportResultBudget | None = None,
) -> MetaAdsCustomConversionsData:
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= CUSTOM_CONVERSIONS_MAX_ROWS
    ):
        raise IntegrationValidationError(
            f"limit must be between 1 and {CUSTOM_CONVERSIONS_MAX_ROWS}.",
            provider_key="meta_ads",
            operation=_OPERATION,
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
            MetaAdsCustomConversion(
                id=row.get("id"),
                name=bounded_string(row.get("name"), operation=_OPERATION),
                description=bounded_string(row.get("description"), operation=_OPERATION),
                is_archived=row.get("is_archived"),
                is_unavailable=row.get("is_unavailable"),
            )
            for row in rows
        ]
    except ValidationError:
        raise IntegrationValidationError(
            "Meta Ads returned invalid custom conversion metadata.",
            provider_key="meta_ads",
            operation=_OPERATION,
        ) from None
    return MetaAdsCustomConversionsData(
        conversions=conversions,
        conversion_count=len(conversions),
        truncated=truncated,
        notes=["Custom conversion discovery reached its row or pagination limit."]
        if truncated
        else [],
    )
