# apps/api/integrations/google_ads/operations/add_negative_keywords.py

"""Add keyword criteria to a Google Ads negative keyword shared set."""

import re

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .mutation_outcomes import (
    SHARED_SET_KEYWORD_MUTATION_SPEC,
    GoogleAdsMutationLedger,
    build_keyword_mutation_ledger,
    reconcile_created_mutation_outcomes,
)
from .utils import grouped_partial_failure_errors, stream_rows


async def add_negative_keywords(
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
    existing = {
        (str(keyword.get("text", "")).casefold(), str(keyword.get("matchType", "")))
        for row in stream_rows(existing_payload)
        if isinstance((criterion := row.get("sharedCriterion")), dict)
        and isinstance((keyword := criterion.get("keyword")), dict)
    }
    skipped_indices = {
        index: "already_exists"
        for index, keyword in enumerate(keywords)
        if (keyword["text"].casefold(), keyword["match_type"]) in existing
    }
    submitted = [
        (index, keyword) for index, keyword in enumerate(keywords) if index not in skipped_indices
    ]
    create_keywords = [keyword for _, keyword in submitted]
    if not create_keywords:
        return build_keyword_mutation_ledger(
            spec=SHARED_SET_KEYWORD_MUTATION_SPEC,
            action="add",
            parent_fields=keywords,
            skipped_indices=skipped_indices,
            submitted=(),
            outcomes=(),
        )

    payload = await client.post(
        f"customers/{normalized_customer_id}/sharedCriteria:mutate",
        operation="add_negative_keywords",
        policy=IntegrationRequestPolicy.MUTATION,
        login_customer_id=login_customer_id,
        json={
            "operations": [
                {
                    "create": {
                        "sharedSet": shared_set,
                        "keyword": {
                            "text": keyword["text"],
                            "matchType": keyword["match_type"],
                        },
                    }
                }
                for keyword in create_keywords
            ],
            "partialFailure": True,
        },
    )
    indexed_errors, unattributed_errors = grouped_partial_failure_errors(
        payload,
        create_keywords,
        value_to_error_fields=lambda keyword: {"scope": "keyword", **keyword},
        unattributed_error_fields={"scope": "account"},
        default_message="Negative keyword creation failed",
    )
    outcomes = reconcile_created_mutation_outcomes(
        payload.get("results") if isinstance(payload, dict) else None,
        resource_pattern=re.compile(
            rf"customers/{normalized_customer_id}/sharedCriteria/{shared_set_id}~\d+"
        ),
        operation_count=len(create_keywords),
        indexed_errors=indexed_errors,
        unattributed_errors=unattributed_errors,
    )
    return build_keyword_mutation_ledger(
        spec=SHARED_SET_KEYWORD_MUTATION_SPEC,
        action="add",
        parent_fields=keywords,
        skipped_indices=skipped_indices,
        submitted=submitted,
        outcomes=outcomes,
    )
