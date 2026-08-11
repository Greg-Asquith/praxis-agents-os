# apps/api/integrations/google_ads/operations/negative_keyword_criteria.py

"""Shared Google Ads campaign and ad-group negative-keyword mechanics."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from core.exceptions.integration import IntegrationValidationError

from ..client import GoogleAdsClient, normalize_customer_id
from .utils import grouped_partial_failure_errors, stream_rows

MAX_ENTITY_NEGATIVE_OPERATIONS = 2_500

type EntityIdKey = Literal["campaign_id", "ad_group_id"]
type ErrorsKey = Literal["campaign_errors", "ad_group_errors"]

_MATCH_TYPES = {"EXACT", "PHRASE", "BROAD"}
_UNACCOUNTED_RESPONSE_MESSAGE = "Google Ads did not account for this submitted operation"
_UNACCOUNTED_RESPONSE_CODE = "UNACCOUNTED_OPERATION"


@dataclass(frozen=True, slots=True)
class NegativeKeywordEntitySpec:
    """Provider-local fields that differ between supported criterion owners."""

    entity_id_key: EntityIdKey
    errors_key: ErrorsKey
    entity_resource: Literal["campaign", "ad_group"]
    criterion_resource: Literal["campaign_criterion", "ad_group_criterion"]
    response_entity_key: Literal["campaign", "adGroup"]
    response_criterion_key: Literal["campaignCriterion", "adGroupCriterion"]
    create_field: Literal["campaign", "adGroup"]
    entity_path: Literal["campaigns", "adGroups"]
    criterion_path: Literal["campaignCriteria", "adGroupCriteria"]
    operation_entity: Literal["campaign", "ad_group"]
    entity_plural_label: Literal["Campaigns", "Ad groups"]
    criterion_label: Literal["campaign", "ad group"]
    max_operations: int


CAMPAIGN_NEGATIVE_KEYWORD_SPEC = NegativeKeywordEntitySpec(
    entity_id_key="campaign_id",
    errors_key="campaign_errors",
    entity_resource="campaign",
    criterion_resource="campaign_criterion",
    response_entity_key="campaign",
    response_criterion_key="campaignCriterion",
    create_field="campaign",
    entity_path="campaigns",
    criterion_path="campaignCriteria",
    operation_entity="campaign",
    entity_plural_label="Campaigns",
    criterion_label="campaign",
    max_operations=MAX_ENTITY_NEGATIVE_OPERATIONS,
)
AD_GROUP_NEGATIVE_KEYWORD_SPEC = NegativeKeywordEntitySpec(
    entity_id_key="ad_group_id",
    errors_key="ad_group_errors",
    entity_resource="ad_group",
    criterion_resource="ad_group_criterion",
    response_entity_key="adGroup",
    response_criterion_key="adGroupCriterion",
    create_field="adGroup",
    entity_path="adGroups",
    criterion_path="adGroupCriteria",
    operation_entity="ad_group",
    entity_plural_label="Ad groups",
    criterion_label="ad group",
    max_operations=MAX_ENTITY_NEGATIVE_OPERATIONS,
)
_KNOWN_SPECS = (CAMPAIGN_NEGATIVE_KEYWORD_SPEC, AD_GROUP_NEGATIVE_KEYWORD_SPEC)


async def add_entity_negative_keywords(
    client: GoogleAdsClient,
    *,
    spec: NegativeKeywordEntitySpec,
    customer_id: str,
    login_customer_id: str,
    entity_ids: list[str],
    keywords: list[dict[str, str]],
) -> dict[str, Any]:
    _require_known_spec(spec)
    normalized_customer_id = normalize_customer_id(customer_id)
    normalized_entity_ids = _entity_ids(spec, entity_ids)
    _validate_operation_count(spec, normalized_entity_ids, keywords, operation="add")
    existing = await _negative_criteria(
        client,
        spec=spec,
        customer_id=normalized_customer_id,
        login_customer_id=login_customer_id,
        entity_ids=normalized_entity_ids,
    )
    existing_pairs = {
        (criterion[spec.entity_id_key], criterion["text"].casefold(), criterion["match_type"])
        for criterion in existing
    }
    requested = [
        {spec.entity_id_key: entity_id, **keyword}
        for entity_id in normalized_entity_ids
        for keyword in keywords
    ]
    skipped_existing = [
        item
        for item in requested
        if (item[spec.entity_id_key], item["text"].casefold(), item["match_type"]) in existing_pairs
    ]
    creates = [
        item
        for item in requested
        if (item[spec.entity_id_key], item["text"].casefold(), item["match_type"])
        not in existing_pairs
    ]
    if not creates:
        return {
            "added": [],
            "resource_names": [],
            "skipped_existing": skipped_existing,
            spec.errors_key: [],
        }

    payload = await client.post(
        f"customers/{normalized_customer_id}/{spec.criterion_path}:mutate",
        operation=f"add_{spec.operation_entity}_negative_keywords",
        login_customer_id=login_customer_id,
        json={
            "operations": [
                {
                    "create": {
                        spec.create_field: (
                            f"customers/{normalized_customer_id}/{spec.entity_path}/"
                            f"{item[spec.entity_id_key]}"
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
    added, errors = _mutation_results(
        payload,
        creates,
        spec=spec,
        default_message=f"{spec.entity_plural_label[:-1]} negative keyword creation failed",
    )
    return {
        "added": added,
        "resource_names": [item["resource_name"] for item in added],
        "skipped_existing": skipped_existing,
        spec.errors_key: errors,
    }


async def remove_entity_negative_keywords(
    client: GoogleAdsClient,
    *,
    spec: NegativeKeywordEntitySpec,
    customer_id: str,
    login_customer_id: str,
    entity_ids: list[str],
    keywords: list[dict[str, str]],
) -> dict[str, Any]:
    _require_known_spec(spec)
    normalized_customer_id = normalize_customer_id(customer_id)
    normalized_entity_ids = _entity_ids(spec, entity_ids)
    _validate_operation_count(spec, normalized_entity_ids, keywords, operation="remove")
    existing = await _negative_criteria(
        client,
        spec=spec,
        customer_id=normalized_customer_id,
        login_customer_id=login_customer_id,
        entity_ids=normalized_entity_ids,
    )
    removals: list[dict[str, str]] = []
    not_found: list[dict[str, str]] = []
    for entity_id in normalized_entity_ids:
        entity_criteria = [
            criterion for criterion in existing if criterion[spec.entity_id_key] == entity_id
        ]
        for keyword in keywords:
            matches = [
                criterion
                for criterion in entity_criteria
                if criterion["text"].casefold() == keyword["text"].casefold()
                and (
                    keyword["match_type"] == "ANY"
                    or criterion["match_type"] == keyword["match_type"]
                )
            ]
            if matches:
                removals.extend(matches)
            else:
                not_found.append({spec.entity_id_key: entity_id, **keyword})

    if len(removals) > spec.max_operations:
        raise IntegrationValidationError(
            f"The selected rows resolve to more than {spec.max_operations:,} "
            f"{spec.criterion_label} "
            "negative keywords. Split the request into smaller groups.",
            provider_key="google_ads",
            operation=f"remove_{spec.operation_entity}_negative_keywords",
        )
    if not removals:
        return {
            "removed": [],
            "resource_names": [],
            "not_found": not_found,
            spec.errors_key: [],
        }

    payload = await client.post(
        f"customers/{normalized_customer_id}/{spec.criterion_path}:mutate",
        operation=f"remove_{spec.operation_entity}_negative_keywords",
        login_customer_id=login_customer_id,
        json={
            "operations": [{"remove": item["resource_name"]} for item in removals],
            "partialFailure": True,
        },
    )
    removed, errors = _mutation_results(
        payload,
        removals,
        spec=spec,
        default_message=f"{spec.entity_plural_label[:-1]} negative keyword removal failed",
    )
    return {
        "removed": removed,
        "resource_names": [item["resource_name"] for item in removed],
        "not_found": not_found,
        spec.errors_key: errors,
    }


async def _negative_criteria(
    client: GoogleAdsClient,
    *,
    spec: NegativeKeywordEntitySpec,
    customer_id: str,
    login_customer_id: str,
    entity_ids: list[str],
) -> list[dict[str, str]]:
    query = (
        f"SELECT {spec.entity_resource}.id, {spec.criterion_resource}.resource_name, "  # noqa: S608 -- spec literals and digit-only entity ids
        f"{spec.criterion_resource}.keyword.text, "
        f"{spec.criterion_resource}.keyword.match_type "
        f"FROM {spec.criterion_resource} "
        f"WHERE {spec.criterion_resource}.negative = TRUE "
        f"AND {spec.criterion_resource}.type = 'KEYWORD' "
        f"AND {spec.entity_resource}.id IN ({', '.join(entity_ids)})"
    )
    payload = await client.post(
        f"customers/{customer_id}/googleAds:searchStream",
        operation=f"list_{spec.operation_entity}_negative_keywords",
        login_customer_id=login_customer_id,
        json={"query": query},
    )
    criteria: list[dict[str, str]] = []
    for row in stream_rows(payload):
        entity = row.get(spec.response_entity_key)
        criterion = row.get(spec.response_criterion_key)
        if not isinstance(entity, Mapping) or not isinstance(criterion, Mapping):
            continue
        entity_id = str(entity.get("id", ""))
        resource_name = criterion.get("resourceName")
        keyword = criterion.get("keyword")
        if (
            entity_id not in entity_ids
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
                spec.entity_id_key: entity_id,
                "text": text,
                "match_type": match_type,
                "resource_name": resource_name,
            }
        )
    return criteria


def _entity_ids(spec: NegativeKeywordEntitySpec, entity_ids: list[str]) -> list[str]:
    normalized = list(dict.fromkeys(normalize_customer_id(value) for value in entity_ids))
    if not normalized:
        raise ValueError(f"At least one Google Ads {spec.criterion_label} id is required")
    return normalized


def _validate_operation_count(
    spec: NegativeKeywordEntitySpec,
    entity_ids: list[str],
    keywords: list[dict[str, str]],
    *,
    operation: str,
) -> None:
    if len(entity_ids) * len(keywords) > spec.max_operations:
        raise IntegrationValidationError(
            f"{spec.entity_plural_label} multiplied by keyword rows must not exceed "
            f"{spec.max_operations:,}. "
            "Split the request into smaller groups.",
            provider_key="google_ads",
            operation=f"{operation}_{spec.operation_entity}_negative_keywords",
        )


def _mutation_results(
    payload: Any,
    operations: list[dict[str, str]],
    *,
    spec: NegativeKeywordEntitySpec,
    default_message: str,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    indexed_errors, unattributed_errors = grouped_partial_failure_errors(
        payload,
        operations,
        value_to_error_fields=lambda item: _error_fields(spec, item),
        unattributed_error_fields={
            spec.entity_id_key: "",
            "text": "",
            "match_type": "",
        },
        default_message=default_message,
    )
    results = payload.get("results") if isinstance(payload, dict) else None
    if unattributed_errors:
        diagnostic = unattributed_errors[0]
        return [], [_operation_error(spec, item, diagnostic) for item in operations]
    if not isinstance(results, list) or len(results) != len(operations):
        return [], [
            _operation_error(spec, item, indexed_errors.get(index))
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
            succeeded.append({**_error_fields(spec, operation), "resource_name": resource_name})
        else:
            errors.append(_operation_error(spec, operation, None))
    return succeeded, errors


def _error_fields(spec: NegativeKeywordEntitySpec, item: Mapping[str, str]) -> dict[str, str]:
    return {
        spec.entity_id_key: item[spec.entity_id_key],
        "text": item["text"],
        "match_type": item["match_type"],
    }


def _operation_error(
    spec: NegativeKeywordEntitySpec,
    item: Mapping[str, str],
    diagnostic: Mapping[str, str] | None,
) -> dict[str, str]:
    return {
        **_error_fields(spec, item),
        "message": diagnostic["message"] if diagnostic else _UNACCOUNTED_RESPONSE_MESSAGE,
        "error_code": diagnostic["error_code"] if diagnostic else _UNACCOUNTED_RESPONSE_CODE,
    }


def _require_known_spec(spec: NegativeKeywordEntitySpec) -> None:
    if spec not in _KNOWN_SPECS:
        raise ValueError("Unsupported Google Ads negative-keyword entity specification")
