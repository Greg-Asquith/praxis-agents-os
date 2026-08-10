# apps/api/integrations/google_ads/operations/campaign_negative_keywords.py

"""Add or remove campaign-level Google Ads negative keyword criteria."""

from collections.abc import Mapping
from typing import Any

from core.exceptions.integration import IntegrationValidationError

from ..client import GoogleAdsClient, normalize_customer_id
from .utils import grouped_partial_failure_errors, stream_rows

MAX_CAMPAIGN_NEGATIVE_OPERATIONS = 2_500
_MATCH_TYPES = {"EXACT", "PHRASE", "BROAD"}
_UNACCOUNTED_RESPONSE_MESSAGE = "Google Ads did not account for this submitted operation"
_UNACCOUNTED_RESPONSE_CODE = "UNACCOUNTED_OPERATION"


async def add_campaign_negative_keywords(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    campaign_ids: list[str],
    keywords: list[dict[str, str]],
) -> dict[str, Any]:
    normalized_customer_id = normalize_customer_id(customer_id)
    normalized_campaign_ids = _campaign_ids(campaign_ids)
    _validate_operation_count(normalized_campaign_ids, keywords, operation="add")
    existing = await _campaign_criteria(
        client,
        customer_id=normalized_customer_id,
        login_customer_id=login_customer_id,
        campaign_ids=normalized_campaign_ids,
    )
    existing_pairs = {
        (criterion["campaign_id"], criterion["text"].casefold(), criterion["match_type"])
        for criterion in existing
    }
    requested = [
        {"campaign_id": campaign_id, **keyword}
        for campaign_id in normalized_campaign_ids
        for keyword in keywords
    ]
    skipped_existing = [
        item
        for item in requested
        if (item["campaign_id"], item["text"].casefold(), item["match_type"]) in existing_pairs
    ]
    creates = [
        item
        for item in requested
        if (item["campaign_id"], item["text"].casefold(), item["match_type"]) not in existing_pairs
    ]
    if not creates:
        return {
            "added": [],
            "resource_names": [],
            "skipped_existing": skipped_existing,
            "campaign_errors": [],
        }

    payload = await client.post(
        f"customers/{normalized_customer_id}/campaignCriteria:mutate",
        operation="add_campaign_negative_keywords",
        login_customer_id=login_customer_id,
        json={
            "operations": [
                {
                    "create": {
                        "campaign": (
                            f"customers/{normalized_customer_id}/campaigns/{item['campaign_id']}"
                        ),
                        "negative": True,
                        "keyword": {
                            "text": item["text"],
                            "matchType": item["match_type"],
                        },
                    }
                }
                for item in creates
            ],
            "partialFailure": True,
        },
    )
    added, campaign_errors = _mutation_results(
        payload,
        creates,
        default_message="Campaign negative keyword creation failed",
    )
    return {
        "added": added,
        "resource_names": [item["resource_name"] for item in added],
        "skipped_existing": skipped_existing,
        "campaign_errors": campaign_errors,
    }


async def remove_campaign_negative_keywords(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    campaign_ids: list[str],
    keywords: list[dict[str, str]],
) -> dict[str, Any]:
    normalized_customer_id = normalize_customer_id(customer_id)
    normalized_campaign_ids = _campaign_ids(campaign_ids)
    _validate_operation_count(normalized_campaign_ids, keywords, operation="remove")
    existing = await _campaign_criteria(
        client,
        customer_id=normalized_customer_id,
        login_customer_id=login_customer_id,
        campaign_ids=normalized_campaign_ids,
    )
    removals: list[dict[str, str]] = []
    not_found: list[dict[str, str]] = []
    for campaign_id in normalized_campaign_ids:
        campaign_criteria = [
            criterion for criterion in existing if criterion["campaign_id"] == campaign_id
        ]
        for keyword in keywords:
            matches = [
                criterion
                for criterion in campaign_criteria
                if criterion["text"].casefold() == keyword["text"].casefold()
                and (
                    keyword["match_type"] == "ANY"
                    or criterion["match_type"] == keyword["match_type"]
                )
            ]
            if matches:
                removals.extend(matches)
            else:
                not_found.append({"campaign_id": campaign_id, **keyword})

    if len(removals) > MAX_CAMPAIGN_NEGATIVE_OPERATIONS:
        raise IntegrationValidationError(
            "The selected rows resolve to more than 2,500 campaign negative keywords. "
            "Split the request into smaller groups.",
            provider_key="google_ads",
            operation="remove_campaign_negative_keywords",
        )
    if not removals:
        return {
            "removed": [],
            "resource_names": [],
            "not_found": not_found,
            "campaign_errors": [],
        }

    payload = await client.post(
        f"customers/{normalized_customer_id}/campaignCriteria:mutate",
        operation="remove_campaign_negative_keywords",
        login_customer_id=login_customer_id,
        json={
            "operations": [{"remove": item["resource_name"]} for item in removals],
            "partialFailure": True,
        },
    )
    removed, campaign_errors = _mutation_results(
        payload,
        removals,
        default_message="Campaign negative keyword removal failed",
    )
    return {
        "removed": removed,
        "resource_names": [item["resource_name"] for item in removed],
        "not_found": not_found,
        "campaign_errors": campaign_errors,
    }


