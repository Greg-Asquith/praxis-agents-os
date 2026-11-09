# apps/api/integrations/google_ads/operations/edits.py

"""The edit seam: change settings on live objects, checked before approval and read back after."""

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from core.exceptions.integration import (
    IntegrationError,
    IntegrationFailureDisposition,
    IntegrationValidationError,
)

from ..client import GoogleAdsClient
from .mutate import MutateOperation, google_ads_mutate
from .mutation_outcomes import (
    GoogleAdsMutationLedger,
    GoogleAdsMutationOutcome,
    GoogleAdsMutationProjection,
    build_mutation_ledger,
    reconcile_mutation_outcomes,
)

# Field paths in Google's JSON names, dotted when nested, such as `shoppingSetting.feedLabel`.
type SettingValues = Mapping[str, Any]
# Reads the live values of each edit's object, keyed by `Edit.key`. A missing key means the
# object doesn't exist. For a criterion, the values are `{"resourceName": ...}`.
type ReadState = Callable[[Sequence["Edit"]], Awaitable[Mapping[str, SettingValues]]]

STALE_CODE = "CHANGED_SINCE_APPROVAL"
ALREADY_SET = "already_set"
_STALE_MESSAGE = (
    "This changed in Google Ads after the request was approved. Ask again to see it now."
)
_MISSING_MESSAGE = "This no longer exists in Google Ads."
_NOT_CONFIRMED = "Google Ads accepted the change, but {settings} still shows a different value."
_DRY_RUN_FAILED = "Google Ads rejected this change"


@dataclass(frozen=True, slots=True)
class FieldChange:
    """New values for some settings of one object, such as a campaign's status.

    `before` is filled from the live object by `prepare_edits`.
    """

    # The mutate resource type, such as `campaign`, `adGroup`, or `adGroupAd`.
    resource: str
    resource_name: str
    requested: SettingValues
    before: SettingValues = field(default_factory=dict)
    # Why the change mustn't be sent, such as Google rejecting it in the dry run.
    refused: str | None = None

    @property
    def key(self) -> str:
        return self.resource_name

    @property
    def changed_fields(self) -> tuple[str, ...]:
        return tuple(
            path for path, value in self.requested.items() if self.before.get(path) != value
        )

    @property
    def unchanged(self) -> bool:
        return not self.changed_fields

    @property
    def settings(self) -> str:
        return ",".join(self.requested)

    def operation(self) -> MutateOperation:
        changed = self.changed_fields
        update: dict[str, Any] = {"resourceName": self.resource_name}
        for path in changed:
            _set_path(update, path, self.requested[path])
        return MutateOperation(self.resource, {"update": update, "updateMask": ",".join(changed)})

    def live(self, values: SettingValues | None) -> SettingValues | None:
        return None if values is None else {path: values.get(path) for path in self.requested}

    def produces(self, resource_name: str) -> bool:
        return resource_name == self.resource_name


@dataclass(frozen=True, slots=True)
class CriterionChange:
    """Adds or removes one criterion, such as a location, audience, or negative keyword.

    A criterion's value can't be updated, so changing one is a remove plus an add.
    """

    # `campaignCriterion` or `adGroupCriterion`.
    resource: str
    action: Literal["add", "remove"]
    # A stable name for the criterion on its owner, such as `campaigns/1/location/2826`.
    key: str
    # The campaign or ad group resource name the criterion belongs to.
    owner: str
    # The create body for an add, without a resource name.
    criterion: Mapping[str, Any] = field(default_factory=dict)
    # The criterion's resource name when it exists, filled by `prepare_edits`.
    before: str | None = None
    refused: str | None = None

    def __post_init__(self) -> None:
        if (self.action == "add") != bool(self.criterion):
            raise ValueError("Only an added Google Ads criterion has a create body")

    @property
    def unchanged(self) -> bool:
        return (self.before is not None) == (self.action == "add")

    @property
    def settings(self) -> str:
        return self.action

    def operation(self) -> MutateOperation:
        if self.action == "remove":
            return MutateOperation(self.resource, {"remove": self.before})
        return MutateOperation(self.resource, {"create": dict(self.criterion)})

    def live(self, values: SettingValues | None) -> str | None:
        name = values.get("resourceName") if values is not None else None
        return name if isinstance(name, str) and name else None

    def produces(self, resource_name: str) -> bool:
        if self.action == "remove":
            return resource_name == self.before
        # The owner is `customers/{customer}/{campaigns or adGroups}/{id}`.
        _customers, customer_id, _owners, owner_id = self.owner.split("/")
        collection = (
            "campaignCriteria" if self.resource == "campaignCriterion" else "adGroupCriteria"
        )
        prefix = f"customers/{customer_id}/{collection}/{owner_id}~"
        return resource_name.startswith(prefix) and resource_name[len(prefix) :].isdigit()


