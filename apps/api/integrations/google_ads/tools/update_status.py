# apps/api/integrations/google_ads/tools/update_status.py

"""Approval-only tool that turns Google Ads campaigns, ad groups, ads, keywords, or asset groups on or off."""

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import replace
from typing import Annotated, Any

from pydantic import Field, ValidationError
from pydantic_ai import ModelRetry, RunContext

from core.exceptions.integration import IntegrationError
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
from services.integrations.approved_display_args import approved_display_args, proposed_args
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.context.targeted import run_context_targets
from services.integrations.entity_references import ScopedEntityReference
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..client import GoogleAdsClient
from ..operations.edits import Edit, EditResult, FieldChange, apply_edits, prepare_edits
from ..operations.read_status import LiveStatus, read_statuses
from .schemas.status import (
    MAX_STATUS_CHANGES,
    GoogleAdsStatusChange,
    GoogleAdsUpdateStatusOutput,
    GoogleAdsUpdateStatusRequest,
)
from .utils.accounts import NOT_SHOWN, approval_accounts, writable_entries
from .utils.bindings import GOOGLE_ADS_WRITE_BINDING, RESULTS_FIELD
from .utils.client import google_ads_available, google_ads_client, google_ads_client_for_principal
from .utils.mutation_evidence import (
    attach_interrupted_evidence,
    audit_status,
    google_ads_account_target,
    terminal_operation_detail,
)
from .utils.requests import validated_request
from .utils.routing import login_customer_id

_OPERATION = "update_status"
_IDENTITY = ("object",)
_MISSING = "This no longer exists in Google Ads."
_REMOVED = "Removed items can't be turned on or off."
_OUTCOMES = {"applied": "updated", "failed": "failed", "unverified": "unverified"}

type _Key = tuple[str, str, str]


def _key(reference: ScopedEntityReference) -> _Key:
    return reference.provider_scope_id, reference.entity_kind, reference.provider_entity_id


async def google_ads_update_status(
    ctx: RunContext[RuntimeDeps],
    changes: Annotated[
        list[GoogleAdsStatusChange],
        Field(
            min_length=1,
            max_length=MAX_STATUS_CHANGES,
            description="One entry per object: its kind, its reference, and the new status.",
        ),
    ],
) -> dict[str, Any]:
    request = validated_request(GoogleAdsUpdateStatusRequest, {"changes": changes})
    _require_proposed(proposed_args(ctx), request)
    checks = approved_display_args(ctx).get("_checks")
    shown: Mapping[str, Any] = checks if isinstance(checks, Mapping) else {}
    by_key = {_key(change.reference): change for change in request.changes}

    async def operation(entry: ResolvedContextEntry, selected: Sequence[Any]) -> Any:
        account_changes = [by_key[_key(reference)] for reference in selected]
        client: GoogleAdsClient | None = None
        edits: list[Edit] = []
        pending: PendingIntegrationOperationDetail | None = None

        async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
            nonlocal client, edits, pending
            client = await google_ads_client(ctx, entry)
            edits = [
                _approved_edit(change, shown.get(change.resource_name))
                for change in account_changes
            ]
            pending = _pending_detail(entry, account_changes, edits, shown)
            return pending

        async def execute() -> IntegrationAuditOutcome[dict[str, Any]]:
            if client is None or pending is None or not edits:
                raise RuntimeError("Google Ads status change preparation did not complete")
            try:
                result = await apply_edits(
                    client,
                    customer_id=entry.external_id,
                    login_customer_id=login_customer_id(entry),
                    edits=edits,
                    read=_status_reader(client, entry, account_changes),
                    family="status",
                    operation=_OPERATION,
                )
            except asyncio.CancelledError as exc:
                attach_interrupted_evidence(exc, pending, identity_keys=_IDENTITY)
                raise
            detail = terminal_operation_detail(pending, result.ledger, identity_keys=_IDENTITY)
            data = _result(entry, account_changes, edits, shown, result)
            status = audit_status(detail)
            return IntegrationAuditOutcome(
                data,
                status=status,
                external_ref=",".join(result.ledger.external_refs)[:1000] or None,
                operation_detail=detail,
                unverified_result=data if status is AuditStatus.UNVERIFIED else None,
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_ads_update_status",
            operation=_OPERATION,
            execute=execute,
            prepare_pending_operation=prepare_pending_operation,
        )

    results = await run_context_targets(
        ctx,
        binding=GOOGLE_ADS_WRITE_BINDING,
        references=[change.reference for change in request.changes],
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


def _require_proposed(proposed: Mapping[str, Any], request: GoogleAdsUpdateStatusRequest) -> None:
    """The card can change each status and cancel changes, but never add an object."""
    try:
        original = GoogleAdsUpdateStatusRequest.model_validate(proposed).changes
    except ValidationError:
        original = []
    allowed = {change.resource_name for change in original}
    if any(change.resource_name not in allowed for change in request.changes):
        raise ModelRetry(
            "An item was added after approval. Ask the agent to prepare the change again."
        )


def _approved_edit(change: GoogleAdsStatusChange, check: Any) -> FieldChange:
    """Builds the edit against the status the approver saw, so `apply_edits` refuses stale ones."""
    edit = FieldChange(
        resource=change.resource,
        resource_name=change.resource_name,
        requested={"status": change.status},
    )
    if not isinstance(check, Mapping) or check.get("unavailable") is not False:
        return replace(edit, refused=NOT_SHOWN)
    before = check.get("status")
    if before is None:
        return replace(edit, refused=_MISSING)
    return replace(
        edit, before={"status": before}, refused=_REMOVED if before == "REMOVED" else None
    )


def _status_reader(
    client: GoogleAdsClient, entry: ResolvedContextEntry, changes: Sequence[GoogleAdsStatusChange]
) -> Callable[[Sequence[Edit]], Awaitable[Mapping[str, Mapping[str, Any]]]]:
    kinds = {change.resource_name: change.kind for change in changes}

    async def read(edits: Sequence[Edit]) -> Mapping[str, Mapping[str, Any]]:
        live = await read_statuses(
            client,
            customer_id=entry.external_id,
            login_customer_id=login_customer_id(entry),
            objects=[(kinds[edit.key], edit.key) for edit in edits],
        )
        return {name: {"status": item.status} for name, item in live.items()}

    return read


def _pending_detail(
    entry: ResolvedContextEntry,
    changes: Sequence[GoogleAdsStatusChange],
    edits: Sequence[Edit],
    shown: Mapping[str, Any],
) -> PendingIntegrationOperationDetail:
    groups: dict[str, list[IntegrationOperationIntent]] = defaultdict(list)
    for change, edit in zip(changes, edits, strict=True):
        before = edit.before.get("status") if isinstance(edit, FieldChange) else None
        fields = {
            "object": change.resource_name,
            "name": _name(change, shown.get(change.resource_name)),
            "before_status": before,
            "requested_status": change.status,
        }
        groups[change.kind].append(
            IntegrationOperationIntent(
                fields={key: value for key, value in fields.items() if value is not None}
            )
        )
    return PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key=f"{kind}:update-status",
                action="update_status",
                entity_type=f"google_ads_{kind}",
                items=items,
            )
            for kind, items in groups.items()
        ],
    )


