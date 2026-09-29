# apps/api/integrations/google_ads/tools/verifiers/label.py

"""Live label verification for Google Ads write tools."""

from collections.abc import Mapping, Sequence

from pydantic_ai import ModelRetry

from integrations.google_ads.client import GoogleAdsClient
from integrations.google_ads.operations.list_ad_groups import list_ad_groups
from integrations.google_ads.operations.list_campaigns import list_campaigns
from integrations.google_ads.operations.list_labels import list_labels
from integrations.google_ads.references import (
    GoogleAdsAdGroupReference,
    GoogleAdsCampaignReference,
    GoogleAdsKeywordReference,
    GoogleAdsLabelReference,
    label_reference_from_row,
)
from integrations.google_ads.tools.utils.routing import login_customer_id
from services.integrations.context.domain import ResolvedContextEntry

from .keyword import verify_positive_keywords
from .utils import validated_ids

_UNAVAILABLE_MESSAGE = "A selected label is unavailable. Ask the user to choose it again."
_TARGET_UNAVAILABLE_MESSAGE = (
    "A selected Google Ads campaign, ad group, or keyword is unavailable. "
    "Ask the user to choose it again."
)
_LOOKUP_BATCH_SIZE = 100


async def verify_labels(
    client: GoogleAdsClient,
    *,
    entry: ResolvedContextEntry,
    label_ids: Sequence[str],
) -> dict[str, GoogleAdsLabelReference]:
    """Returns live references, failing closed unless every approved label is enabled."""
    normalized_ids = validated_ids(label_ids, invalid_message=_UNAVAILABLE_MESSAGE)
    labels = await list_labels(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        label_ids=normalized_ids,
        limit=len(normalized_ids),
    )
    references = {
        reference.label_id: reference
        for label in labels
        if (
            reference := label_reference_from_row(
                entry.external_id,
                label,
                scope_label=entry.display_name,
            )
        )
        is not None
    }
    if set(references) != set(normalized_ids):
        raise ModelRetry(_UNAVAILABLE_MESSAGE)
    return references


async def verify_label_targets(
    client: GoogleAdsClient,
    *,
    entry: ResolvedContextEntry,
    campaigns: Sequence[GoogleAdsCampaignReference],
    ad_groups: Sequence[GoogleAdsAdGroupReference],
    keywords: Sequence[GoogleAdsKeywordReference],
) -> None:
    """Fails closed unless every label target still exists and isn't removed."""
    if campaigns:
        await _verify_live_ids(
            client,
            entry=entry,
            ids=[reference.campaign_id for reference in campaigns],
            kind="campaign",
        )
    if ad_groups:
        await _verify_live_ids(
            client,
            entry=entry,
            ids=[reference.ad_group_id for reference in ad_groups],
            kind="ad_group",
        )
    if keywords:
        await verify_positive_keywords(client, entry=entry, selected=keywords)


async def _verify_live_ids(
    client: GoogleAdsClient,
    *,
    entry: ResolvedContextEntry,
    ids: Sequence[str],
    kind: str,
) -> None:
    normalized_ids = validated_ids(ids, invalid_message=_TARGET_UNAVAILABLE_MESSAGE)
    live: set[str] = set()
    for start in range(0, len(normalized_ids), _LOOKUP_BATCH_SIZE):
        batch = normalized_ids[start : start + _LOOKUP_BATCH_SIZE]
        if kind == "campaign":
            rows = await list_campaigns(
                client,
                customer_id=entry.external_id,
                login_customer_id=login_customer_id(entry),
                campaign_ids=batch,
                limit=len(batch),
                exclude_removed=True,
            )
        else:
            rows = [
                ad_group
                for row in await list_ad_groups(
                    client,
                    customer_id=entry.external_id,
                    login_customer_id=login_customer_id(entry),
                    ad_group_ids=batch,
                    limit=len(batch),
                    exclude_removed=True,
                )
                if isinstance((ad_group := row.get("adGroup")), Mapping)
            ]
        live.update(str(row.get("id", "")) for row in rows if row.get("status") != "REMOVED")
    if live != set(normalized_ids):
        raise ModelRetry(_TARGET_UNAVAILABLE_MESSAGE)
