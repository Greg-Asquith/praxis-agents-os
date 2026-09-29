# apps/api/integrations/google_ads/operations/mutate_label_associations.py

"""Apply or remove Google Ads label associations with exact outcome accounting."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from core.exceptions.integration import IntegrationError, IntegrationFailureDisposition
from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .mutation_outcomes import (
    GoogleAdsMutationLedger,
    GoogleAdsMutationOutcome,
    GoogleAdsMutationProjection,
    build_mutation_ledger,
    reconcile_exact_mutation_outcomes,
)
from .utils import grouped_partial_failure_errors, stream_rows

type GoogleAdsLabelTargetKind = Literal["campaign", "ad_group", "keyword"]
type GoogleAdsLabelAssociationAction = Literal["apply", "remove"]

MAX_LABEL_ASSOCIATIONS = 500
_EXISTING_QUERY_BATCH_SIZE = 100


@dataclass(frozen=True, slots=True)
class _AssociationService:
    entity_collection: str
    association_collection: str
    create_field: str
    gaql_resource: str
    row_key: str


# Ordered as submitted, so ledger slots follow this order.
_SERVICES: dict[GoogleAdsLabelTargetKind, _AssociationService] = {
    "campaign": _AssociationService(
        "campaigns", "campaignLabels", "campaign", "campaign_label", "campaignLabel"
    ),
    "ad_group": _AssociationService(
        "adGroups", "adGroupLabels", "adGroup", "ad_group_label", "adGroupLabel"
    ),
    "keyword": _AssociationService(
        "adGroupCriteria",
        "adGroupCriterionLabels",
        "adGroupCriterion",
        "ad_group_criterion_label",
        "adGroupCriterionLabel",
    ),
}


@dataclass(frozen=True, slots=True)
class GoogleAdsLabelAssociation:
    """One label-target pair; keyword target IDs are `ad_group_id~criterion_id`."""

    label_id: str
    target_kind: GoogleAdsLabelTargetKind
    target_id: str

    def identity(self) -> dict[str, str]:
        return {
            "label_id": self.label_id,
            "target_kind": self.target_kind,
            "target_id": self.target_id,
        }


async def mutate_label_associations(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    action: GoogleAdsLabelAssociationAction,
    associations: Sequence[GoogleAdsLabelAssociation],
) -> GoogleAdsMutationLedger:
    """Applies or removes each association, skipping pairs already in the requested state.

    Apply skips existing associations as `already_applied`; remove skips absent
    ones as `not_applied`. Remove never touches the label itself.
    """
    customer = normalize_customer_id(customer_id)
    _validate_associations(associations)
    names = [_association_resource_name(customer, item) for item in associations]
    existing = await _existing_resource_names(
        client, customer=customer, login_customer_id=login_customer_id, associations=associations
    )
    skip_reason = "already_applied" if action == "apply" else "not_applied"
    skipped_indices = {
        index: skip_reason
        for index, name in enumerate(names)
        if (name in existing) is (action == "apply")
    }
    submitted: list[tuple[int, dict[str, str]]] = []
    outcomes: list[GoogleAdsMutationOutcome] = []
    for kind, service in _SERVICES.items():
        indices = [
            index
            for index, item in enumerate(associations)
            if item.target_kind == kind and index not in skipped_indices
        ]
        if not indices:
            continue
        submitted.extend((index, associations[index].identity()) for index in indices)
        outcomes.extend(
            await _mutate_service(
                client,
                customer=customer,
                login_customer_id=login_customer_id,
                action=action,
                service=service,
                associations=[associations[index] for index in indices],
                resource_names=[names[index] for index in indices],
            )
        )
    return build_mutation_ledger(
        family="label_associations",
        action=action,
        parent_fields=[item.identity() for item in associations],
        skipped_indices=skipped_indices,
        submitted=submitted,
        outcomes=outcomes,
        projection=GoogleAdsMutationProjection(
            applied_key="applied" if action == "apply" else "removed",
            skipped_key=skip_reason,
            errors_key="association_errors",
        ),
    )


async def _mutate_service(
    client: GoogleAdsClient,
    *,
    customer: str,
    login_customer_id: str,
    action: GoogleAdsLabelAssociationAction,
    service: _AssociationService,
    associations: Sequence[GoogleAdsLabelAssociation],
    resource_names: Sequence[str],
) -> list[GoogleAdsMutationOutcome]:
    operations = [
        {
            "create": {
                service.create_field: f"customers/{customer}/{service.entity_collection}/"
                f"{item.target_id}",
                "label": f"customers/{customer}/labels/{item.label_id}",
            }
        }
        if action == "apply"
        else {"remove": name}
        for item, name in zip(associations, resource_names, strict=True)
    ]
    try:
        payload = await client.post(
            f"customers/{customer}/{service.association_collection}:mutate",
            operation=f"{action}_labels",
            policy=IntegrationRequestPolicy.MUTATION,
            login_customer_id=login_customer_id,
            json={"operations": operations, "partialFailure": True},
        )
    except Exception as exc:
        # Earlier services may have applied, so record this service's slots instead of raising.
        return _request_failure_outcomes(exc, len(operations))
    indexed_errors, unattributed_errors = grouped_partial_failure_errors(
        payload,
        list(associations),
        value_to_error_fields=lambda item: item.identity(),
        unattributed_error_fields={"label_id": "", "target_kind": "", "target_id": ""},
        default_message="Label update failed",
    )
    return reconcile_exact_mutation_outcomes(
        payload.get("results") if isinstance(payload, dict) else None,
        expected_resource_names=resource_names,
        indexed_errors=indexed_errors,
        unattributed_errors=unattributed_errors,
    )


def _request_failure_outcomes(exc: Exception, count: int) -> list[GoogleAdsMutationOutcome]:
    disposition = getattr(exc, "failure_disposition", IntegrationFailureDisposition.AMBIGUOUS)
    outcome = (
        "failed" if disposition is IntegrationFailureDisposition.NOT_DISPATCHED else "unverified"
    )
    raw_message = exc.user_message if isinstance(exc, IntegrationError) else str(exc)
    message = " ".join(raw_message.split())[:1000] or "Label update failed"
    return [(outcome, None, exc.__class__.__name__[:100], message)] * count


async def _existing_resource_names(
    client: GoogleAdsClient,
    *,
    customer: str,
    login_customer_id: str,
    associations: Sequence[GoogleAdsLabelAssociation],
) -> set[str]:
    existing: set[str] = set()
    for kind, service in _SERVICES.items():
        names = [
            _association_resource_name(customer, item)
            for item in associations
            if item.target_kind == kind
        ]
        for start in range(0, len(names), _EXISTING_QUERY_BATCH_SIZE):
            batch = names[start : start + _EXISTING_QUERY_BATCH_SIZE]
            resource = service.gaql_resource
            query = (
                f"SELECT {resource}.resource_name FROM {resource} "  # noqa: S608 -- fixed resources and digit-only ids
                f"WHERE {resource}.resource_name IN ({', '.join(f"'{name}'" for name in batch)})"
            )
            payload = await client.post(
                f"customers/{customer}/googleAds:searchStream",
                operation="list_label_associations",
                policy=IntegrationRequestPolicy.READ,
                login_customer_id=login_customer_id,
                json={"query": query},
            )
            existing.update(
                str(row[service.row_key].get("resourceName", ""))
                for row in stream_rows(payload)
                if isinstance(row.get(service.row_key), dict)
            )
    return existing


def _association_resource_name(customer: str, item: GoogleAdsLabelAssociation) -> str:
    collection = _SERVICES[item.target_kind].association_collection
    return f"customers/{customer}/{collection}/{item.target_id}~{item.label_id}"


def _validate_associations(associations: Sequence[GoogleAdsLabelAssociation]) -> None:
    if not associations or len(associations) > MAX_LABEL_ASSOCIATIONS:
        raise ValueError(
            f"Google Ads label changes require 1 to {MAX_LABEL_ASSOCIATIONS} associations"
        )
    if len(set(associations)) != len(associations):
        raise ValueError("Google Ads label associations must be unique")
    for item in associations:
        parts = item.target_id.split("~")
        if item.target_kind not in _SERVICES or len(parts) != (
            2 if item.target_kind == "keyword" else 1
        ):
            raise ValueError("Google Ads label association target is invalid")
        if any(not value.isascii() or not value.isdigit() for value in (item.label_id, *parts)):
            raise ValueError("Google Ads label association ids must contain only digits")
