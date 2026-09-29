# apps/api/integrations/google_ads/tools/verifiers/label.py

"""Live label verification for Google Ads write tools."""

from collections.abc import Sequence

from pydantic_ai import ModelRetry

from integrations.google_ads.client import GoogleAdsClient
from integrations.google_ads.operations.list_labels import list_labels
from integrations.google_ads.references import (
    GoogleAdsLabelReference,
    label_reference_from_row,
)
from integrations.google_ads.tools.utils.routing import login_customer_id
from services.integrations.context.domain import ResolvedContextEntry

from .utils import validated_ids

_UNAVAILABLE_MESSAGE = "A selected label is unavailable. Ask the user to choose it again."


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
