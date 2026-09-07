# apps/api/integrations/google_ads/operations/create_positive_keywords.py

"""Create positive Google Ads ad-group keyword criteria."""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from ..constants import GOOGLE_ADS_INT64_MAX
from .list_positive_keywords import list_positive_keyword_pairs
from .mutation_outcomes import (
    GoogleAdsMutationLedger,
    GoogleAdsMutationProjection,
    build_mutation_ledger,
    freeze_fields,
)
from .url_custom_parameters import validate_url_custom_parameter_items
from .utils import grouped_partial_failure_errors

type KeywordMatchType = Literal["EXACT", "PHRASE", "BROAD"]

MAX_POSITIVE_KEYWORD_OPERATIONS = 2_500
_RESOURCE_PATTERN = re.compile(
    r"customers/(?P<customer>\d{1,32})/adGroupCriteria/"
    r"(?P<ad_group>\d{1,32})~\d{1,32}"
)
_UNACCOUNTED_CODE = "UNACCOUNTED_OPERATION"
_UNACCOUNTED_MESSAGE = "Google Ads did not account for this submitted operation"


@dataclass(frozen=True, slots=True)
class GoogleAdsPositiveKeywordCreate:
    """One normalized keyword create expanded for a specific ad group."""

    ad_group_id: str
    text: str
    match_type: KeywordMatchType
    cpc_bid_micros: int | None = None
    bid_modifier: float | None = None
    status: Literal["ENABLED", "PAUSED"] = "ENABLED"
    final_urls: tuple[str, ...] = ()
    final_mobile_urls: tuple[str, ...] = ()
    final_url_suffix: str | None = None
    tracking_url_template: str | None = None
    url_custom_parameters: tuple[tuple[str, str], ...] = ()


def positive_keyword_creation_failure_ledger(
    creates: Sequence[GoogleAdsPositiveKeywordCreate],
    *,
    customer_id: str,
    outcome: Literal["failed", "unverified"],
    error_code: str,
    message: str,
    existing_rows: Sequence[Mapping[str, Any]] = (),
) -> GoogleAdsMutationLedger:
    """Accounts for every create when a request has no usable response body."""
    _validate_creates(creates)
    parents = [_identity(item) for item in creates]
    existing = _existing_pairs(existing_rows, customer_id=normalize_customer_id(customer_id))
    skipped_indices: dict[int, str] = {}
    skipped_refs: list[tuple[tuple[tuple[str, str], ...], str]] = []
    submitted = []
    for index, (item, identity) in enumerate(zip(creates, parents, strict=True)):
        key = positive_keyword_pair_key(item.ad_group_id, item.text, item.match_type)
        if resource_name := existing.get(key):
            skipped_indices[index] = "already exists"
            skipped_refs.append((freeze_fields(identity), resource_name))
        else:
            submitted.append((index, identity))
    return _ledger(
        parents,
        skipped_indices=skipped_indices,
        skipped_refs=skipped_refs,
        submitted=submitted,
        outcomes=[(outcome, None, error_code, message) for _ in submitted],
    )


