# apps/api/integrations/meta_ads/operations/paging.py

"""Read bounded account edges without following provider-supplied URLs."""

from collections.abc import Callable
from typing import Any

from services.integrations.http import IntegrationRequestPolicy
from services.integrations.report_results import ReportResultBudget

from ..client import MetaAdsClient, next_cursor
from ..throttle import ensure_account_available
from .values import invalid_response


async def read_pages(
    client: MetaAdsClient,
    *,
    path: str,
    account_id: str,
    params: dict[str, Any],
    limit: int,
    budget: ReportResultBudget,
    operation: str,
    page_size: int = 100,
    max_pages: int = 10,
    include: Callable[[dict[str, Any]], bool] | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    # Only included rows count towards the limit, so filtered reads request full pages.
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    query = dict(params)
    for _ in range(max_pages):
        ensure_account_available(account_id, operation=operation)
        query["limit"] = page_size if include else min(limit - len(rows), page_size)
        payload = await client.graph_get(
            path,
            params=dict(query),
            operation=operation,
            policy=IntegrationRequestPolicy.READ,
            max_response_bytes=budget.remaining,
            usage_account_id=account_id,
        )
        budget.add(payload)
        page = payload.get("data")
        if not isinstance(page, list) or any(not isinstance(row, dict) for row in page):
            raise invalid_response("Meta Ads returned an invalid list.", operation=operation)
        paging = payload.get("paging", {})
        if not isinstance(paging, dict):
            raise invalid_response("Meta Ads returned invalid pagination.", operation=operation)
        next_url = paging.get("next")
        matches = [row for row in page if include(row)] if include else page
        remaining = limit - len(rows)
        rows.extend(matches[:remaining])
        if len(rows) >= limit:
            return rows, bool(next_url) or len(matches) > remaining
        if not next_url:
            return rows, False
        cursor = next_cursor(next_url, path, operation)
        if cursor in seen or not page:
            return rows, True
        seen.add(cursor)
        query["after"] = cursor
    return rows, True
