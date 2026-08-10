# apps/api/integrations/google_ads/tools/verifiers/shared_set.py

"""Live entity-reference verification for Google Ads write tools."""

from collections.abc import Sequence

from pydantic_ai import ModelRetry

from integrations.google_ads.client import GoogleAdsClient
from integrations.google_ads.operations.list_shared_sets import list_shared_sets
from integrations.google_ads.tools.utils.routing import login_customer_id
from services.integrations.context.domain import ResolvedContextEntry

from .utils import mapping_ids, validated_ids


async def verify_shared_sets(
    client: GoogleAdsClient,
    *,
    entry: ResolvedContextEntry,
    shared_set_ids: Sequence[str],
) -> None:
    """Fail closed unless every approved enabled negative list still exists."""
    normalized_ids = validated_ids(
        shared_set_ids,
        invalid_message=(
            "The selected negative keyword list is unavailable. Ask the user to choose it again."
        ),
    )
    shared_sets = await list_shared_sets(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        shared_set_type="NEGATIVE_KEYWORDS",
        shared_set_ids=normalized_ids,
        limit=len(normalized_ids),
    )
    if mapping_ids(shared_sets) != set(normalized_ids):
        raise ModelRetry(
            "The selected negative keyword list is unavailable. Ask the user to choose it again."
        )
