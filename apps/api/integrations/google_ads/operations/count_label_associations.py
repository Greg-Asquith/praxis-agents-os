# apps/api/integrations/google_ads/operations/count_label_associations.py

"""Count live Google Ads label associations by entity type."""

from collections.abc import Sequence

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from ..references import GoogleAdsLabelAssociationCounts
from .utils import stream_rows

LABEL_ASSOCIATION_ROW_BOUND = 10_000

# (count key, GAQL resource, JSON row key, extra selected fields)
_ASSOCIATION_RESOURCES = (
    ("campaign", "campaign_label", "campaignLabel", ""),
    ("ad_group", "ad_group_label", "adGroupLabel", ""),
    (
        "keyword",
        "ad_group_criterion_label",
        "adGroupCriterionLabel",
        ", ad_group_criterion.type, ad_group_criterion.negative",
    ),
    ("ad", "ad_group_ad_label", "adGroupAdLabel", ""),
)
_COUNT_KEYS = ("campaign", "ad_group", "keyword", "other_criterion", "ad")


async def count_label_associations(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    label_ids: Sequence[str],
) -> dict[str, GoogleAdsLabelAssociationCounts]:
    """Returns bounded association counts for each requested label.

    Each entity type reads one row past `LABEL_ASSOCIATION_ROW_BOUND` across all
    requested labels; a type that exceeds the bound marks every count truncated.
    """
    normalized_customer_id = normalize_customer_id(customer_id)
    ids = sorted(set(label_ids))
    if not ids or any(not label_id.isdigit() for label_id in ids):
        raise ValueError("Google Ads label ids must contain only digits")
    resource_by_id = {
        label_id: f"customers/{normalized_customer_id}/labels/{label_id}" for label_id in ids
    }
    id_by_resource = {resource: label_id for label_id, resource in resource_by_id.items()}
    label_list = ", ".join(f"'{resource}'" for resource in resource_by_id.values())
    counts = {label_id: dict.fromkeys(_COUNT_KEYS, 0) for label_id in ids}
    truncated = False
    for key, resource, row_key, extra_fields in _ASSOCIATION_RESOURCES:
        query = (
            f"SELECT {resource}.label{extra_fields} FROM {resource} "  # noqa: S608 -- fixed resources and digit-only ids
            f"WHERE {resource}.label IN ({label_list}) "
            f"LIMIT {LABEL_ASSOCIATION_ROW_BOUND + 1}"
        )
        payload = await client.post(
            f"customers/{normalized_customer_id}/googleAds:searchStream",
            operation="count_label_associations",
            policy=IntegrationRequestPolicy.READ,
            login_customer_id=login_customer_id,
            json={"query": query},
        )
        rows = stream_rows(payload, max_rows=LABEL_ASSOCIATION_ROW_BOUND + 1)
        if len(rows) > LABEL_ASSOCIATION_ROW_BOUND:
            truncated = True
            rows = rows[:LABEL_ASSOCIATION_ROW_BOUND]
        for row in rows:
            association = row.get(row_key)
            label_id = (
                id_by_resource.get(str(association.get("label", "")))
                if isinstance(association, dict)
                else None
            )
            if label_id is not None:
                counts[label_id][_count_key(key, row)] += 1
    return {
        label_id: GoogleAdsLabelAssociationCounts(**label_counts, truncated=truncated)
        for label_id, label_counts in counts.items()
    }


def _count_key(key: str, row: dict) -> str:
    if key != "keyword":
        return key
    criterion = row.get("adGroupCriterion")
    positive_keyword = (
        isinstance(criterion, dict)
        and criterion.get("type") == "KEYWORD"
        and criterion.get("negative") is not True
    )
    return "keyword" if positive_keyword else "other_criterion"