async def _campaign_criteria(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    campaign_ids: list[str],
) -> list[dict[str, str]]:
    query = (
        "SELECT campaign.id, campaign_criterion.resource_name, "  # noqa: S608 -- digit-only campaign ids
        "campaign_criterion.keyword.text, campaign_criterion.keyword.match_type "
        "FROM campaign_criterion "
        "WHERE campaign_criterion.negative = TRUE "
        "AND campaign_criterion.type = 'KEYWORD' "
        f"AND campaign.id IN ({', '.join(campaign_ids)})"
    )
    payload = await client.post(
        f"customers/{customer_id}/googleAds:searchStream",
        operation="list_campaign_negative_keywords",
        login_customer_id=login_customer_id,
        json={"query": query},
    )
    criteria: list[dict[str, str]] = []
    for row in stream_rows(payload):
        campaign = row.get("campaign")
        criterion = row.get("campaignCriterion")
        if not isinstance(campaign, Mapping) or not isinstance(criterion, Mapping):
            continue
        campaign_id = str(campaign.get("id", ""))
        resource_name = criterion.get("resourceName")
        keyword = criterion.get("keyword")
        if (
            campaign_id not in campaign_ids
            or not isinstance(resource_name, str)
            or not resource_name
            or not isinstance(keyword, Mapping)
        ):
            continue
        text = keyword.get("text")
        match_type = keyword.get("matchType")
        if not isinstance(text, str) or match_type not in _MATCH_TYPES:
            continue
        criteria.append(
            {
                "campaign_id": campaign_id,
                "text": text,
                "match_type": match_type,
                "resource_name": resource_name,
            }
        )
    return criteria


def _campaign_ids(campaign_ids: list[str]) -> list[str]:
    normalized = list(dict.fromkeys(normalize_customer_id(value) for value in campaign_ids))
    if not normalized:
        raise ValueError("At least one Google Ads campaign id is required")
    return normalized


def _validate_operation_count(
    campaign_ids: list[str],
    keywords: list[dict[str, str]],
    *,
    operation: str,
) -> None:
    if len(campaign_ids) * len(keywords) > MAX_CAMPAIGN_NEGATIVE_OPERATIONS:
        raise IntegrationValidationError(
            "Campaigns multiplied by keyword rows must not exceed 2,500. "
            "Split the request into smaller groups.",
            provider_key="google_ads",
            operation=f"{operation}_campaign_negative_keywords",
        )


def _mutation_results(
    payload: Any,
    operations: list[dict[str, str]],
    *,
    default_message: str,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    indexed_errors, unattributed_errors = grouped_partial_failure_errors(
        payload,
        operations,
        value_to_error_fields=lambda item: _error_fields(item),
        unattributed_error_fields={
            "campaign_id": "",
            "text": "",
            "match_type": "",
        },
        default_message=default_message,
    )
    results = payload.get("results") if isinstance(payload, dict) else None
    if unattributed_errors:
        diagnostic = unattributed_errors[0]
        return [], [_operation_error(item, diagnostic) for item in operations]
    if not isinstance(results, list) or len(results) != len(operations):
        return [], [
            _operation_error(item, indexed_errors.get(index))
            for index, item in enumerate(operations)
        ]

    succeeded: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    for index, (operation, item) in enumerate(zip(operations, results, strict=True)):
        error = indexed_errors.get(index)
        resource_name = item.get("resourceName") if isinstance(item, Mapping) else None
        if error is not None:
            errors.append(error)
        elif isinstance(resource_name, str) and resource_name:
            succeeded.append({**_error_fields(operation), "resource_name": resource_name})
        else:
            errors.append(_operation_error(operation, None))
    return succeeded, errors


def _error_fields(item: Mapping[str, str]) -> dict[str, str]:
    return {
        "campaign_id": item["campaign_id"],
        "text": item["text"],
        "match_type": item["match_type"],
    }


def _operation_error(
    item: Mapping[str, str], diagnostic: Mapping[str, str] | None
) -> dict[str, str]:
    return {
        **_error_fields(item),
        "message": (diagnostic["message"] if diagnostic else _UNACCOUNTED_RESPONSE_MESSAGE),
        "error_code": (diagnostic["error_code"] if diagnostic else _UNACCOUNTED_RESPONSE_CODE),
    }
