# apps/api/integrations/google_ads/tools/remove_objects.py

"""Approval-only tool that permanently removes Google Ads objects of any supported kind."""

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
from ..operations.edits import (
    Edit,
    EditResult,
    Removal,
    SettingValues,
    apply_edits,
    prepare_edits,
)
from ..operations.read_removals import RemovalTarget, read_removal_targets
from .schemas.removals import (
    MAX_REMOVALS,
    GoogleAdsRemoval,
    GoogleAdsRemoveObjectsOutput,
    GoogleAdsRemoveObjectsRequest,
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

_OPERATION = "remove_objects"
_IDENTITY = ("object",)
_OUTCOMES = {"applied": "removed", "failed": "failed", "unverified": "unverified"}
# Children go before their parents, so removing an ad group doesn't fail the keywords in it.
_SEND_ORDER = {
    kind: rank
    for rank, kind in enumerate(
        (
            "keyword",
            "ad",
            "ad_group",
            "asset_group",
            "campaign",
            "budget",
            "bidding_strategy",
            "negative_keyword_list",
            "label",
        )
    )
}
_DEPENDANT_KEYS = ("campaigns", "ad_groups", "ads", "keywords")
_MISSING = "This no longer exists in Google Ads."
_IN_USE = {
    "budget": "Still funds {names}. Move {them} to another budget first.",
    "bidding_strategy": "Still used by {names}. Move {them} to another bid strategy first.",
}

type _Key = tuple[str, str, str]


def _key(reference: ScopedEntityReference) -> _Key:
    return reference.provider_scope_id, reference.entity_kind, reference.provider_entity_id


async def google_ads_remove_objects(
    ctx: RunContext[RuntimeDeps],
    items: Annotated[
        list[GoogleAdsRemoval],
        Field(
            min_length=1,
            max_length=MAX_REMOVALS,
            description="One entry per item to remove: its kind and its reference.",
        ),
    ],
) -> dict[str, Any]:
    request = validated_request(GoogleAdsRemoveObjectsRequest, {"items": items})
    _require_proposed(proposed_args(ctx), request)
    checks = approved_display_args(ctx).get("_checks")
    shown: Mapping[str, Any] = checks if isinstance(checks, Mapping) else {}
    by_key = {_key(item.reference): item for item in request.items}

    async def operation(entry: ResolvedContextEntry, selected: Sequence[Any]) -> Any:
        account_items = [by_key[_key(reference)] for reference in selected]
        client: GoogleAdsClient | None = None
        edits: list[Edit] = []
        pending: PendingIntegrationOperationDetail | None = None

        async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
            nonlocal client, edits, pending
            client = await google_ads_client(ctx, entry)
            ordered = sorted(account_items, key=lambda item: _SEND_ORDER[item.kind])
            edits = [_approved_edit(item, shown.get(item.resource_name)) for item in ordered]
            pending = _pending_detail(entry, ordered, shown)
            return pending

        async def execute() -> IntegrationAuditOutcome[dict[str, Any]]:
            if client is None or pending is None or not edits:
                raise RuntimeError("Google Ads removal preparation did not complete")
            try:
                result = await apply_edits(
                    client,
                    customer_id=entry.external_id,
                    login_customer_id=login_customer_id(entry),
                    edits=edits,
                    read=_reader(client, entry, account_items),
                    family="removals",
                    operation=_OPERATION,
                )
            except asyncio.CancelledError as exc:
                attach_interrupted_evidence(exc, pending, identity_keys=_IDENTITY)
                raise
            detail = terminal_operation_detail(pending, result.ledger, identity_keys=_IDENTITY)
            data = _result(entry, account_items, shown, result)
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
            tool_name="google_ads_remove_objects",
            operation=_OPERATION,
            execute=execute,
            prepare_pending_operation=prepare_pending_operation,
        )

    results = await run_context_targets(
        ctx,
        binding=GOOGLE_ADS_WRITE_BINDING,
        references=[item.reference for item in request.items],
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


def _require_proposed(proposed: Mapping[str, Any], request: GoogleAdsRemoveObjectsRequest) -> None:
    """The card can cancel removals, but never add an item."""
    try:
        original = GoogleAdsRemoveObjectsRequest.model_validate(proposed).items
    except ValidationError:
        original = []
    allowed = {item.resource_name for item in original}
    if any(item.resource_name not in allowed for item in request.items):
        raise ModelRetry(
            "An item was added after approval. Ask the agent to prepare the removal again."
        )


def _approved_edit(item: GoogleAdsRemoval, check: Any) -> Removal:
    """Builds the removal against what the approver saw, so `apply_edits` refuses stale ones.

    An item the card showed as already removed is skipped; any problem the card showed stands.
    """
    edit = Removal(resource=item.resource, resource_name=item.resource_name)
    if not isinstance(check, Mapping) or check.get("unavailable") is not False:
        return replace(edit, refused=NOT_SHOWN)
    if check.get("problem"):
        return replace(edit, refused=str(check["problem"]))
    if check.get("status") is None:
        return replace(edit, refused=_MISSING)
    removed = check["status"] == "REMOVED"
    return replace(edit, before=None if removed else item.resource_name)


def _reader(
    client: GoogleAdsClient, entry: ResolvedContextEntry, items: Sequence[GoogleAdsRemoval]
) -> Callable[[Sequence[Edit]], Awaitable[Mapping[str, SettingValues]]]:
    kinds = {item.resource_name: item.kind for item in items}

    async def read(edits: Sequence[Edit]) -> Mapping[str, SettingValues]:
        live = await read_removal_targets(
            client,
            customer_id=entry.external_id,
            login_customer_id=login_customer_id(entry),
            objects=[(kinds[edit.key], edit.key) for edit in edits],
            with_dependants=False,
        )
        return {name: {"status": target.status} for name, target in live.items()}

    return read


def _pending_detail(
    entry: ResolvedContextEntry,
    items: Sequence[GoogleAdsRemoval],
    shown: Mapping[str, Any],
) -> PendingIntegrationOperationDetail:
    groups: dict[str, list[IntegrationOperationIntent]] = defaultdict(list)
    for item in items:
        check = shown.get(item.resource_name)
        fields = {
            "object": item.resource_name,
            "name": _name(item, check),
            "also_removes": _dependant_text(_dependants(check)) or None,
        }
        groups[item.reference.entity_kind].append(
            IntegrationOperationIntent(
                fields={key: value for key, value in fields.items() if value is not None}
            )
        )
    return PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key=f"{entity_kind.removeprefix('google_ads_')}:remove",
                action="remove",
                entity_type=entity_kind,
                items=intents,
            )
            for entity_kind, intents in groups.items()
        ],
    )


