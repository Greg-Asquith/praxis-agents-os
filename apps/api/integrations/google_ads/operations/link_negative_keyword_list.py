# apps/api/integrations/google_ads/operations/link_negative_keyword_list.py

"""Link or unlink a negative keyword shared set and selected campaigns."""

from collections.abc import Mapping
from typing import Any, Literal

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .mutation_outcomes import (
    GoogleAdsMutationLedger,
    GoogleAdsMutationProjection,
    build_mutation_ledger,
)
from .utils import grouped_partial_failure_errors, stream_rows

_UNACCOUNTED_RESPONSE_MESSAGE = "Google Ads did not account for this submitted operation"
_UNACCOUNTED_RESPONSE_CODE = "UNACCOUNTED_OPERATION"


async def link_negative_keyword_list(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    shared_set_id: str,
    campaign_ids: list[str],
    action: Literal["LINK", "UNLINK"],
) -> GoogleAdsMutationLedger:
    normalized_customer_id = normalize_customer_id(customer_id)
    if not shared_set_id.isdigit():
        raise ValueError("Google Ads shared set id must contain only digits")
    normalized_campaign_ids = list(
        dict.fromkeys(normalize_customer_id(campaign_id) for campaign_id in campaign_ids)
    )
    shared_set = f"customers/{normalized_customer_id}/sharedSets/{shared_set_id}"
    existing_query = (
        "SELECT campaign_shared_set.campaign, campaign_shared_set.shared_set, "  # noqa: S608 -- normalized customer and digit-only shared set ids
        "campaign_shared_set.status "
        "FROM campaign_shared_set "
        f"WHERE campaign_shared_set.shared_set = '{shared_set}' "
        "AND campaign_shared_set.status = 'ENABLED'"
    )
    existing_payload = await client.post(
        f"customers/{normalized_customer_id}/googleAds:searchStream",
        operation="list_negative_keyword_list_campaign_links",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={"query": existing_query},
    )
    linked_campaign_ids = _linked_campaign_ids(stream_rows(existing_payload), shared_set=shared_set)
    skipped_key = "skipped_existing" if action == "LINK" else "not_found"
    skipped_indices = {
        index: "already_linked" if action == "LINK" else "not_linked"
        for index, campaign_id in enumerate(normalized_campaign_ids)
        if (campaign_id in linked_campaign_ids) is (action == "LINK")
    }
    submitted = [
        (index, {"campaign_id": campaign_id})
        for index, campaign_id in enumerate(normalized_campaign_ids)
        if index not in skipped_indices
    ]
    mutation_ids = [fields["campaign_id"] for _, fields in submitted]
    if not mutation_ids:
        return _ledger(
            normalized_campaign_ids,
            action=action,
            skipped_key=skipped_key,
            skipped_indices=skipped_indices,
            submitted=(),
            outcomes=(),
        )

    payload = await client.post(
        f"customers/{normalized_customer_id}/campaignSharedSets:mutate",
        operation="link_negative_keyword_list",
        policy=IntegrationRequestPolicy.MUTATION,
        login_customer_id=login_customer_id,
        json={
            "operations": [
                _mutation_operation(
                    customer_id=normalized_customer_id,
                    campaign_id=campaign_id,
                    shared_set_id=shared_set_id,
                    shared_set=shared_set,
                    action=action,
                )
                for campaign_id in mutation_ids
            ],
            "partialFailure": True,
        },
    )
    indexed_errors, unattributed_errors = grouped_partial_failure_errors(
        payload,
        mutation_ids,
        value_to_error_fields=lambda campaign_id: {"campaign_id": campaign_id},
        unattributed_error_fields={"campaign_id": ""},
        default_message="Negative keyword list campaign update failed",
    )
    results = payload.get("results") if isinstance(payload, dict) else None
    if unattributed_errors:
        diagnostic = unattributed_errors[0]
        return _ledger(
            normalized_campaign_ids,
            action=action,
            skipped_key=skipped_key,
            skipped_indices=skipped_indices,
            submitted=submitted,
            outcomes=[
                ("unverified", None, diagnostic["error_code"], diagnostic["message"])
                for _ in mutation_ids
            ],
        )
    if not isinstance(results, list) or len(results) != len(mutation_ids):
        return _ledger(
            normalized_campaign_ids,
            action=action,
            skipped_key=skipped_key,
            skipped_indices=skipped_indices,
            submitted=submitted,
            outcomes=[
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
                for index in range(len(mutation_ids))
            ],
        )

    outcomes = []
    for index, (_campaign_id, item) in enumerate(zip(mutation_ids, results, strict=True)):
        error = indexed_errors.get(index)
        resource_name = item.get("resourceName") if isinstance(item, Mapping) else None
        if error is not None:
            if resource_name is not None:
                raise ValueError("Google Ads returned contradictory campaign link evidence")
            outcomes.append(("failed", None, error["error_code"], error["message"]))
        elif isinstance(resource_name, str) and resource_name:
            outcomes.append(("applied", resource_name, None, None))
        else:
            outcomes.append(
                ("unverified", None, _UNACCOUNTED_RESPONSE_CODE, _UNACCOUNTED_RESPONSE_MESSAGE)
            )
    return _ledger(
        normalized_campaign_ids,
        action=action,
        skipped_key=skipped_key,
        skipped_indices=skipped_indices,
        submitted=submitted,
        outcomes=outcomes,
    )


def _ledger(
    campaign_ids: list[str],
    *,
    action: Literal["LINK", "UNLINK"],
    skipped_key: str,
    skipped_indices: dict[int, str],
    submitted: Any,
    outcomes: Any,
) -> GoogleAdsMutationLedger:
    return build_mutation_ledger(
        family="campaign_shared_set_links",
        action=action.lower(),
        parent_fields=[{"campaign_id": campaign_id} for campaign_id in campaign_ids],
        skipped_indices=skipped_indices,
        submitted=submitted,
        outcomes=outcomes,
        projection=GoogleAdsMutationProjection(
            applied_key="applied",
            skipped_key=skipped_key,
            errors_key="campaign_errors",
        ),
    )


def _linked_campaign_ids(rows: list[dict[str, Any]], *, shared_set: str) -> set[str]:
    campaign_ids: set[str] = set()
    for row in rows:
        link = row.get("campaignSharedSet")
        if (
            not isinstance(link, Mapping)
            or link.get("sharedSet") != shared_set
            or link.get("status") != "ENABLED"
        ):
            continue
        campaign = link.get("campaign")
        if not isinstance(campaign, str):
            continue
        campaign_id = campaign.rsplit("/", 1)[-1]
        if campaign_id.isdigit():
            campaign_ids.add(campaign_id)
    return campaign_ids


def _mutation_operation(
    *,
    customer_id: str,
    campaign_id: str,
    shared_set_id: str,
    shared_set: str,
    action: Literal["LINK", "UNLINK"],
) -> dict[str, Any]:
    if action == "LINK":
        return {
            "create": {
                "campaign": f"customers/{customer_id}/campaigns/{campaign_id}",
                "sharedSet": shared_set,
            }
        }
    return {"remove": (f"customers/{customer_id}/campaignSharedSets/{campaign_id}~{shared_set_id}")}
