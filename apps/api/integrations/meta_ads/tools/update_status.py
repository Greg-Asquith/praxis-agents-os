# apps/api/integrations/meta_ads/tools/update_status.py

"""Approval-only tool that turns Meta campaigns, ad sets, or ads on or off."""

import asyncio
from collections import defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal, localcontext
from typing import Annotated, Any, Literal

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from core.exceptions.integration import IntegrationError, IntegrationFailureDisposition
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_EXTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_EXTERNAL_WRITE,
    TOOL_POLICY_APPROVAL,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.audit_events import (
    AuditStatus,
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    PendingIntegrationOperationDetail,
)
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.context.targeted import run_context_targets
from services.integrations.entity_references import resolve_runtime_references
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)
from utils.metadata import metadata_str

from ..client import MetaAdsClient
from ..operations.list_objects import list_objects
from ..operations.mutations import MetaAdsMutationLedger
from ..operations.update_status import (
    MetaAdsRequestedStatus,
    MetaAdsStatusTarget,
    read_status_targets,
    update_status,
)
from ..operations.values import require_currency
from ..references import MetaAdsAdReference, MetaAdsAdSetReference, MetaAdsCampaignReference
from ..throttle import ensure_account_available
from .schemas.objects import OBJECT_STATUSES, MetaAdsObject, MetaAdsObjectType
from .schemas.status import MetaAdsStatusOutput, MetaAdsStatusSelection
from .utils.bindings import META_ADS_BINDING, META_ADS_WRITE_BINDING, RESULTS_FIELD
from .utils.client import meta_ads_available, meta_ads_client, meta_ads_client_for_principal
from .utils.mutation_evidence import (
    audit_status,
    meta_ads_account_target,
    terminal_operation_detail,
)

_OPERATION = "update_status"
_MAX_OBJECTS = 50
_CLOSED_STATUSES = frozenset({"ARCHIVED", "DELETED"})
_REFERENCE_FIELDS: tuple[tuple[str, str, MetaAdsObjectType], ...] = (
    ("campaigns", "meta_ads_campaign", "campaign"),
    ("ad_sets", "meta_ads_ad_set", "adset"),
    ("ads", "meta_ads_ad", "ad"),
)
_ID_FIELDS: dict[MetaAdsObjectType, str] = {
    "campaign": "campaign_id",
    "adset": "adset_id",
    "ad": "ad_id",
}
_GROUP_KEYS = {"campaign": "campaigns", "adset": "ad-sets", "ad": "ads"}
_ENTITY_TYPES = {"campaign": "meta_ads_campaign", "adset": "meta_ads_ad_set", "ad": "meta_ads_ad"}

type _Reference = MetaAdsCampaignReference | MetaAdsAdSetReference | MetaAdsAdReference


async def meta_ads_update_status(
    ctx: RunContext[RuntimeDeps],
    status: Annotated[
        Literal["ACTIVE", "PAUSED"],
        Field(description="ACTIVE turns the objects on; PAUSED turns them off."),
    ],
    campaigns: Annotated[
        list[MetaAdsCampaignReference] | None,
        Field(min_length=1, max_length=_MAX_OBJECTS, description="Scoped campaigns to change."),
    ] = None,
    ad_sets: Annotated[
        list[MetaAdsAdSetReference] | None,
        Field(min_length=1, max_length=_MAX_OBJECTS, description="Scoped ad sets to change."),
    ] = None,
    ads: Annotated[
        list[MetaAdsAdReference] | None,
        Field(min_length=1, max_length=_MAX_OBJECTS, description="Scoped ads to change."),
    ] = None,
) -> dict[str, Any]:
    references: list[_Reference] = [*(campaigns or ()), *(ad_sets or ()), *(ads or ())]
    if not references:
        raise ModelRetry("Choose at least one Meta Ads campaign, ad set, or ad.")
    if len(references) > _MAX_OBJECTS:
        raise ModelRetry(f"Choose at most {_MAX_OBJECTS} Meta Ads objects per change.")

    async def operation(entry: ResolvedContextEntry, selected: Sequence[_Reference]) -> Any:
        client: MetaAdsClient | None = None
        targets: list[MetaAdsStatusTarget] = []
        pending_detail: PendingIntegrationOperationDetail | None = None

        async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
            nonlocal client, targets, pending_detail
            ensure_account_available(entry.external_id, operation=_OPERATION)
            client = await meta_ads_client(ctx, entry)
            targets = await _live_targets(client, entry, selected)
            pending_detail = _pending_operation_detail(entry, targets, status)
            return pending_detail

        async def execute() -> IntegrationAuditOutcome[dict[str, Any]]:
            if client is None or pending_detail is None or not targets:
                raise RuntimeError("Meta Ads status change preparation did not complete")
            try:
                ledger, refreshed = await update_status(
                    client,
                    account_id=entry.external_id,
                    currency=_currency(entry),
                    targets=targets,
                    status=status,
                )
            except asyncio.CancelledError as exc:
                _attach_cancelled_evidence(exc, pending_detail)
                raise
            detail = terminal_operation_detail(pending_detail, ledger, identity_key="object_id")
            result = _result(entry.external_id, targets, ledger, refreshed, status)
            outcome_status = audit_status(detail)
            return IntegrationAuditOutcome(
                result,
                status=outcome_status,
                external_ref=",".join(ledger.external_refs)[:1000] or None,
                operation_detail=detail,
                unverified_result=result if outcome_status is AuditStatus.UNVERIFIED else None,
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="meta_ads_update_status",
            operation=_OPERATION,
            execute=execute,
            prepare_pending_operation=prepare_pending_operation,
        )

    results = await run_context_targets(
        ctx, binding=META_ADS_WRITE_BINDING, references=references, operation=operation
    )
    return {"results": serialize_fan_out_results(results)}