def _result(
    entry: ResolvedContextEntry,
    items: Sequence[GoogleAdsRemoval],
    shown: Mapping[str, Any],
    result: EditResult,
) -> dict[str, Any]:
    parents = {dict(parent.identity)["object"]: parent for parent in result.ledger.parents}
    objects = []
    for item in items:
        check = shown.get(item.resource_name)
        parent = parents[item.resource_name]
        effect = parent.effects[0] if parent.effects else None
        skipped = parent.decision == "skipped"
        objects.append(
            {
                "kind": item.kind,
                "resource_name": item.resource_name,
                "name": _name(item, check),
                "campaign_name": check.get("campaign_name") if isinstance(check, Mapping) else None,
                "dependants": _dependants(check),
                "outcome": "already_removed"
                if skipped
                else _OUTCOMES[effect.outcome if effect else "unverified"],
                "error_code": effect.error_code if effect is not None else None,
                "message": effect.message if effect is not None else None,
            }
        )
    return {"account_id": entry.external_id, "objects": objects}


def _name(item: GoogleAdsRemoval, check: Any) -> str:
    shown_name = check.get("name") if isinstance(check, Mapping) else None
    return str(shown_name or item.reference.label)


def _dependants(check: Any) -> dict[str, Any]:
    raw = check.get("dependants") if isinstance(check, Mapping) else None
    raw = raw if isinstance(raw, Mapping) else {}
    counts: dict[str, Any] = {
        key: value for key in _DEPENDANT_KEYS if isinstance(value := raw.get(key), int) and value
    }
    return {**counts, "truncated": raw.get("truncated") is True}


def _dependant_text(dependants: Mapping[str, Any]) -> str:
    plus = "+" if dependants.get("truncated") else ""
    return ", ".join(
        f"{dependants[key]}{plus} {key.replace('_', ' ')}"
        for key in _DEPENDANT_KEYS
        if dependants.get(key)
    )


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Adds each account's facts and, per item, what it takes with it and why it can't go."""
    request = GoogleAdsRemoveObjectsRequest.model_validate(args)
    by_account: dict[str, list[GoogleAdsRemoval]] = defaultdict(list)
    for item in request.items:
        by_account[item.reference.customer_id].append(item)
    entries = writable_entries(deps.active_context)
    checks: dict[str, dict[str, Any]] = {}
    for customer_id, items in by_account.items():
        checks.update(await _account_checks(deps, entries.get(customer_id), items))
    accounts = approval_accounts(entries[item] for item in by_account if item in entries)
    return {**args, "_accounts": accounts, "_checks": checks}


async def _account_checks(
    deps: RuntimeDeps, entry: ResolvedContextEntry | None, items: Sequence[GoogleAdsRemoval]
) -> dict[str, dict[str, Any]]:
    """Reads one account's items and dry runs the removals; an unreadable account is unavailable."""
    try:
        if entry is None:
            raise LookupError("Google Ads account not selected")
        client = await google_ads_client_for_principal(
            deps.db, actor=deps.user, workspace=deps.workspace, entry=entry
        )
        live = await read_removal_targets(
            client,
            customer_id=entry.external_id,
            login_customer_id=login_customer_id(entry),
            objects=[(item.kind, item.resource_name) for item in items],
            with_dependants=True,
        )
        problems = {
            item.resource_name: _problem(item, live.get(item.resource_name)) for item in items
        }
        problems |= await _dry_run(client, entry, items, live, problems)
    except (IntegrationError, LookupError):
        return {item.resource_name: {"unavailable": True} for item in items}
    return {
        item.resource_name: _check(item, live.get(item.resource_name), problems[item.resource_name])
        for item in items
    }