type Edit = FieldChange | CriterionChange


@dataclass(frozen=True, slots=True)
class EditResult:
    """The ledger for one account's edits, and each object's values read back after them."""

    ledger: GoogleAdsMutationLedger
    after: Mapping[str, SettingValues]


async def prepare_edits(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    edits: Sequence[Edit],
    read: ReadState,
    operation: str,
) -> list[Edit]:
    """Fills each edit's live values and checks the real changes with Google without making them.

    An edit whose object is gone, or that Google rejects, comes back with `refused` set, so
    the approval card can show it as a problem. Edits already at their requested values
    aren't checked.
    """
    _require_unique(edits)
    live = await read(edits)
    prepared: list[Edit] = []
    for edit in edits:
        values = live.get(edit.key)
        if isinstance(edit, FieldChange):
            if values is None:
                prepared.append(replace(edit, refused=_MISSING_MESSAGE))
                continue
            prepared.append(replace(edit, before=edit.live(values) or {}))
        else:
            prepared.append(replace(edit, before=edit.live(values)))
    checked = [
        index for index, edit in enumerate(prepared) if edit.refused is None and not edit.unchanged
    ]
    if not checked:
        return prepared
    try:
        response = await google_ads_mutate(
            client,
            customer_id=customer_id,
            login_customer_id=login_customer_id,
            operations=[prepared[index].operation() for index in checked],
            partial_failure=True,
            validate_only=True,
            operation=operation,
        )
    except IntegrationValidationError as exc:
        return [
            replace(edit, refused=exc.user_message) if index in checked else edit
            for index, edit in enumerate(prepared)
        ]
    for slot, index in enumerate(checked):
        error = response.indexed_errors.get(slot)
        if error is None and response.unattributed_errors:
            error = response.unattributed_errors[0]
        if error is not None:
            prepared[index] = replace(prepared[index], refused=error["message"] or _DRY_RUN_FAILED)
    return prepared


async def apply_edits(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    edits: Sequence[Edit],
    read: ReadState,
    family: str,
    operation: str,
) -> EditResult:
    """Applies approved edits for one account in one request, then reads each object back.

    An object whose live values differ from the approved `before` values is refused as
    changed since approval. Edits already at their values are skipped as already set.
    Refused edits from preparation are recorded as failed and never sent.

    Raises:
        asyncio.CancelledError: With a `ledger` attribute marking the sent edits unverified.
    """
    _require_unique(edits)
    live = await read(edits)
    refusals = {
        edit.key: edit.refused or _STALE_MESSAGE
        for edit in edits
        if edit.refused is not None or edit.live(live.get(edit.key)) != edit.before
    }
    sent = [edit for edit in edits if edit.key not in refusals and not edit.unchanged]
    try:
        outcomes = await _send(
            client,
            customer_id=customer_id,
            login_customer_id=login_customer_id,
            sent=sent,
            operation=operation,
        )
    except asyncio.CancelledError as exc:
        unclear = [("unverified", None, "CANCELLED", "The change was interrupted.")] * len(sent)
        exc.ledger = _ledger(family, edits, refusals, sent, unclear)
        raise
    after: dict[str, SettingValues] = {}
    read_back = False
    if sent:
        # A failed read keeps Google's reply as the outcome, with no read-back values.
        with contextlib.suppress(IntegrationError):
            after.update(await read(sent))
            read_back = True
    checked = [
        _checked_outcome(edit, outcome, after.get(edit.key), read_back=read_back)
        for edit, outcome in zip(sent, outcomes, strict=True)
    ]
    return EditResult(ledger=_ledger(family, edits, refusals, sent, checked), after=after)


