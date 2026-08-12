# apps/api/integrations/google_ads/operations/link_negative_keyword_list.py

"""Link or unlink a negative keyword shared set and selected campaigns."""

from collections.abc import Mapping
from typing import Any, Literal

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
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
) -> dict[str, Any]:
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
    skipped_ids = [
        campaign_id
        for campaign_id in normalized_campaign_ids
        if (campaign_id in linked_campaign_ids) is (action == "LINK")
    ]
    mutation_ids = [
        campaign_id for campaign_id in normalized_campaign_ids if campaign_id not in skipped_ids
    ]
    if not mutation_ids:
        return {
            "resource_names": [],
            skipped_key: skipped_ids,
            "campaign_errors": [],
        }

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
        return {
            "resource_names": [],
            skipped_key: skipped_ids,
            "campaign_errors": [
                _campaign_error(campaign_id, diagnostic) for campaign_id in mutation_ids
            ],
        }
    if not isinstance(results, list) or len(results) != len(mutation_ids):
        return {
            "resource_names": [],
            skipped_key: skipped_ids,
            "campaign_errors": [
                _campaign_error(campaign_id, indexed_errors.get(index))
                for index, campaign_id in enumerate(mutation_ids)
            ],
        }

    resource_names: list[str] = []
    campaign_errors: list[dict[str, str]] = []
    for index, (campaign_id, item) in enumerate(zip(mutation_ids, results, strict=True)):
        error = indexed_errors.get(index)
        resource_name = item.get("resourceName") if isinstance(item, Mapping) else None
        if error is not None:
            campaign_errors.append(error)
        elif isinstance(resource_name, str) and resource_name:
            resource_names.append(resource_name)
        else:
            campaign_errors.append(_campaign_error(campaign_id, None))
    return {
        "resource_names": resource_names,
        skipped_key: skipped_ids,
        "campaign_errors": campaign_errors,
    }


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


def _campaign_error(campaign_id: str, diagnostic: dict[str, str] | None) -> dict[str, str]:
    return {
        "campaign_id": campaign_id,
        "message": (diagnostic["message"] if diagnostic else _UNACCOUNTED_RESPONSE_MESSAGE),
        "error_code": (diagnostic["error_code"] if diagnostic else _UNACCOUNTED_RESPONSE_CODE),
    }