def _problem(item: GoogleAdsRemoval, target: RemovalTarget | None) -> str | None:
    if target is None:
        return _MISSING
    if item.kind in _IN_USE and target.status != "REMOVED" and target.dependants.get("campaigns"):
        count = target.dependants["campaigns"]
        names = ", ".join(target.users)
        if count > len(target.users):
            names = f"{names} and {count - len(target.users)} more"
        return _IN_USE[item.kind].format(names=names, them="it" if count == 1 else "them")
    return None


async def _dry_run(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    items: Sequence[GoogleAdsRemoval],
    live: Mapping[str, RemovalTarget],
    problems: Mapping[str, str | None],
) -> dict[str, str]:
    """Returns Google's rejection per item, asking only about live items with no problem yet."""
    checked = [
        Removal(resource=item.resource, resource_name=item.resource_name)
        for item in sorted(items, key=lambda item: _SEND_ORDER[item.kind])
        if problems[item.resource_name] is None and live[item.resource_name].status != "REMOVED"
    ]
    if not checked:
        return {}

    async def read(edits: Sequence[Edit]) -> Mapping[str, SettingValues]:
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
    item: GoogleAdsRemoval, target: RemovalTarget | None, problem: str | None
) -> dict[str, Any]:
    if target is None:
        return {
            "unavailable": False,
            "kind": item.kind,
            "name": item.reference.label,
            "status": None,
            "campaign_name": None,
            "ad_group_name": None,
            "dependants": {"truncated": False},
            "problem": problem,
        }
    return {
        "unavailable": False,
        "kind": item.kind,
        "name": target.name or item.reference.label,
        "status": target.status,
        "campaign_name": target.campaign_name,
        "ad_group_name": target.ad_group_name,
        "dependants": {**target.dependants, "truncated": target.truncated},
        "problem": problem,
    }


DEFINITION = RuntimeToolDefinition(
    name="google_ads_remove_objects",
    function=google_ads_remove_objects,
    description=(
        "Permanently remove Google Ads items, up to 500 per call across kinds and accounts, "
        "in one approval. Removal can't be undone; to stop something showing for now, use "
        "google_ads_update_status instead. Each entry names its kind and the item's reference: "
        "campaign, ad_group, ad, keyword (a positive keyword; negative keywords change in "
        "google_ads_update_negative_keywords), asset_group, budget (a campaign budget no "
        "campaign uses), label, bidding_strategy (a portfolio strategy no campaign uses), or "
        "negative_keyword_list (a google_ads_shared_set reference). "
        "Removing a campaign or ad group also removes the ad groups, ads, and keywords in it, "
        "and the card counts them. Removing a label takes it off every item it is on, and removing "
        "a negative keyword list takes it off every campaign that uses it. A budget "
        "or bid strategy that a campaign still uses is refused on the card. Each result reports "
        "whether Google Ads shows the item as removed."
    ),
    provider="google_ads",
    label="Remove Google Ads Items",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=300,
    output_model=GoogleAdsRemoveObjectsOutput,
    preview_list_path="results.*.data.objects",
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    approval_display_args=_approval_display_args,
    # Cancelled items are checked whole, and the tool holds them to the proposed items.
    approval_input_model=GoogleAdsRemoveObjectsRequest,
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Removing Google Ads Items",
        completed_label="Removed Google Ads Items",
        failed_label="Couldn't Remove Google Ads Items",
        approval_title="Remove Google Ads Items",
        approval_prompt=(
            "The agent wants to permanently remove these Google Ads items. Removal can't be undone."
        ),
        approve_label="Approve & Remove",
        arg_fields=(
            ToolFieldPresentation(key="items", label="Items", editable=True, format="structured"),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
