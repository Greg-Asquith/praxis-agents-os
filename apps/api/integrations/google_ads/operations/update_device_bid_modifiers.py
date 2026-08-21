# apps/api/integrations/google_ads/operations/update_device_bid_modifiers.py

"""Create or update campaign-level device bid modifiers."""

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any, Literal

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .list_campaign_device_criteria import GoogleAdsCampaignDeviceState
from .mutation_outcomes import (
    GoogleAdsMutationLedger,
    GoogleAdsMutationProjection,
    build_mutation_ledger,
    freeze_fields,
)
from .utils import (
    grouped_partial_failure_errors,
    rounded_bid_modifier,
    valid_exact_mutation_results,
)

type GoogleAdsDevice = Literal["DESKTOP", "MOBILE", "TABLET"]
type GoogleAdsDeviceBidAdjustment = tuple[str, GoogleAdsDevice, float]

_DEVICE_CRITERION_IDS: dict[GoogleAdsDevice, str] = {
    "DESKTOP": "30000",
    "MOBILE": "30001",
    "TABLET": "30002",
}
_UNACCOUNTED_RESPONSE_MESSAGE = "Google Ads did not account for this submitted operation"
_UNACCOUNTED_RESPONSE_CODE = "UNACCOUNTED_OPERATION"


async def update_device_bid_modifiers(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    adjustments: Sequence[GoogleAdsDeviceBidAdjustment],
    existing_state: Mapping[str, GoogleAdsCampaignDeviceState],
) -> GoogleAdsMutationLedger:
    """Updates device bid modifiers with exact create, update, and skip accounting."""
    normalized_customer_id = normalize_customer_id(customer_id)
    parent_fields: list[dict[str, str]] = []
    skipped_indices: dict[int, str] = {}
    skipped_refs: list[tuple[tuple[tuple[str, str], ...], str]] = []
    submitted: list[tuple[int, dict[str, str]]] = []
    operations: list[dict[str, Any]] = []
    expected_resource_names: list[str] = []

    for campaign_id, device, bid_modifier in adjustments:
        if not campaign_id.isdigit():
            raise ValueError("Google Ads campaign ids must contain only digits")
        if device not in _DEVICE_CRITERION_IDS:
            raise ValueError("Google Ads device must be DESKTOP, MOBILE, or TABLET")
        normalized_modifier = rounded_bid_modifier(bid_modifier)
        identity = {
            "campaign_id": campaign_id,
            "device": device,
            "bid_modifier": f"{normalized_modifier:.2f}",
        }
        parent_index = len(parent_fields)
        parent_fields.append(identity)
        current = existing_state.get(campaign_id, {}).get("devices", {}).get(device)
        criterion_id = (
            current["criterion_id"] if current is not None else _DEVICE_CRITERION_IDS[device]
        )
        resource_name = (
            f"customers/{normalized_customer_id}/campaignCriteria/{campaign_id}~{criterion_id}"
        )
        if (
            current is not None
            and rounded_bid_modifier(current["bid_modifier"]) == normalized_modifier
        ):
            skipped_indices[parent_index] = "already set"
            skipped_refs.append((freeze_fields(identity), resource_name))
            continue

        submitted.append((parent_index, identity))
        expected_resource_names.append(resource_name)
        if current is not None:
            operations.append(
                {
                    "update": {
                        "resourceName": resource_name,
                        "bidModifier": float(normalized_modifier),
                    },
                    "updateMask": "bidModifier",
                }
            )
        else:
            operations.append(
                {
                    "create": {
                        "campaign": f"customers/{normalized_customer_id}/campaigns/{campaign_id}",
                        "device": {"type": device},
                        "bidModifier": float(normalized_modifier),
                    }
                }
            )

    if not operations:
        return _ledger(
            parent_fields,
            skipped_indices=skipped_indices,
            skipped_refs=skipped_refs,
            submitted=(),
            outcomes=(),
        )

    payload = await client.post(
        f"customers/{normalized_customer_id}/campaignCriteria:mutate",
        operation="update_device_bid_modifiers",
        policy=IntegrationRequestPolicy.MUTATION,
        login_customer_id=login_customer_id,
        json={"operations": operations, "partialFailure": True},
    )
    indexed_errors, unattributed_errors = grouped_partial_failure_errors(
        payload,
        submitted,
        value_to_error_fields=lambda item: item[1],
        unattributed_error_fields={"campaign_id": "", "device": "", "bid_modifier": ""},
        default_message="Device bid adjustment failed",
    )
    results = payload.get("results") if isinstance(payload, dict) else None
    if unattributed_errors:
        diagnostic = unattributed_errors[0]
        return _ledger(
            parent_fields,
            skipped_indices=skipped_indices,
            skipped_refs=skipped_refs,
            submitted=submitted,
            outcomes=[
                ("unverified", None, diagnostic["error_code"], diagnostic["message"])
                for _ in submitted
            ],
        )
    if not valid_exact_mutation_results(
        results,
        expected_resource_names=expected_resource_names,
        indexed_errors=indexed_errors,
    ):
        return _ledger(
            parent_fields,
            skipped_indices=skipped_indices,
            skipped_refs=skipped_refs,
            submitted=submitted,
            outcomes=[
                (
                    "failed" if index in indexed_errors else "unverified",
                    None,
                    indexed_errors.get(index, {}).get("error_code", _UNACCOUNTED_RESPONSE_CODE),
                    indexed_errors.get(index, {}).get("message", _UNACCOUNTED_RESPONSE_MESSAGE),
                )
                for index in range(len(submitted))
            ],
        )

    outcomes = []
    for index, item in enumerate(results):
        if (error := indexed_errors.get(index)) is not None:
            outcomes.append(("failed", None, error["error_code"], error["message"]))
        else:
            outcomes.append(("applied", item["resourceName"], None, None))
    return _ledger(
        parent_fields,
        skipped_indices=skipped_indices,
        skipped_refs=skipped_refs,
        submitted=submitted,
        outcomes=outcomes,
    )


def _ledger(
    parent_fields: Sequence[Mapping[str, object]],
    *,
    skipped_indices: Mapping[int, str],
    skipped_refs: Sequence[tuple[tuple[tuple[str, str], ...], str]],
    submitted: Any,
    outcomes: Any,
) -> GoogleAdsMutationLedger:
    ledger = build_mutation_ledger(
        family="campaign_device_bid_modifiers",
        action="update",
        parent_fields=parent_fields,
        skipped_indices=skipped_indices,
        submitted=submitted,
        outcomes=outcomes,
        projection=GoogleAdsMutationProjection(
            applied_key="updated",
            skipped_key="already_set",
            errors_key="device_errors",
        ),
    )
    return replace(ledger, skipped_external_refs=tuple(skipped_refs))