async def _send(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    sent: Sequence[Edit],
    operation: str,
) -> list[GoogleAdsMutationOutcome]:
    if not sent:
        return []
    try:
        response = await google_ads_mutate(
            client,
            customer_id=customer_id,
            login_customer_id=login_customer_id,
            operations=[edit.operation() for edit in sent],
            partial_failure=True,
            validate_only=False,
            operation=operation,
        )
    except IntegrationError as exc:
        # Only a request Google never received or rejected outright changed nothing for sure.
        unclear = exc.failure_disposition not in {
            IntegrationFailureDisposition.NOT_DISPATCHED,
            IntegrationFailureDisposition.REJECTED,
        }
        code = exc.error_code or ("UNCLEAR_REPLY" if unclear else "REQUEST_REJECTED")
        return [("unverified" if unclear else "failed", None, code, exc.user_message)] * len(sent)
    return reconcile_mutation_outcomes(
        response.results,
        operation_count=len(sent),
        indexed_errors=response.indexed_errors,
        unattributed_errors=response.unattributed_errors,
        valid_resource_name=lambda index, name: sent[index].produces(name),
    )


def _checked_outcome(
    edit: Edit,
    outcome: GoogleAdsMutationOutcome,
    after: SettingValues | None,
    *,
    read_back: bool,
) -> GoogleAdsMutationOutcome:
    """Settles an unclear reply from the read-back, and fails a change the read-back contradicts."""
    state = outcome[0]
    if state == "failed" or not read_back:
        return outcome
    if isinstance(edit, CriterionChange):
        present = edit.live(after)
        if edit.action == "add" and present is not None:
            return ("applied", present, None, None)
        if edit.action == "remove" and present is None and edit.before is not None:
            return ("applied", edit.before, None, None)
        return outcome if state == "unverified" else _not_confirmed(f"the {edit.action}")
    values = edit.live(after) or {}
    different = [path for path, value in edit.requested.items() if values.get(path) != value]
    if not different:
        return ("applied", edit.resource_name, None, None)
    return outcome if state == "unverified" else _not_confirmed(", ".join(different))


def _not_confirmed(settings: str) -> GoogleAdsMutationOutcome:
    return ("failed", None, "SETTING_NOT_CONFIRMED", _NOT_CONFIRMED.format(settings=settings))


def _ledger(
    family: str,
    edits: Sequence[Edit],
    refusals: Mapping[str, str],
    sent: Sequence[Edit],
    sent_outcomes: Sequence[GoogleAdsMutationOutcome],
) -> GoogleAdsMutationLedger:
    sent_outcome = {edit.key: outcome for edit, outcome in zip(sent, sent_outcomes, strict=True)}
    parent_fields = [{"object": edit.key, "settings": edit.settings} for edit in edits]
    skipped: dict[int, str] = {}
    submitted: list[tuple[int, Mapping[str, object]]] = []
    outcomes: list[GoogleAdsMutationOutcome] = []
    for index, edit in enumerate(edits):
        if edit.key in refusals:
            code = "REFUSED" if edit.refused is not None else STALE_CODE
            submitted.append((index, parent_fields[index]))
            outcomes.append(("failed", None, code, refusals[edit.key]))
        elif edit.key in sent_outcome:
            submitted.append((index, parent_fields[index]))
            outcomes.append(sent_outcome[edit.key])
        else:
            skipped[index] = ALREADY_SET
    return build_mutation_ledger(
        family=family,
        action="update",
        parent_fields=parent_fields,
        skipped_indices=skipped,
        submitted=submitted,
        outcomes=outcomes,
        projection=GoogleAdsMutationProjection(
            applied_key="updated", skipped_key=ALREADY_SET, errors_key="errors"
        ),
    )


def _require_unique(edits: Sequence[Edit]) -> None:
    if not edits:
        raise ValueError("Google Ads edits cannot be empty")
    keys = [edit.key for edit in edits]
    if len(set(keys)) != len(keys):
        raise ValueError("Google Ads edits must name each object once")


def _set_path(body: dict[str, Any], path: str, value: Any) -> None:
    *parents, leaf = path.split(".")
    for part in parents:
        body = body.setdefault(part, {})
    body[leaf] = value
