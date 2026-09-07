# apps/api/integrations/google_ads/operations/update_positive_keywords.py

"""Updates mutable Google Ads positive-keyword fields with exact outcome accounting."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from ..constants import GOOGLE_ADS_INT64_MAX
from ..positive_keyword_fields import POSITIVE_KEYWORD_FIELDS, POSITIVE_KEYWORD_MUTABLE_FIELD_PATHS
from .mutation_outcomes import (
    GoogleAdsMutationLedger,
    GoogleAdsMutationProjection,
    build_mutation_ledger,
    freeze_fields,
    reconcile_exact_mutation_outcomes,
)
from .url_custom_parameters import validate_url_custom_parameter_items
from .utils import grouped_partial_failure_errors

MUTABLE_FIELD_PATHS = POSITIVE_KEYWORD_MUTABLE_FIELD_PATHS

_JSON_FIELDS = {field.provider_name: field.json_name for field in POSITIVE_KEYWORD_FIELDS}


@dataclass(frozen=True, slots=True)
class GoogleAdsPositiveKeywordUpdate:
    """One live-verified positive-keyword patch."""

    ad_group_id: str
    criterion_id: str
    previous: Mapping[str, Any]
    requested: Mapping[str, Any]
    requested_fields: tuple[str, ...]


def positive_keyword_update_failure_ledger(
    changes: Sequence[GoogleAdsPositiveKeywordUpdate],
    *,
    outcome: str,
    error_code: str,
    message: str,
) -> GoogleAdsMutationLedger:
    """Accounts for every keyword update when no usable response body exists."""
    if outcome not in {"failed", "unverified"}:
        raise ValueError("Positive keyword update failures must be failed or unverified")
    parent_fields, skipped_indices, submitted = _partition_changes(changes)
    return _ledger(
        parent_fields,
        skipped_indices=skipped_indices,
        skipped_refs=(),
        submitted=submitted,
        outcomes=[(outcome, None, error_code, message) for _ in submitted],
    )


def positive_keyword_update_preflight_ledger(
    changes: Sequence[GoogleAdsPositiveKeywordUpdate],
    *,
    customer_id: str,
    outcome: str,
) -> GoogleAdsMutationLedger:
    """Builds the largest permitted uniform terminal outcome before dispatch."""
    if outcome not in {"applied", "failed", "unverified"}:
        raise ValueError("Positive keyword preflight outcome is invalid")
    normalized_customer_id = normalize_customer_id(customer_id)
    parent_fields, skipped_indices, submitted = _partition_changes(changes)
    outcomes = []
    for parent_index, _identity in submitted:
        change = changes[parent_index]
        if outcome == "applied":
            external_ref = (
                f"customers/{normalized_customer_id}/adGroupCriteria/"
                f"{change.ad_group_id}~{change.criterion_id}"
            )
            outcomes.append(("applied", external_ref, None, None))
        else:
            # A control character occupies six JSON characters, the maximum escape width.
            outcomes.append((outcome, None, "\x00" * 100, "\x00" * 500))
    return _ledger(
        parent_fields,
        skipped_indices=skipped_indices,
        skipped_refs=[
            (
                freeze_fields(parent_fields[index]),
                f"customers/{normalized_customer_id}/adGroupCriteria/"
                f"{changes[index].ad_group_id}~{changes[index].criterion_id}",
            )
            for index in skipped_indices
        ],
        submitted=submitted,
        outcomes=outcomes,
    )


async def update_positive_keywords(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    changes: Sequence[GoogleAdsPositiveKeywordUpdate],
) -> GoogleAdsMutationLedger:
    """Patches explicitly requested fields for up to 500 live positive keywords."""
    normalized_customer_id = normalize_customer_id(customer_id)
    parent_fields, skipped_indices, submitted = _partition_changes(changes)
    skipped_refs: list[tuple[tuple[tuple[str, str], ...], str]] = []
    operations: list[dict[str, Any]] = []
    expected_resource_names: list[str] = []
    for parent_index, identity in enumerate(parent_fields):
        change = changes[parent_index]
        resource_name = (
            f"customers/{normalized_customer_id}/adGroupCriteria/"
            f"{change.ad_group_id}~{change.criterion_id}"
        )
        if parent_index in skipped_indices:
            skipped_refs.append((freeze_fields(identity), resource_name))
            continue
        expected_resource_names.append(resource_name)
        operations.append(
            {
                "update": {
                    "resourceName": resource_name,
                    **{
                        _JSON_FIELDS[field]: change.requested[field]
                        for field in change.requested_fields
                    },
                },
                "updateMask": ",".join(_JSON_FIELDS[field] for field in change.requested_fields),
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
        f"customers/{normalized_customer_id}/adGroupCriteria:mutate",
        operation="update_positive_keywords",
        policy=IntegrationRequestPolicy.MUTATION,
        login_customer_id=login_customer_id,
        json={"operations": operations, "partialFailure": True},
    )
    indexed_errors, unattributed_errors = grouped_partial_failure_errors(
        payload,
        submitted,
        value_to_error_fields=lambda item: item[1],
        unattributed_error_fields={"ad_group_id": "", "criterion_id": ""},
        default_message="Positive keyword update failed",
    )
    results = payload.get("results") if isinstance(payload, dict) else None
    outcomes = reconcile_exact_mutation_outcomes(
        results,
        expected_resource_names=expected_resource_names,
        indexed_errors=indexed_errors,
        unattributed_errors=unattributed_errors,
    )
    return _ledger(
        parent_fields,
        skipped_indices=skipped_indices,
        skipped_refs=skipped_refs,
        submitted=submitted,
        outcomes=outcomes,
    )


def _partition_changes(
    changes: Sequence[GoogleAdsPositiveKeywordUpdate],
) -> tuple[list[dict[str, str]], dict[int, str], list[tuple[int, dict[str, str]]]]:
    if not changes:
        raise ValueError("Google Ads positive keyword updates cannot be empty")
    if len(changes) > 500:
        raise ValueError("Google Ads positive keyword updates accept at most 500 changes")
    parent_fields: list[dict[str, str]] = []
    skipped_indices: dict[int, str] = {}
    submitted: list[tuple[int, dict[str, str]]] = []
    identities: set[tuple[str, str]] = set()
    for change in changes:
        _validate_change(change)
        identity_key = (change.ad_group_id, change.criterion_id)
        if identity_key in identities:
            raise ValueError("Google Ads positive keyword updates must be unique")
        identities.add(identity_key)
        identity = {"ad_group_id": change.ad_group_id, "criterion_id": change.criterion_id}
        parent_index = len(parent_fields)
        parent_fields.append(identity)
        if all(
            change.previous[field] == change.requested[field] for field in change.requested_fields
        ):
            skipped_indices[parent_index] = "already set"
        else:
            submitted.append((parent_index, identity))
    return parent_fields, skipped_indices, submitted


def _validate_change(change: GoogleAdsPositiveKeywordUpdate) -> None:
    if not change.ad_group_id.isdigit() or not change.criterion_id.isdigit():
        raise ValueError("Google Ads positive keyword ids must contain only digits")
    if not change.requested_fields or len(change.requested_fields) != len(
        set(change.requested_fields)
    ):
        raise ValueError("Google Ads positive keyword update fields must be unique and non-empty")
    if any(field not in MUTABLE_FIELD_PATHS for field in change.requested_fields):
        raise ValueError("Google Ads positive keyword update field is not mutable")
    if set(change.previous) != set(MUTABLE_FIELD_PATHS):
        raise ValueError("Google Ads positive keyword previous state is incomplete")
    if set(change.requested) != set(change.requested_fields):
        raise ValueError("Google Ads positive keyword requested state is inconsistent")
    _validate_mutable_state(change.previous, requested=False)
    _validate_mutable_state(change.requested, requested=True)
    validate_positive_keyword_url_update(change)


def validate_positive_keyword_url_update(change: GoogleAdsPositiveKeywordUpdate) -> None:
    """Checks destination dependencies only when their fields change."""
    relevant = {"final_urls", "tracking_url_template"}.intersection(change.requested_fields)
    if not any(change.previous[field] != change.requested[field] for field in relevant):
        return
    effective = {**change.previous, **change.requested}
    if effective["tracking_url_template"] and not effective["final_urls"]:
        raise ValueError("A keyword tracking template requires at least one final URL.")


def _validate_mutable_state(state: Mapping[str, Any], *, requested: bool) -> None:
    _validate_status(state)
    _validate_bid_modifier(state)
    _validate_cpc_bid(state)
    _validate_url_lists(state, requested=requested)
    _validate_url_text(state)
    _validate_custom_parameters(state, requested=requested)


def _validate_status(state: Mapping[str, Any]) -> None:
    if "status" in state and state["status"] not in {"ENABLED", "PAUSED"}:
        raise ValueError("Google Ads positive keyword status is invalid")


def _validate_bid_modifier(state: Mapping[str, Any]) -> None:
    modifier = state.get("bid_modifier")
    if modifier is not None and (
        isinstance(modifier, bool)
        or not isinstance(modifier, int | float)
        or not 0.1 <= modifier <= 10
    ):
        raise ValueError("Google Ads positive keyword bid modifier is invalid")


def _validate_cpc_bid(state: Mapping[str, Any]) -> None:
    cpc_bid = state.get("cpc_bid_micros")
    if cpc_bid is not None and (
        isinstance(cpc_bid, bool)
        or not isinstance(cpc_bid, int)
        or not 0 <= cpc_bid <= GOOGLE_ADS_INT64_MAX
    ):
        raise ValueError("Google Ads positive keyword CPC bid is invalid")


def _validate_url_lists(state: Mapping[str, Any], *, requested: bool) -> None:
    for field in ("final_urls", "final_mobile_urls"):
        value = state.get(field)
        if value is None and requested and field in state:
            raise ValueError(f"Google Ads positive keyword {field} must use an empty list to clear")
        if value is not None and (
            not isinstance(value, list)
            or len(value) > 10
            or any(
                not isinstance(item, str)
                or len(item) > 2048
                or re.fullmatch(r"https?://\S+", item, flags=re.IGNORECASE) is None
                for item in value
            )
        ):
            raise ValueError(f"Google Ads positive keyword {field} is invalid")


def _validate_url_text(state: Mapping[str, Any]) -> None:
    for field in ("final_url_suffix", "tracking_url_template"):
        value = state.get(field)
        if value is not None and (not isinstance(value, str) or len(value) > 2048):
            raise ValueError(f"Google Ads positive keyword {field} is invalid")


def _validate_custom_parameters(state: Mapping[str, Any], *, requested: bool) -> None:
    parameters = state.get("url_custom_parameters")
    if parameters is None and requested and "url_custom_parameters" in state:
        raise ValueError("Google Ads URL custom parameters must use an empty list to clear")
    if parameters is not None:
        if not isinstance(parameters, list):
            raise ValueError("Google Ads URL custom parameters are invalid")
        items: list[tuple[str, str]] = []
        for item in parameters:
            if not isinstance(item, Mapping):
                raise TypeError("Google Ads URL custom parameters are invalid")
            key, value = item.get("key"), item.get("value")
            if not isinstance(key, str) or not isinstance(value, str):
                raise TypeError("Google Ads URL custom parameters are invalid")
            items.append((key, value))
        validate_url_custom_parameter_items(items)


def _ledger(
    parent_fields: Sequence[Mapping[str, object]],
    *,
    skipped_indices: Mapping[int, str],
    skipped_refs: Sequence[tuple[tuple[tuple[str, str], ...], str]],
    submitted: Any,
    outcomes: Any,
) -> GoogleAdsMutationLedger:
    ledger = build_mutation_ledger(
        family="positive_keywords",
        action="update",
        parent_fields=parent_fields,
        skipped_indices=skipped_indices,
        submitted=submitted,
        outcomes=outcomes,
        projection=GoogleAdsMutationProjection(
            applied_key="updated",
            skipped_key="already_set",
            errors_key="keyword_errors",
        ),
    )
    return replace(ledger, skipped_external_refs=tuple(skipped_refs))
