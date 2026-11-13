# apps/api/integrations/google_ads/operations/build.py

"""The build seam: create related objects in one all-or-nothing request with temporary names."""

import asyncio
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from core.exceptions.integration import (
    IntegrationError,
    IntegrationFailureDisposition,
    IntegrationValidationError,
)

from ..client import GoogleAdsClient, normalize_customer_id
from .mutate import MAX_MUTATE_OPERATIONS, MutateOperation, google_ads_mutate
from .mutation_outcomes import (
    GoogleAdsMutationLedger,
    GoogleAdsMutationOutcome,
    GoogleAdsMutationProjection,
    build_mutation_ledger,
    reconcile_mutation_outcomes,
)

type BuildResource = Literal[
    "campaignBudget",
    "asset",
    "campaign",
    "campaignCriterion",
    "adGroup",
    "adGroupCriterion",
    "adGroupAd",
    "assetGroup",
    "campaignAsset",
    "adGroupAsset",
    "assetGroupAsset",
    "assetGroupSignal",
    "assetGroupListingGroupFilter",
    "audience",
    "campaignConversionGoal",
    "sharedSet",
    "sharedCriterion",
    "campaignSharedSet",
]

# Each resource's collection and its place in the request. A temporary name must be created
# before anything refers to it, so parents come first. Assets come early because ads and
# links can refer to them.
_COLLECTIONS: dict[str, tuple[str, int]] = {
    "campaignBudget": ("campaignBudgets", 0),
    "asset": ("assets", 1),
    "campaign": ("campaigns", 2),
    "campaignCriterion": ("campaignCriteria", 3),
    "adGroup": ("adGroups", 4),
    "adGroupCriterion": ("adGroupCriteria", 5),
    "adGroupAd": ("adGroupAds", 6),
    "assetGroup": ("assetGroups", 7),
    "campaignAsset": ("campaignAssets", 8),
    "adGroupAsset": ("adGroupAssets", 8),
    "assetGroupAsset": ("assetGroupAssets", 8),
    "assetGroupSignal": ("assetGroupSignals", 8),
    "assetGroupListingGroupFilter": ("assetGroupListingGroupFilters", 8),
    # An audience signal's audience names its asset group, and the signal names the audience.
    "audience": ("audiences", 8),
    # Google makes a new campaign's goals with the campaign, so they're updated after it.
    "campaignConversionGoal": ("campaignConversionGoals", 9),
    "sharedSet": ("sharedSets", 1),
    "sharedCriterion": ("sharedCriteria", 3),
    "campaignSharedSet": ("campaignSharedSets", 8),
}
# Objects other operations refer to get a temporary name; Google names the rest.
# Google makes campaign goals with their campaign, so a build only updates them.
_UPDATED = {"campaignConversionGoal"}
# Live objects a build may change in the same request as the objects it creates.
_UPDATABLE = {"campaignConversionGoal", "assetGroup", "audience"}
_REMOVABLE = {"assetGroupAsset", "assetGroupSignal"}
# Removals go last, so an asset group gains its new assets before it loses old ones.
_REMOVAL_RANK = 10
_NAMED = {"campaignBudget", "asset", "campaign", "adGroup", "assetGroup", "audience", "sharedSet"}
_TEMPORARY_NAME = re.compile(r"customers/\d+/[A-Za-z]+/-\d+")
_NOTHING_CREATED = "Google Ads created nothing, because part of the request was rejected."


@dataclass(frozen=True, slots=True)
class BuildStep:
    """One object to create or update. `label` names it for the operator, such as a name."""

    resource: BuildResource
    label: str
    body: Mapping[str, Any]
    temporary_name: str | None
    # What the caller compiled this from, so a rejection can be traced back to it.
    source: Any = None
    # The fields an update sets; None for a create.
    update_mask: str | None = None
    # The live object a removal removes; None for a create or update.
    removed: str | None = None


@dataclass(frozen=True, slots=True)
class BuildProblem:
    """Google's reason a dry run rejected one step, or the whole request when `step` is None."""

    step: BuildStep | None
    message: str


