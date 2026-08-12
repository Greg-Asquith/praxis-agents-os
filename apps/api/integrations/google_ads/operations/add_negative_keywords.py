# apps/api/integrations/google_ads/operations/add_negative_keywords.py

"""Add keyword criteria to a Google Ads negative keyword shared set."""

from typing import Any

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .utils import grouped_partial_failure_errors, stream_rows

_UNACCOUNTED_RESPONSE_MESSAGE = "Google Ads did not account for this submitted operation"
_UNACCOUNTED_RESPONSE_CODE = "UNACCOUNTED_OPERATION"


async def add_negative_keywords(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    shared_set_id: str,
    keywords: list[dict[str, str]],
) -> dict[str, Any]:
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
    skipped_existing = [
        keyword
        for keyword in keywords
        if (keyword["text"].casefold(), keyword["match_type"]) in existing
    ]
    create_keywords = [
        keyword
        for keyword in keywords
        if (keyword["text"].casefold(), keyword["match_type"]) not in existing
    ]
    if not create_keywords:
        return {
            "added": [],
            "skipped_existing": skipped_existing,
            "keyword_errors": [],
        }

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
    results = payload.get("results") if isinstance(payload, dict) else None
    indexed_errors, unattributed_errors = grouped_partial_failure_errors(
        payload,
        create_keywords,
        value_to_error_fields=lambda keyword: {"scope": "keyword", **keyword},
        unattributed_error_fields={"scope": "account"},
        default_message="Negative keyword creation failed",
    )
    if unattributed_errors:
        diagnostic = unattributed_errors[0]
        return {
            "added": [],
            "skipped_existing": skipped_existing,
            "keyword_errors": [
                _keyword_response_error(
                    keyword,
                    _merge_error_diagnostic(indexed_error, diagnostic)
                    if (indexed_error := indexed_errors.get(index)) is not None
                    else diagnostic,
                )
                for index, keyword in enumerate(create_keywords)
            ],
        }
    if not isinstance(results, list) or len(results) != len(create_keywords):
        return {
            "added": [],
            "skipped_existing": skipped_existing,
            "keyword_errors": [
                _keyword_response_error(keyword, indexed_errors.get(index))
                for index, keyword in enumerate(create_keywords)
            ],
        }

    added: list[dict[str, str]] = []
    keyword_errors: list[dict[str, str]] = []
    for index, (keyword, item) in enumerate(zip(create_keywords, results, strict=True)):
        error = indexed_errors.get(index)
        resource_name = item.get("resourceName") if isinstance(item, dict) else None
        if error is not None:
            keyword_errors.append(error)
        elif isinstance(resource_name, str) and resource_name:
            added.append({**keyword, "resource_name": resource_name})
        else:
            keyword_errors.append(_unaccounted_keyword_error(keyword))

    return {
        "added": added,
        "skipped_existing": skipped_existing,
        "keyword_errors": keyword_errors,
    }


def _unaccounted_keyword_error(keyword: dict[str, str]) -> dict[str, str]:
    return {
        "scope": "keyword",
        **keyword,
        "message": _UNACCOUNTED_RESPONSE_MESSAGE,
        "error_code": _UNACCOUNTED_RESPONSE_CODE,
    }


def _keyword_response_error(
    keyword: dict[str, str], diagnostic: dict[str, str] | None
) -> dict[str, str]:
    if diagnostic is None:
        return _unaccounted_keyword_error(keyword)
    return {
        "scope": "keyword",
        **keyword,
        "message": diagnostic["message"],
        "error_code": diagnostic["error_code"],
    }


def _merge_error_diagnostic(error: dict[str, str], diagnostic: dict[str, str]) -> dict[str, str]:
    messages = list(dict.fromkeys((error["message"], diagnostic["message"])))
    codes = list(dict.fromkeys((error["error_code"], diagnostic["error_code"])))
    return {
        **error,
        "message": " | ".join(messages),
        "error_code": " | ".join(codes),
    }
