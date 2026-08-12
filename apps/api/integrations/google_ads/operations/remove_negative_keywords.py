# apps/api/integrations/google_ads/operations/remove_negative_keywords.py

"""Remove keyword criteria from a Google Ads negative keyword shared set."""

from collections.abc import Mapping
from typing import Any

from core.exceptions.integration import IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .mutation_outcomes import (
    SHARED_SET_KEYWORD_MUTATION_SPEC,
    GoogleAdsMutationLedger,
    build_keyword_mutation_ledger,
)
from .utils import grouped_partial_failure_errors, stream_rows

MAX_NEGATIVE_KEYWORD_REMOVALS = 500
_UNACCOUNTED_RESPONSE_MESSAGE = "Google Ads did not account for this submitted operation"
_UNACCOUNTED_RESPONSE_CODE = "UNACCOUNTED_OPERATION"


async def remove_negative_keywords(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    shared_set_id: str,
    keywords: list[dict[str, str]],
) -> GoogleAdsMutationLedger:
    normalized_customer_id = normalize_customer_id(customer_id)
    if not shared_set_id.isdigit():
        raise ValueError("Google Ads shared set id must contain only digits")
    shared_set = f"customers/{normalized_customer_id}/sharedSets/{shared_set_id}"
    existing_query = (
        "SELECT shared_criterion.criterion_id, shared_criterion.keyword.text, "  # noqa: S608 -- normalized customer id and digit-only shared set id
        "shared_criterion.keyword.match_type FROM shared_criterion "
        "WHERE shared_criterion.type = 'KEYWORD' "
        f"AND shared_criterion.shared_set = '{shared_set}'"
    )
    existing_payload = await client.post(
        f"customers/{normalized_customer_id}/googleAds:searchStream",
        operation="list_negative_keywords",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={"query": existing_query},
    )
    existing = _existing_criteria(
        stream_rows(existing_payload),
        customer_id=normalized_customer_id,
        shared_set_id=shared_set_id,
    )
    removals: list[tuple[int, dict[str, str]]] = []
    skipped_indices: dict[int, str] = {}
    for parent_index, keyword in enumerate(keywords):
        matches = [
            criterion
            for criterion in existing
            if criterion["text"].casefold() == keyword["text"].casefold()
            and (keyword["match_type"] == "ANY" or criterion["match_type"] == keyword["match_type"])
        ]
        if not matches:
            skipped_indices[parent_index] = "not_found"
            continue
        removals.extend((parent_index, match) for match in matches)

    if len(removals) > MAX_NEGATIVE_KEYWORD_REMOVALS:
        raise IntegrationValidationError(
            "The selected rows resolve to more than 500 negative keywords. "
            "Split the request into smaller groups.",
            provider_key="google_ads",
            operation="remove_negative_keywords",
        )

    if not removals:
        return _ledger(keywords, skipped_indices=skipped_indices, submitted=(), outcomes=())

    removal_rows = [removal for _, removal in removals]

    payload = await client.post(
        f"customers/{normalized_customer_id}/sharedCriteria:mutate",
        operation="remove_negative_keywords",
        policy=IntegrationRequestPolicy.MUTATION,
        login_customer_id=login_customer_id,
        json={
            "operations": [{"remove": removal["resource_name"]} for removal in removal_rows],
            "partialFailure": True,
        },
    )
    indexed_errors, unattributed_errors = grouped_partial_failure_errors(
        payload,
        removal_rows,
        value_to_error_fields=lambda removal: {
            "scope": "keyword",
            "text": removal["text"],
            "match_type": removal["match_type"],
        },
        unattributed_error_fields={"scope": "account"},
        default_message="Negative keyword removal failed",
    )
    results = payload.get("results") if isinstance(payload, dict) else None
    if unattributed_errors:
        diagnostic = unattributed_errors[0]
        return _ledger(
            keywords,
            skipped_indices=skipped_indices,
            submitted=removals,
            outcomes=[
                ("unverified", None, diagnostic["error_code"], diagnostic["message"])
                for _ in removals
            ],
        )
    if not isinstance(results, list) or len(results) != len(removals):
        outcomes = [
            (
                "failed" if index in indexed_errors else "unverified",
                None,
                (
                    indexed_errors[index]["error_code"]
                    if index in indexed_errors
                    else _UNACCOUNTED_RESPONSE_CODE
                ),
                (
                    indexed_errors[index]["message"]
                    if index in indexed_errors
                    else _UNACCOUNTED_RESPONSE_MESSAGE
                ),
            )
            for index in range(len(removals))
        ]
        return _ledger(
            keywords, skipped_indices=skipped_indices, submitted=removals, outcomes=outcomes
        )

    outcomes = []
    for index, (_removal, item) in enumerate(zip(removal_rows, results, strict=True)):
        error = indexed_errors.get(index)
        resource_name = item.get("resourceName") if isinstance(item, dict) else None
        if error is not None:
            if resource_name is not None:
                raise ValueError("Google Ads returned contradictory keyword mutation evidence")
            outcomes.append(("failed", None, error["error_code"], error["message"]))
        elif isinstance(resource_name, str) and resource_name:
            outcomes.append(("applied", resource_name, None, None))
        else:
            outcomes.append(
                ("unverified", None, _UNACCOUNTED_RESPONSE_CODE, _UNACCOUNTED_RESPONSE_MESSAGE)
            )
    return _ledger(keywords, skipped_indices=skipped_indices, submitted=removals, outcomes=outcomes)


def _ledger(
    keywords: list[dict[str, str]],
    *,
    skipped_indices: dict[int, str],
    submitted: Any,
    outcomes: Any,
) -> GoogleAdsMutationLedger:
    concrete = [
        (parent_index, {key: value for key, value in removal.items() if key != "resource_name"})
        for parent_index, removal in submitted
    ]
    return build_keyword_mutation_ledger(
        spec=SHARED_SET_KEYWORD_MUTATION_SPEC,
        action="remove",
        parent_fields=keywords,
        skipped_indices=skipped_indices,
        submitted=concrete,
        outcomes=outcomes,
    )


def _existing_criteria(
    rows: list[dict[str, Any]],
    *,
    customer_id: str,
    shared_set_id: str,
) -> list[dict[str, str]]:
    criteria: list[dict[str, str]] = []
    for row in rows:
        criterion = row.get("sharedCriterion")
        if not isinstance(criterion, Mapping):
            continue
        keyword = criterion.get("keyword")
        criterion_id = str(criterion.get("criterionId", ""))
        if not isinstance(keyword, Mapping) or not criterion_id.isdigit():
            continue
        text = keyword.get("text")
        match_type = keyword.get("matchType")
        if not isinstance(text, str) or match_type not in {"EXACT", "PHRASE", "BROAD"}:
            continue
        criteria.append(
            {
                "text": text,
                "match_type": match_type,
                "resource_name": (
                    f"customers/{customer_id}/sharedCriteria/{shared_set_id}~{criterion_id}"
                ),
            }
        )
    return criteria