async def _live_targets(
    client: MetaAdsClient, entry: ResolvedContextEntry, selected: Sequence[_Reference]
) -> list[MetaAdsStatusTarget]:
    object_ids: dict[MetaAdsObjectType, list[str]] = defaultdict(list)
    for reference in selected:
        object_ids[_object_type(reference)].append(reference.provider_entity_id)
    targets, missing = await read_status_targets(
        client, account_id=entry.external_id, currency=_currency(entry), object_ids=object_ids
    )
    if missing:
        raise ModelRetry(
            "Some selected Meta Ads objects are no longer in this ad account. Choose them again."
        )
    if any(target.before.status in _CLOSED_STATUSES for target in targets):
        raise ModelRetry(
            "Archived or deleted Meta Ads objects can't be turned on or off. Remove them."
        )
    return targets


def _object_type(reference: _Reference) -> MetaAdsObjectType:
    if isinstance(reference, MetaAdsCampaignReference):
        return "campaign"
    return "adset" if isinstance(reference, MetaAdsAdSetReference) else "ad"


def _currency(entry: ResolvedContextEntry) -> str:
    return require_currency(
        metadata_str(entry.permissions_metadata.get("currency")), operation=_OPERATION
    )


def _pending_operation_detail(
    entry: ResolvedContextEntry,
    targets: Sequence[MetaAdsStatusTarget],
    status: MetaAdsRequestedStatus,
) -> PendingIntegrationOperationDetail:
    groups: dict[MetaAdsObjectType, list[IntegrationOperationIntent]] = defaultdict(list)
    for target in targets:
        fields = {
            "object_id": target.object_id,
            "object_name": target.before.name,
            "previous_status": target.before.status,
            "previous_effective_status": target.before.effective_status,
            "campaign_status": target.campaign_status,
            "adset_status": target.adset_status,
        }
        groups[target.object_type].append(
            IntegrationOperationIntent(
                fields={key: value for key, value in fields.items() if value is not None}
            )
        )
    return PendingIntegrationOperationDetail(
        target=meta_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key=f"{_GROUP_KEYS[object_type]}:update-status",
                action="update_status",
                entity_type=_ENTITY_TYPES[object_type],
                fields={"status": status},
                items=items,
            )
            for object_type, items in groups.items()
        ],
    )


def _attach_cancelled_evidence(
    exc: asyncio.CancelledError, pending_detail: PendingIntegrationOperationDetail
) -> None:
    ledger: MetaAdsMutationLedger | None = getattr(exc, "ledger", None)
    if ledger is None:
        return
    exc.operation_detail = terminal_operation_detail(
        pending_detail, ledger, identity_key="object_id"
    )
    exc.failure_disposition = (
        IntegrationFailureDisposition.AMBIGUOUS
        if ledger.has_unverified
        else IntegrationFailureDisposition.NOT_DISPATCHED
    )


