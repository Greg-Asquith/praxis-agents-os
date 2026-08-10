# apps/api/integrations/google_ads/tools/utils/ad_groups.py

"""Shared ad-group-reference verification for Google Ads write tools."""

from collections.abc import Mapping, Sequence

from pydantic_ai import ModelRetry

from integrations.google_ads.client import GoogleAdsClient
from integrations.google_ads.operations.utils import stream_rows
from services.integrations.context.domain import ResolvedContextEntry

from .routing import login_customer_id


async def verify_ad_groups(
    client: GoogleAdsClient,
    *,
    entry: ResolvedContextEntry,
    ad_group_ids: Sequence[str],
) -> None:
    """Fail closed unless every approved ad group still exists in its account."""
    query = (
        "SELECT ad_group.id FROM ad_group "  # noqa: S608 -- callers provide digit-only ids
        f"WHERE ad_group.id IN ({', '.join(ad_group_ids)}) "
        f"LIMIT {len(ad_group_ids)}"
    )
    payload = await client.post(
        f"customers/{entry.external_id}/googleAds:searchStream",
        operation="resolve_ad_group_references",
        login_customer_id=login_customer_id(entry),
        json={"query": query},
    )
    resolved_ids = {
        str(ad_group.get("id", ""))
        for row in stream_rows(payload)
        if isinstance((ad_group := row.get("adGroup")), Mapping)
    }
    if resolved_ids != set(ad_group_ids):
        raise ModelRetry(
            "A selected Google Ads ad group is unavailable. Ask the user to choose it again."
        )
