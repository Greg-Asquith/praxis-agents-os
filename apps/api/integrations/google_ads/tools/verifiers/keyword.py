# apps/api/integrations/google_ads/tools/verifiers/keyword.py

"""Live positive-keyword verification for Google Ads write tools."""

from collections.abc import Sequence

from pydantic_ai import ModelRetry

from integrations.google_ads.client import GoogleAdsClient
from integrations.google_ads.operations.list_positive_keywords import list_positive_keywords
from integrations.google_ads.references import (
    GoogleAdsKeywordReference,
    positive_keyword_reference_from_row,
)
from integrations.google_ads.tools.utils.routing import login_customer_id
from services.integrations.context.domain import ResolvedContextEntry

_QUERY_BATCH_SIZE = 50


async def verify_positive_keywords(
    client: GoogleAdsClient,
    *,
    entry: ResolvedContextEntry,
    selected: Sequence[GoogleAdsKeywordReference],
) -> list[GoogleAdsKeywordReference]:
    """Return fresh references after rejecting stale or changed criteria."""
    identities = [reference.identity() for reference in selected]
    if not selected or len(identities) != len(set(identities)):
        raise ModelRetry("Choose each available Google Ads keyword only once.")
    references_by_key: dict[tuple[str, str], GoogleAdsKeywordReference] = {}
    for start in range(0, len(selected), _QUERY_BATCH_SIZE):
        batch = selected[start : start + _QUERY_BATCH_SIZE]
        expected = {(reference.ad_group_id, reference.criterion_id) for reference in batch}
        criterion_ids = sorted({reference.criterion_id for reference in batch})
        ad_group_ids = sorted({reference.ad_group_id for reference in batch})
        rows = await list_positive_keywords(
            client,
            customer_id=entry.external_id,
            login_customer_id=login_customer_id(entry),
            criterion_ids=criterion_ids,
            ad_group_ids=ad_group_ids,
            limit=len(criterion_ids) * len(ad_group_ids),
        )
        for row in rows:
            reference = positive_keyword_reference_from_row(entry.external_id, row)
            if reference is None:
                raise ModelRetry(
                    "A selected Google Ads keyword returned contradictory live details."
                )
            key = (reference.ad_group_id, reference.criterion_id)
            if key not in expected:
                continue
            if key in references_by_key:
                raise ModelRetry(
                    "A selected Google Ads keyword returned contradictory live details."
                )
            references_by_key[key] = reference
    selected_keys = {(reference.ad_group_id, reference.criterion_id) for reference in selected}
    if set(references_by_key) != selected_keys:
        raise ModelRetry(
            "A selected Google Ads keyword is no longer available. Ask the user to choose it again."
        )
    live = [
        references_by_key[(reference.ad_group_id, reference.criterion_id)] for reference in selected
    ]
    for original, current in zip(selected, live, strict=True):
        if _immutable_identity(original) != _immutable_identity(current):
            raise ModelRetry(
                f"Keyword {original.label!r} changed during verification. "
                "Ask the user to choose it again."
            )
    return live


def _immutable_identity(reference: GoogleAdsKeywordReference) -> tuple[str, ...]:
    return (
        reference.customer_id,
        reference.campaign_id,
        reference.ad_group_id,
        reference.criterion_id,
        reference.text,
        reference.match_type,
    )
