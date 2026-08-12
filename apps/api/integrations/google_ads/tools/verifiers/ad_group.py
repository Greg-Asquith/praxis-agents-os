# apps/api/integrations/google_ads/tools/verifiers/ad_group.py

"""Live entity-reference verification for Google Ads write tools."""

from collections.abc import Mapping, Sequence

from pydantic_ai import ModelRetry

from integrations.google_ads.client import GoogleAdsClient
from integrations.google_ads.operations.list_ad_groups import list_ad_groups
from integrations.google_ads.tools.utils.routing import login_customer_id
from services.integrations.context.domain import ResolvedContextEntry

from .utils import validated_ids


async def verify_ad_groups(
    client: GoogleAdsClient,
    *,
    entry: ResolvedContextEntry,
    ad_group_ids: Sequence[str],
) -> None:
    """Fail closed unless every approved ad group still exists in its account."""
    normalized_ids = validated_ids(
        ad_group_ids,
        invalid_message=(
            "A selected Google Ads ad group is unavailable. Ask the user to choose it again."
        ),
    )
    rows = await list_ad_groups(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        ad_group_ids=normalized_ids,
        limit=len(normalized_ids),
        exclude_removed=False,
    )
    resolved_ids = {
        str(ad_group.get("id", ""))
        for row in rows
        if isinstance((ad_group := row.get("adGroup")), Mapping)
    }
    if resolved_ids != set(normalized_ids):
        raise ModelRetry(
            "A selected Google Ads ad group is unavailable. Ask the user to choose it again."
        )
