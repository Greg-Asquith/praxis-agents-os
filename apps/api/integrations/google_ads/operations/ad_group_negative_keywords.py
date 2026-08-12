# apps/api/integrations/google_ads/operations/ad_group_negative_keywords.py

"""Ad-group-level Google Ads negative-keyword operation adapters."""

from typing import Any

from ..client import GoogleAdsClient
from .negative_keyword_criteria import (
    AD_GROUP_NEGATIVE_KEYWORD_SPEC,
    MAX_ENTITY_NEGATIVE_OPERATIONS,
    add_entity_negative_keywords,
    remove_entity_negative_keywords,
)

MAX_AD_GROUP_NEGATIVE_OPERATIONS = MAX_ENTITY_NEGATIVE_OPERATIONS


async def add_ad_group_negative_keywords(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    ad_group_ids: list[str],
    keywords: list[dict[str, str]],
) -> dict[str, Any]:
    return await add_entity_negative_keywords(
        client,
        spec=AD_GROUP_NEGATIVE_KEYWORD_SPEC,
        customer_id=customer_id,
        login_customer_id=login_customer_id,
        entity_ids=ad_group_ids,
        keywords=keywords,
    )


async def remove_ad_group_negative_keywords(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    ad_group_ids: list[str],
    keywords: list[dict[str, str]],
) -> dict[str, Any]:
    return await remove_entity_negative_keywords(
        client,
        spec=AD_GROUP_NEGATIVE_KEYWORD_SPEC,
        customer_id=customer_id,
        login_customer_id=login_customer_id,
        entity_ids=ad_group_ids,
        keywords=keywords,
    )