def _result(
    entry: ResolvedContextEntry,
    changes: Sequence[GoogleAdsStatusChange],
    edits: Sequence[Edit],
    shown: Mapping[str, Any],
    result: EditResult,
) -> dict[str, Any]:
    parents = {dict(parent.identity)["object"]: parent for parent in result.ledger.parents}
    objects = []
    for change, edit in zip(changes, edits, strict=True):
        name = change.resource_name
        check = shown.get(name)
        check = check if isinstance(check, Mapping) else {}
        parent = parents[name]
        effect = parent.effects[0] if parent.effects else None
        before = edit.before.get("status") if isinstance(edit, FieldChange) else None
        skipped = parent.decision == "skipped"
        objects.append(
            {
                "kind": change.kind,
                "resource_name": name,
                "name": _name(change, check),
                "campaign_id": check.get("campaign_id") or change.reference.campaign_id,
                "campaign_name": check.get("campaign_name"),
                "before": before,
                "requested": change.status,
                # A skipped object matched the request when it was read just before sending.
                "after": before if skipped else result.after.get(name, {}).get("status"),
                "outcome": "already_set"
                if skipped
                else _OUTCOMES[effect.outcome if effect else "unverified"],
                "error_code": effect.error_code if effect is not None else None,
                "message": effect.message if effect is not None else None,
            }
        )
    return {"account_id": entry.external_id, "objects": objects}