async def create_positive_keywords(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    creates: Sequence[GoogleAdsPositiveKeywordCreate],
    existing_rows: Sequence[Mapping[str, Any]] | None = None,
) -> GoogleAdsMutationLedger:
    """Adds missing positive keyword pairs and records every requested outcome."""
    normalized_customer_id = normalize_customer_id(customer_id)
    _validate_creates(creates)
    if existing_rows is None:
        existing_rows = await list_positive_keyword_pairs(
            client,
            customer_id=normalized_customer_id,
            login_customer_id=login_customer_id,
            keyword_targets=[(item.ad_group_id, item.text, item.match_type) for item in creates],
        )
    existing = _existing_pairs(existing_rows, customer_id=normalized_customer_id)
    parent_fields = [_identity(item) for item in creates]
    skipped_indices, skipped_refs, submitted, operations = _partition_creates(
        creates,
        parent_fields,
        existing,
        customer_id=normalized_customer_id,
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
        operation="create_positive_keywords",
        policy=IntegrationRequestPolicy.MUTATION,
        login_customer_id=login_customer_id,
        json={"operations": operations, "partialFailure": True},
    )
    submitted_values = [fields for _, fields in submitted]
    indexed_errors, unattributed_errors = grouped_partial_failure_errors(
        payload,
        submitted_values,
        value_to_error_fields=lambda fields: fields,
        unattributed_error_fields={"ad_group_id": "", "text": "", "match_type": ""},
        default_message="Positive keyword creation failed",
    )
    outcomes = _creation_outcomes(
        payload.get("results") if isinstance(payload, Mapping) else None,
        submitted_values,
        customer_id=normalized_customer_id,
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


def _partition_creates(
    creates: Sequence[GoogleAdsPositiveKeywordCreate],
    parent_fields: Sequence[dict[str, str]],
    existing: Mapping[tuple[str, str, str], str],
    *,
    customer_id: str,
) -> tuple[
    dict[int, str],
    list[tuple[tuple[tuple[str, str], ...], str]],
    list[tuple[int, dict[str, str]]],
    list[dict[str, Any]],
]:
    skipped_indices: dict[int, str] = {}
    skipped_refs: list[tuple[tuple[tuple[str, str], ...], str]] = []
    submitted: list[tuple[int, dict[str, str]]] = []
    operations: list[dict[str, Any]] = []
    for index, (item, identity) in enumerate(zip(creates, parent_fields, strict=True)):
        resource_name = existing.get(
            positive_keyword_pair_key(item.ad_group_id, item.text, item.match_type)
        )
        if resource_name:
            skipped_indices[index] = "already exists"
            skipped_refs.append((freeze_fields(identity), resource_name))
        else:
            submitted.append((index, identity))
            operations.append({"create": _create_payload(item, customer_id=customer_id)})
    return skipped_indices, skipped_refs, submitted, operations


def _create_payload(item: GoogleAdsPositiveKeywordCreate, *, customer_id: str) -> dict[str, Any]:
    create: dict[str, Any] = {
        "adGroup": f"customers/{customer_id}/adGroups/{item.ad_group_id}",
        "status": item.status,
        "negative": False,
        "keyword": {"text": item.text, "matchType": item.match_type},
    }
    if item.cpc_bid_micros is not None:
        create["cpcBidMicros"] = str(item.cpc_bid_micros)
    if item.bid_modifier is not None:
        create["bidModifier"] = item.bid_modifier
    for field, value in (
        ("finalUrls", item.final_urls),
        ("finalMobileUrls", item.final_mobile_urls),
    ):
        if value:
            create[field] = list(value)
    create.update(
        {
            field: value
            for field, value in (
                ("finalUrlSuffix", item.final_url_suffix),
                ("trackingUrlTemplate", item.tracking_url_template),
            )
            if value is not None
        }
    )
    if item.url_custom_parameters:
        create["urlCustomParameters"] = [
            {"key": key, "value": value} for key, value in item.url_custom_parameters
        ]
    return create


def _existing_pairs(
    rows: Sequence[Mapping[str, Any]], *, customer_id: str
) -> dict[tuple[str, str, str], str]:
    existing: dict[tuple[str, str, str], str] = {}
    for row in rows:
        ad_group = row.get("adGroup")
        criterion = row.get("adGroupCriterion")
        if not isinstance(ad_group, Mapping) or not isinstance(criterion, Mapping):
            continue
        keyword = criterion.get("keyword")
        if not isinstance(keyword, Mapping):
            continue
        ad_group_id = str(ad_group.get("id", ""))
        text = keyword.get("text")
        match_type = keyword.get("matchType")
        resource_name = criterion.get("resourceName")
        resource_match = (
            _RESOURCE_PATTERN.fullmatch(resource_name) if isinstance(resource_name, str) else None
        )
        if (
            ad_group_id.isdigit()
            and isinstance(text, str)
            and match_type in {"EXACT", "PHRASE", "BROAD"}
            and resource_match is not None
            and resource_match.group("customer") == customer_id
            and resource_match.group("ad_group") == ad_group_id
        ):
            existing.setdefault(
                positive_keyword_pair_key(ad_group_id, text, str(match_type)), resource_name
            )
    return existing


def _creation_outcomes(
    results: Any,
    submitted: Sequence[Mapping[str, str]],
    *,
    customer_id: str,
    indexed_errors: Mapping[int, Mapping[str, str]],
    unattributed_errors: Sequence[Mapping[str, str]],
) -> list[tuple[str, str | None, str | None, str | None]]:
    if unattributed_errors:
        diagnostic = unattributed_errors[0]
        return [
            ("unverified", None, diagnostic["error_code"], diagnostic["message"]) for _ in submitted
        ]
    if not isinstance(results, list) or len(results) != len(submitted):
        return [
            (
                "failed" if index in indexed_errors else "unverified",
                None,
                indexed_errors.get(index, {}).get("error_code", _UNACCOUNTED_CODE),
                indexed_errors.get(index, {}).get("message", _UNACCOUNTED_MESSAGE),
            )
            for index in range(len(submitted))
        ]
    outcomes: list[tuple[str, str | None, str | None, str | None]] = []
    seen: set[str] = set()
    for index, (item, fields) in enumerate(zip(results, submitted, strict=True)):
        error = indexed_errors.get(index)
        resource_name = item.get("resourceName") if isinstance(item, Mapping) else None
        if error is not None:
            if resource_name is not None:
                raise ValueError("Google Ads returned contradictory keyword creation evidence")
            outcomes.append(("failed", None, error["error_code"], error["message"]))
            continue
        match = _RESOURCE_PATTERN.fullmatch(str(resource_name))
        if (
            match is None
            or match.group("customer") != customer_id
            or match.group("ad_group") != fields["ad_group_id"]
            or str(resource_name) in seen
        ):
            outcomes.append(("unverified", None, _UNACCOUNTED_CODE, _UNACCOUNTED_MESSAGE))
            continue
        seen.add(str(resource_name))
        outcomes.append(("applied", str(resource_name), None, None))
    return outcomes


def _validate_creates(creates: Sequence[GoogleAdsPositiveKeywordCreate]) -> None:
    if not creates or len(creates) > MAX_POSITIVE_KEYWORD_OPERATIONS:
        raise ValueError("Google Ads positive keyword creates must contain 1-2,500 rows")
    identities: list[tuple[str, str, str]] = []
    for item in creates:
        _validate_create_identity(item)
        _validate_create_bids(item)
        _validate_create_urls(item)
        validate_url_custom_parameter_items(item.url_custom_parameters)
        identities.append(positive_keyword_pair_key(item.ad_group_id, item.text, item.match_type))
    if len(set(identities)) != len(identities):
        raise ValueError("Google Ads positive keyword creates must be unique")


def _validate_create_identity(item: GoogleAdsPositiveKeywordCreate) -> None:
    if (
        not item.ad_group_id.isdigit()
        or item.match_type not in {"EXACT", "PHRASE", "BROAD"}
        or item.status not in {"ENABLED", "PAUSED"}
    ):
        raise ValueError("Google Ads positive keyword create is invalid")
    if not item.text or len(item.text) > 80 or len(item.text.split()) > 10:
        raise ValueError("Google Ads positive keyword text is invalid")


def _validate_create_bids(item: GoogleAdsPositiveKeywordCreate) -> None:
    if item.bid_modifier is not None and not 0.1 <= item.bid_modifier <= 10:
        raise ValueError("Google Ads positive keyword bid adjustment must be between 0.1 and 10")
    if item.cpc_bid_micros is not None and not (0 < item.cpc_bid_micros <= GOOGLE_ADS_INT64_MAX):
        raise ValueError("Google Ads positive keyword CPC bid must be positive")


def _validate_create_urls(item: GoogleAdsPositiveKeywordCreate) -> None:
    if len(item.final_urls) > 10 or len(item.final_mobile_urls) > 10:
        raise ValueError("Google Ads positive keyword URL lists are too long")
    if any(
        len(url) > 2048 or re.fullmatch(r"https?://\S+", url, flags=re.IGNORECASE) is None
        for url in (*item.final_urls, *item.final_mobile_urls)
    ):
        raise ValueError("Google Ads positive keyword final URL is invalid")
    if any(
        value is not None and len(value) > 2048
        for value in (item.final_url_suffix, item.tracking_url_template)
    ):
        raise ValueError("Google Ads positive keyword URL setting is too long")
    if item.tracking_url_template is not None and not item.final_urls:
        raise ValueError(
            "Google Ads positive keyword tracking templates require at least one final URL"
        )


def _identity(item: GoogleAdsPositiveKeywordCreate) -> dict[str, str]:
    fields = {
        "ad_group_id": item.ad_group_id,
        "text": item.text,
        "match_type": item.match_type,
    }
    fields["status"] = item.status
    fields.update(_optional_identity_fields(item))
    return fields


def _optional_identity_fields(item: GoogleAdsPositiveKeywordCreate) -> dict[str, str]:
    fields = {
        key: str(value)
        for key, value in (
            ("bid_modifier", item.bid_modifier),
            ("cpc_bid_micros", item.cpc_bid_micros),
            ("final_url_suffix", item.final_url_suffix),
            ("tracking_url_template", item.tracking_url_template),
        )
        if value is not None
    }
    for key, value in (
        ("final_urls", item.final_urls),
        ("final_mobile_urls", item.final_mobile_urls),
    ):
        if value:
            fields[key] = json.dumps(value, separators=(",", ":"))
    if item.url_custom_parameters:
        fields["url_custom_parameters"] = json.dumps(
            dict(item.url_custom_parameters), separators=(",", ":"), sort_keys=True
        )
    return fields


def positive_keyword_pair_key(ad_group_id: str, text: str, match_type: str) -> tuple[str, str, str]:
    """Returns the provider-equivalent identity for an ad-group keyword pair."""
    return ad_group_id, " ".join(text.split()).casefold(), match_type


def _ledger(
    parent_fields: Sequence[Mapping[str, object]],
    *,
    skipped_indices: Mapping[int, str],
    skipped_refs: Sequence[tuple[tuple[tuple[str, str], ...], str]],
    submitted: Any,
    outcomes: Any,
) -> GoogleAdsMutationLedger:
    ledger = build_mutation_ledger(
        family="ad_group_positive_keywords",
        action="create",
        parent_fields=parent_fields,
        skipped_indices=skipped_indices,
        submitted=submitted,
        outcomes=outcomes,
        projection=GoogleAdsMutationProjection(
            applied_key="added",
            skipped_key="skipped_existing",
            errors_key="keyword_errors",
        ),
    )
    return replace(ledger, skipped_external_refs=tuple(skipped_refs))
