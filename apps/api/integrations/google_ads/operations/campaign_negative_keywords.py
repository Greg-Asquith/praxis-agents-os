# apps/api/integrations/google_ads/operations/campaign_negative_keywords.py

"""Campaign-level Google Ads negative-keyword operation adapters."""

from typing import Any

from ..client import GoogleAdsClient
from .negative_keyword_criteria import (
    CAMPAIGN_NEGATIVE_KEYWORD_SPEC,
    MAX_ENTITY_NEGATIVE_OPERATIONS,
    add_entity_negative_keywords,
    remove_entity_negative_keywords,
)

MAX_CAMPAIGN_NEGATIVE_OPERATIONS = MAX_ENTITY_NEGATIVE_OPERATIONS


async def add_campaign_negative_keywords(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    campaign_ids: list[str],
    keywords: list[dict[str, str]],
) -> dict[str, Any]:
    return await add_entity_negative_keywords(
        client,
        spec=CAMPAIGN_NEGATIVE_KEYWORD_SPEC,
        customer_id=customer_id,
        login_customer_id=login_customer_id,
        entity_ids=campaign_ids,
        keywords=keywords,
    )


async def remove_campaign_negative_keywords(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    campaign_ids: list[str],
    keywords: list[dict[str, str]],
) -> dict[str, Any]:
    return await remove_entity_negative_keywords(
        client,
        spec=CAMPAIGN_NEGATIVE_KEYWORD_SPEC,
        customer_id=customer_id,
        login_customer_id=login_customer_id,
        entity_ids=campaign_ids,
        keywords=keywords,
    )