def _name(change: GoogleAdsStatusChange, check: Any) -> str:
    shown_name = check.get("name") if isinstance(check, Mapping) else None
    return str(shown_name or change.reference.label)


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Adds each account's facts and, per object, its live status and Google's dry-run problem."""
    request = GoogleAdsUpdateStatusRequest.model_validate(args)
    by_account: dict[str, list[GoogleAdsStatusChange]] = defaultdict(list)
    for change in request.changes:
        by_account[change.reference.customer_id].append(change)
    entries = writable_entries(deps.active_context)
    checks: dict[str, dict[str, Any]] = {}
    for customer_id, changes in by_account.items():
        checks.update(await _account_checks(deps, entries.get(customer_id), changes))
    accounts = approval_accounts(entries[item] for item in by_account if item in entries)
    return {**args, "_accounts": accounts, "_checks": checks}


async def _account_checks(
    deps: RuntimeDeps, entry: ResolvedContextEntry | None, changes: Sequence[GoogleAdsStatusChange]
) -> dict[str, dict[str, Any]]:
    """Reads one account's objects and dry runs the changes; an unreadable account is unavailable."""
    try:
        if entry is None:
            raise LookupError("Google Ads account not selected")
        client = await google_ads_client_for_principal(
            deps.db, actor=deps.user, workspace=deps.workspace, entry=entry
        )
        live = await read_statuses(
            client,
            customer_id=entry.external_id,
            login_customer_id=login_customer_id(entry),
            objects=[(change.kind, change.resource_name) for change in changes],
        )
        problems = await _dry_run(client, entry, changes, live)
    except (IntegrationError, LookupError):
        return {change.resource_name: {"unavailable": True} for change in changes}
    return {
        change.resource_name: _check(change, live.get(change.resource_name), problems)
        for change in changes
    }


async def _dry_run(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    changes: Sequence[GoogleAdsStatusChange],
    live: Mapping[str, LiveStatus],
) -> dict[str, str]:
    """Returns Google's rejection per object, checking only objects that exist and aren't removed."""
    checked = [
        FieldChange(
            resource=change.resource,
            resource_name=change.resource_name,
            requested={"status": change.status},
        )
        for change in changes
        if (item := live.get(change.resource_name)) is not None and item.status != "REMOVED"
    ]
    if not checked:
        return {}

    async def read(edits: Sequence[Edit]) -> Mapping[str, Mapping[str, Any]]:
        return {edit.key: {"status": live[edit.key].status} for edit in edits}

    prepared = await prepare_edits(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        edits=checked,
        read=read,
        operation=_OPERATION,
    )
    return {edit.key: f"Google says: {edit.refused}" for edit in prepared if edit.refused}


def _check(
    change: GoogleAdsStatusChange, item: LiveStatus | None, problems: Mapping[str, str]
) -> dict[str, Any]:
    reference = change.reference
    if item is None:
        return {
            "unavailable": False,
            "kind": change.kind,
            "name": reference.label,
            "campaign_id": reference.campaign_id,
            "campaign_name": None,
            "campaign_status": None,
            "ad_group_id": getattr(reference, "ad_group_id", None),
            "ad_group_name": None,
            "ad_group_status": None,
            "status": None,
            "requested": change.status,
            "problem": _MISSING,
        }
    return {
        "unavailable": False,
        "kind": change.kind,
        "name": item.name or reference.label,
        "campaign_id": item.campaign_id,
        "campaign_name": item.campaign_name,
        "campaign_status": item.campaign_status,
        "ad_group_id": item.ad_group_id,
        "ad_group_name": item.ad_group_name,
        "ad_group_status": item.ad_group_status,
        "status": item.status,
        "requested": change.status,
        "problem": _REMOVED if item.status == "REMOVED" else problems.get(change.resource_name),
    }


DEFINITION = RuntimeToolDefinition(
    name="google_ads_update_status",
    function=google_ads_update_status,
    description=(
        "Turn Google Ads campaigns, ad groups, ads, positive keywords, or Performance Max "
        "asset groups on (ENABLED) or off (PAUSED), up to 100 per call across kinds and "
        "accounts, in one approval. Each change names its kind, the object's reference, and "
        "its own status, so one call can turn some objects off and others on. Turning on an "
        "ad group, ad, or keyword whose campaign or ad group is off doesn't start delivery. "
        "Turning on a campaign starts spending. Removing objects isn't supported here. Each "
        "result reports the status Google Ads shows after the change."
    ),
    provider="google_ads",
    label="Update Google Ads Status",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=120,
    output_model=GoogleAdsUpdateStatusOutput,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    approval_display_args=_approval_display_args,
    # Edited changes are checked whole, and the tool holds them to the proposed objects.
    approval_input_model=GoogleAdsUpdateStatusRequest,
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Updating Google Ads Status",
        completed_label="Updated Google Ads Status",
        failed_label="Couldn't Update Google Ads Status",
        approval_title="Turn Google Ads On or Off",
        approval_prompt="The agent wants to turn these Google Ads items on or off.",
        approve_label="Approve & Update",
        arg_fields=(
            ToolFieldPresentation(
                key="changes", label="Status Changes", editable=True, format="structured"
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
