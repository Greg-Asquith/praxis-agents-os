# apps/api/integrations/google_ads/tools/verifiers/recommendation.py

"""Live recommendation verification for Google Ads action tools."""

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic_ai import ModelRetry

from integrations.google_ads.client import GoogleAdsClient
from integrations.google_ads.operations.list_recommendations import list_recommendations
from integrations.google_ads.references import GoogleAdsRecommendationReference
from integrations.google_ads.tools.utils.routing import login_customer_id
from services.integrations.context.domain import ResolvedContextEntry


async def verify_recommendations(
    client: GoogleAdsClient,
    *,
    entry: ResolvedContextEntry,
    references: Sequence[GoogleAdsRecommendationReference],
) -> dict[str, Mapping[str, Any]]:
    """Returns live rows after verifying every recommendation remains actionable."""
    resource_names = tuple(dict.fromkeys(reference.resource_name for reference in references))
    if not resource_names or len(resource_names) != len(references):
        raise ModelRetry("Choose each Google Ads recommendation only once.")
    rows = await list_recommendations(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        resource_names=resource_names,
        include_dismissed=True,
        limit=len(resource_names),
    )
    rows_by_name = {
        str(row.get("resourceName")): row
        for row in rows
        if isinstance(row.get("resourceName"), str)
    }
    if set(rows_by_name) != set(resource_names):
        raise ModelRetry(
            "A selected Google Ads recommendation is no longer available. "
            "Run the recommendation report again before retrying."
        )
    for reference in references:
        live = rows_by_name[reference.resource_name]
        if live.get("dismissed") is True:
            raise ModelRetry(
                "A selected Google Ads recommendation has been dismissed. "
                "Run the recommendation report again before retrying."
            )
        if live.get("type") != reference.recommendation_type:
            raise ModelRetry(
                "A selected Google Ads recommendation has changed. "
                "Run the recommendation report again before retrying."
            )
    return rows_by_name