def _result(
    account_id: str,
    targets: Sequence[MetaAdsStatusTarget],
    ledger: MetaAdsMutationLedger,
    refreshed: Mapping[str, MetaAdsObject | None],
    status: MetaAdsRequestedStatus,
) -> dict[str, Any]:
    parents = {dict(parent.identity)["object_id"]: parent for parent in ledger.parents}
    objects = []
    for target in targets:
        parent = parents[target.object_id]
        effect = parent.effects[0] if parent.effects else None
        # Effects carry the read-back state only when the object was read after the change.
        observed = dict(effect.fields) if effect is not None else {}
        if parent.decision == "skipped":
            # A parent's change can move a skipped object's delivery status; None means unread.
            current = refreshed.get(target.object_id, target.before)
            observed = {
                "status": current.status or "" if current else "",
                "effective_status": current.effective_status or "" if current else "",
            }
        outcome = {"applied": "updated", "skipped": "already_set"}.get(
            parent.outcome, parent.outcome
        )
        objects.append(
            {
                "object_type": target.object_type,
                "object_id": target.object_id,
                "object_name": target.before.name,
                "campaign_id": target.before.campaign_id,
                "adset_id": target.before.adset_id,
                "previous_status": target.before.status,
                "previous_effective_status": target.before.effective_status,
                "status": observed.get("status") or None,
                "effective_status": observed.get("effective_status") or None,
                "outcome": outcome,
                "error_code": effect.error_code if effect is not None else None,
                "message": effect.message if effect is not None else None,
            }
        )
    return {"account_id": account_id, "requested_status": status, "objects": objects}


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Hydrates live object state and, when turning on, what changes in delivery."""
    display = dict(args)
    selected: dict[str, dict[MetaAdsObjectType, list[str]]] = defaultdict(lambda: defaultdict(list))
    reviewed: list[str] = []
    for key, entity_kind, object_type in _REFERENCE_FIELDS:
        values = args.get(key)
        if values is None:
            continue
        if not isinstance(values, list) or not all(isinstance(value, Mapping) for value in values):
            raise TypeError("Meta Ads status approval arguments are invalid")
        display[key] = await resolve_runtime_references(
            deps, entity_kind=entity_kind, field_key=key, values=[dict(v) for v in values]
        )
        for reference in display[key]:
            object_id = str(reference[_ID_FIELDS[object_type]])
            selected[reference["account_id"]][object_type].append(object_id)
            reviewed.append(f"{object_type}:{object_id}")
    # Lets the card tell when an edit has outdated this evidence; resume enforces it separately.
    display["_reviewed_selection"] = {"status": args.get("status"), "objects": reviewed}
    if args.get("status") == "ACTIVE":
        display["_delivery"] = await _delivery_preview(deps, selected)
    return display


async def _delivery_preview(
    deps: RuntimeDeps, selected: Mapping[str, Mapping[MetaAdsObjectType, Sequence[str]]]
) -> dict[str, dict[str, Any]]:
    """Returns, per object ID, which parents keep it off and what starts delivering with it.

    Objects in an account that can't be read are marked unavailable, so the card says so.
    """
    active_context = deps.active_context
    entries = {
        entry.external_id: entry
        for entry in (active_context.compatible_entries(META_ADS_BINDING) if active_context else ())
    }
    preview: dict[str, dict[str, Any]] = {}
    for account_id, object_ids in selected.items():
        entry = entries.get(account_id)
        try:
            if entry is None:
                raise LookupError(account_id)
            client = await meta_ads_client_for_principal(
                deps.db, actor=deps.user, workspace=deps.workspace, entry=entry
            )
            preview.update(
                await _account_delivery(client, account_id, _currency(entry), object_ids)
            )
        except (IntegrationError, LookupError):
            preview.update(
                {item: {"unavailable": True} for ids in object_ids.values() for item in ids}
            )
    return preview


async def _account_delivery(
    client: MetaAdsClient,
    account_id: str,
    currency: str,
    object_ids: Mapping[MetaAdsObjectType, Sequence[str]],
) -> dict[str, dict[str, Any]]:
    """Projects the whole selection turned on, then reports each object's delivery change."""
    targets, _missing = await read_status_targets(
        client, account_id=account_id, currency=currency, object_ids=dict(object_ids)
    )
    turning_on = {item for ids in object_ids.values() for item in ids}
    preview: dict[str, dict[str, Any]] = {}
    starting: list[MetaAdsStatusTarget] = []
    for target in targets:
        blocked = _blocked_by(target, turning_on)
        preview[target.object_id] = {"blocked_by": blocked}
        if target.object_type == "ad" or blocked:
            continue
        # A parent that is already on starts nothing new; its children are counted on their own rows.
        if target.before.status == "ACTIVE":
            preview[target.object_id]["already_on"] = True
        else:
            starting.append(target)
    for parent_type in ("campaign", "adset"):
        if parent_ids := [item.object_id for item in starting if item.object_type == parent_type]:
            children = await _starting_children(
                client, account_id, currency, parent_type, parent_ids, turning_on
            )
            for parent_id, item in children.items():
                preview[parent_id].update(item)
    return preview