@dataclass(frozen=True, slots=True)
class BuildResult:
    """The ledger for one build, and each temporary name's real resource name."""

    ledger: GoogleAdsMutationLedger
    created: Mapping[str, str]


@dataclass(slots=True)
class CampaignBuild:
    """Collects the objects to create in one account, in the order Google needs them."""

    customer_id: str
    _steps: list[BuildStep] = field(default_factory=list)
    _next_id: int = -1
    _once: dict[str, str | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.customer_id = normalize_customer_id(self.customer_id)

    def create(
        self, resource: BuildResource, body: Mapping[str, Any], *, label: str, source: Any = None
    ) -> str | None:
        """Adds one object and returns its temporary name, for objects others refer to.

        Raises:
            ValueError: When the body refers to a temporary name this build hasn't made.
        """
        if resource not in _COLLECTIONS or resource in _UPDATED:
            raise ValueError("Google Ads builds can't create this resource")
        self._check(body)
        temporary_name = None
        if resource in _NAMED:
            collection = _COLLECTIONS[resource][0]
            temporary_name = f"customers/{self.customer_id}/{collection}/{self._next_id}"
            self._next_id -= 1
            body = {**body, "resourceName": temporary_name}
        self._steps.append(BuildStep(resource, label, body, temporary_name, source))
        return temporary_name

    def update(
        self,
        resource: BuildResource,
        body: Mapping[str, Any],
        *,
        update_mask: str,
        label: str,
        source: Any = None,
    ) -> None:
        """Updates a live object, or one Google makes along with one this build creates."""
        if resource not in _UPDATABLE:
            raise ValueError("Google Ads builds can't update this resource")
        self._check(body)
        self._steps.append(BuildStep(resource, label, body, None, source, update_mask))

    def remove(
        self, resource: BuildResource, resource_name: str, *, label: str, source: Any = None
    ) -> None:
        """Removes a live object in the same request, after everything the build creates."""
        if resource not in _REMOVABLE:
            raise ValueError("Google Ads builds can't remove this resource")
        self._check({})
        self._steps.append(BuildStep(resource, label, {}, None, source, removed=resource_name))

    def _check(self, body: Mapping[str, Any]) -> None:
        if len(self._steps) >= MAX_MUTATE_OPERATIONS:
            raise ValueError("Google Ads builds accept at most 5,000 objects")
        known = {step.temporary_name for step in self._steps}
        if any(name not in known for name in _temporary_names(body)):
            raise ValueError("A Google Ads build step refers to an object it doesn't create")

    def create_once(
        self,
        key: str,
        resource: BuildResource,
        body: Mapping[str, Any],
        *,
        label: str,
        source: Any = None,
    ) -> str | None:
        """Adds the object the first time `key` is seen; later calls get the same name back."""
        if key not in self._once:
            self._once[key] = self.create(resource, body, label=label, source=source)
        return self._once[key]

    @property
    def steps(self) -> list[BuildStep]:
        """The steps in the order they're sent: parents before the objects that refer to them."""
        return sorted(self._steps, key=_rank)

    def operations(self) -> list[MutateOperation]:
        return [_operation(step) for step in self.steps]


def _rank(step: BuildStep) -> int:
    return _REMOVAL_RANK if step.removed is not None else _COLLECTIONS[step.resource][1]


def _operation(step: BuildStep) -> MutateOperation:
    if step.removed is not None:
        return MutateOperation(step.resource, {"remove": step.removed})
    if step.update_mask is not None:
        return MutateOperation(
            step.resource, {"update": dict(step.body), "updateMask": step.update_mask}
        )
    return MutateOperation(step.resource, {"create": dict(step.body)})


async def dry_run_build(
    client: GoogleAdsClient,
    build: CampaignBuild,
    *,
    login_customer_id: str,
    operation: str,
    partial_failure: bool = True,
) -> list[BuildProblem]:
    """Checks the whole build with Google without creating anything.

    Partial failure reports every rejected step rather than only the first. Builds with
    Performance Max asset groups turn it off, because Google refuses it for them.

    Returns:
        Each rejected step with Google's reason, or one problem for the whole request.
    """
    steps = build.steps
    try:
        response = await google_ads_mutate(
            client,
            customer_id=build.customer_id,
            login_customer_id=login_customer_id,
            operations=build.operations(),
            partial_failure=partial_failure,
            validate_only=True,
            operation=operation,
        )
    except IntegrationValidationError as exc:
        return [BuildProblem(None, exc.user_message)]
    problems = [
        BuildProblem(steps[index], error["message"])
        for index, error in sorted(response.indexed_errors.items())
    ]
    problems.extend(BuildProblem(None, error["message"]) for error in response.unattributed_errors)
    return problems


async def send_build(
    client: GoogleAdsClient,
    build: CampaignBuild,
    *,
    login_customer_id: str,
    family: str,
    operation: str,
) -> BuildResult:
    """Creates every step in one atomic request, so either all are created or none are.

    Raises:
        asyncio.CancelledError: With a `ledger` attribute marking every step unverified.
    """
    steps = build.steps
    try:
        response = await google_ads_mutate(
            client,
            customer_id=build.customer_id,
            login_customer_id=login_customer_id,
            operations=build.operations(),
            partial_failure=False,
            validate_only=False,
            operation=operation,
        )
    except asyncio.CancelledError as exc:
        unclear = ("unverified", None, "CANCELLED", "The request was interrupted.")
        exc.ledger = _ledger(family, steps, [unclear] * len(steps))
        raise
    except IntegrationError as exc:
        # Only a request Google never received or rejected outright is known to create nothing.
        unclear = exc.failure_disposition not in {
            IntegrationFailureDisposition.NOT_DISPATCHED,
            IntegrationFailureDisposition.REJECTED,
        }
        outcome: GoogleAdsMutationOutcome = (
            ("unverified", None, exc.error_code or "UNCLEAR_REPLY", exc.user_message)
            if unclear
            else (
                "failed",
                None,
                exc.error_code or "NOTHING_CREATED",
                f"{_NOTHING_CREATED} {exc.user_message}",
            )
        )
        return BuildResult(ledger=_ledger(family, steps, [outcome] * len(steps)), created={})
    outcomes = reconcile_mutation_outcomes(
        response.results,
        operation_count=len(steps),
        indexed_errors=response.indexed_errors,
        unattributed_errors=response.unattributed_errors,
        valid_resource_name=lambda index, name: _created_name(
            build.customer_id, steps[index], name
        ),
    )
    created = {
        step.temporary_name: outcome[1]
        for step, outcome in zip(steps, outcomes, strict=True)
        if step.temporary_name is not None and outcome[0] == "applied" and outcome[1] is not None
    }
    return BuildResult(ledger=_ledger(family, steps, outcomes), created=created)


def _ledger(
    family: str,
    steps: list[BuildStep],
    outcomes: list[GoogleAdsMutationOutcome],
) -> GoogleAdsMutationLedger:
    parent_fields = [
        {"step": str(index), "resource": step.resource, "label": step.label or step.resource}
        for index, step in enumerate(steps)
    ]
    return build_mutation_ledger(
        family=family,
        action="create",
        parent_fields=parent_fields,
        skipped_indices={},
        submitted=list(enumerate(parent_fields)),
        outcomes=outcomes,
        projection=GoogleAdsMutationProjection(
            applied_key="created", skipped_key="skipped", errors_key="errors"
        ),
    )


def _created_name(customer_id: str, step: BuildStep, name: str) -> bool:
    if step.removed is not None:
        return name == step.removed
    collection = _COLLECTIONS[step.resource][0]
    return (
        re.fullmatch(rf"customers/{customer_id}/{collection}/\d+(?:~\d+)*(?:~[A-Z_]+)*", name)
        is not None
    )


def _temporary_names(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value} if _TEMPORARY_NAME.fullmatch(value) else set()
    if isinstance(value, Mapping):
        return set().union(*(_temporary_names(item) for item in value.values()))
    if isinstance(value, list | tuple):
        return set().union(*(_temporary_names(item) for item in value))
    return set()