def _blocked_by(target: MetaAdsStatusTarget, turning_on: set[str]) -> list[str]:
    """Lists the parents that stay off after this change and so keep the object off."""
    blocked: list[str] = []
    if (
        target.object_type == "ad"
        and target.adset_status != "ACTIVE"
        and target.before.adset_id not in turning_on
    ):
        blocked.append("ad_set")
    if (
        target.object_type != "campaign"
        and target.campaign_status != "ACTIVE"
        and target.before.campaign_id not in turning_on
    ):
        blocked.append("campaign")
    return blocked


async def _starting_children(
    client: MetaAdsClient,
    account_id: str,
    currency: str,
    parent_type: Literal["campaign", "adset"],
    parent_ids: Sequence[str],
    turning_on: set[str],
) -> dict[str, dict[str, Any]]:
    """Counts children that are on, or turned on by this change, under parents being turned on.

    An ad set counted here is enabled, which doesn't prove any of its ads can deliver.
    """
    child_type: MetaAdsObjectType = "adset" if parent_type == "campaign" else "ad"
    children = await list_objects(
        client,
        account_id=account_id,
        object_type=child_type,
        # Every open delivery status, since only the configured status decides what's on.
        statuses=[item for item in OBJECT_STATUSES[child_type] if item not in _CLOSED_STATUSES],
        campaign_ids=list(parent_ids) if parent_type == "campaign" else None,
        adset_ids=list(parent_ids) if parent_type == "adset" else None,
        limit=500,
        currency=currency,
    )
    preview: dict[str, dict[str, Any]] = {}
    for parent_id in parent_ids:
        starting = [
            child
            for child in children.objects
            if getattr(child, _ID_FIELDS[parent_type]) == parent_id
            and (child.status == "ACTIVE" or child.id in turning_on)
        ]
        item: dict[str, Any] = {
            "starting_children": len(starting),
            "children_truncated": children.truncated,
        }
        if parent_type == "campaign":
            item.update(_child_budgets(starting))
        preview[parent_id] = item
    return preview


def _child_budgets(adsets: Sequence[MetaAdsObject]) -> dict[str, Any]:
    """Sums ad set budgets exactly, and flags ad sets whose budget couldn't be read."""
    totals: dict[str, Any] = {
        "budgets_incomplete": any(
            adset.budget is None or adset.budget.amount is None for adset in adsets
        )
    }
    for kind in ("daily", "lifetime"):
        amounts = [
            Decimal(adset.budget.amount)
            for adset in adsets
            if adset.budget and adset.budget.kind == kind and adset.budget.amount
        ]
        # Enough precision for 500 amounts of up to 520 characters, so no digit is rounded.
        with localcontext(prec=1100):
            totals[f"{kind}_budget"] = format(sum(amounts, Decimal(0)), "f") if amounts else None
    return totals


def _reference_field(key: str, label: str, entity_kind: str) -> ToolFieldPresentation:
    # Secondary so an approval can add a family that wasn't proposed, or clear one to null.
    return ToolFieldPresentation(
        key=key,
        label=label,
        format="entity_list",
        editable=True,
        entity_kind=entity_kind,
        secondary=True,
    )


DEFINITION = RuntimeToolDefinition(
    name="meta_ads_update_status",
    function=meta_ads_update_status,
    description=(
        "Turn named Meta campaigns, ad sets, or ads on (ACTIVE) or off (PAUSED), up to 50 "
        "per call across campaigns, ad_sets, and ads. Turning on an object whose campaign "
        "or ad set is off doesn't start delivery. Turning on a campaign or ad set starts "
        "delivery for its children that are already on, and starts spending. Archiving and "
        "deleting aren't supported. Each result reports the status Meta shows after the change."
    ),
    provider="meta_ads",
    label="Update Meta Ads Status",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=120,
    output_model=MetaAdsStatusOutput,
    integration_binding=META_ADS_WRITE_BINDING,
    availability_check=meta_ads_available,
    approval_display_args=_approval_display_args,
    approval_input_model=MetaAdsStatusSelection,
    # An edited selection is re-read before approval, so delivery evidence matches it.
    approval_review_fields=("campaigns", "ad_sets", "ads", "status"),
    presentation=ToolPresentation(
        icon="meta_ads",
        running_label="Updating Meta Ads Status",
        completed_label="Updated Meta Ads Status",
        failed_label="Couldn't Update Meta Ads Status",
        approval_title="Turn Meta Ads On or Off",
        approval_prompt="The agent wants to turn these Meta Ads objects on or off.",
        approve_label="Approve & Update",
        arg_fields=(
            ToolFieldPresentation(
                key="status", label="Status", editable=True, options=("ACTIVE", "PAUSED")
            ),
            _reference_field("campaigns", "Campaigns", "meta_ads_campaign"),
            _reference_field("ad_sets", "Ad Sets", "meta_ads_ad_set"),
            _reference_field("ads", "Ads", "meta_ads_ad"),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
