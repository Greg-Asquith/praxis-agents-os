# apps/api/integrations/google_ads/tools/update_assets.py

"""Approval-only tool that adds, removes, and edits sitelinks and callouts on campaigns and ad groups."""

import asyncio
import hashlib
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Annotated, Any, Literal

from pydantic import Field
from pydantic_ai import RunContext, ToolReturn

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
from services.integrations.approved_display_args import approved_display_args
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import split_fan_out_tool_return
from services.integrations.context.targeted import run_context_targets
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..client import GoogleAdsClient
from ..operations.assets import ASSET_PATHS, LiveAssets, read_assets
from ..operations.build import CampaignBuild, dry_run_build, send_build
from ..operations.edits import CriterionChange, Edit, FieldChange, apply_edits, prepare_edits
from ..operations.mutation_outcomes import (
    GoogleAdsMutationLedger,
    GoogleAdsMutationProjection,
    build_mutation_ledger,
    freeze_fields,
    joined_ledger,
)
from .schemas.assets import (
    MAX_ASSET_CHANGES,
    MAX_ASSET_TARGETS,
    GoogleAdsAssetChange,
    GoogleAdsAssetTarget,
    GoogleAdsCallout,
    GoogleAdsExistingAsset,
    GoogleAdsSitelink,
    GoogleAdsUpdateAssetsOutput,
    GoogleAdsUpdateAssetsRequest,
    asset_row_key,
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

_OPERATION = "update_assets"
_FAMILY = "assets"
_IDENTITY = ("object",)
# One row per link and change, with room for long names.
_MAX_PUBLIC_RESULT_CHARS = 1_000_000
_MAX_MODEL_OUTCOMES = 50
# The card names this many of the campaigns and ad groups an edited asset is used in.
_MAX_USES_SHOWN = 50

_NOUNS = {"campaign": "campaign", "ad_group": "ad group"}
_LINKS = {"campaign": ("campaignAsset", "campaign"), "ad_group": ("adGroupAsset", "adGroup")}
_ASSET_MISSING = "This asset no longer exists in Google Ads."
_MADE_BY_GOOGLE = "Google made this asset, so it can't be changed or linked."
_WRONG_TYPE = "This asset isn't a {expected}."
_INTERRUPTED = "This wasn't sent, because the change was interrupted."
_APPLIED = {"add": "added", "remove": "removed", "change": "changed"}
_TYPE_NOUNS = {"SITELINK": "sitelink", "CALLOUT": "callout"}

type _Action = Literal["add", "remove", "change", "create"]
type _NewAsset = GoogleAdsSitelink | GoogleAdsCallout


@dataclass(frozen=True, slots=True)
class _Planned:
    """One change, with what the card and the result say about it."""

    # The audit record's name for the change, unique within the account.
    key: str
    # The asset's name within its target, or the asset's resource name for a content change.
    row: str
    action: _Action
    asset_type: str
    label: str
    # The campaign or ad group the link belongs to; None for a content change or a new asset.
    target: str | None = None
    target_kind: str | None = None
    # A change to something that exists; new assets and their links are build steps instead.
    edit: Edit | None = None
    new: _NewAsset | None = None
    # A new asset already linked to the target with the same content, so nothing changes.
    linked: bool = False
    refused: str | None = None


def _link_key(target: str, row: str) -> str:
    return f"{target}|{row}"


def _create_key(customer_id: str, content: str) -> str:
    digest = hashlib.sha256(content.encode()).hexdigest()[:16]
    return f"customers/{customer_id}/newAssets/{digest}"


def _asset_body(asset: _NewAsset) -> dict[str, Any]:
    """The create body for a new asset; unset fields are left out."""
    body: dict[str, Any] = {}
    for path, value in asset.values().items():
        if value is None:
            continue
        *parents, leaf = path.split(".")
        node = body
        for part in parents:
            node = node.setdefault(part, {})
        node[leaf] = value
    return body


def _plan_target(entry: GoogleAdsAssetTarget) -> list[_Planned]:
    """Compiles one target's links, with removals first, against nothing read yet."""
    target = entry.target_key
    resource, owner_field = _LINKS[entry.kind]
    planned: list[_Planned] = []
    for reference in entry.remove:
        row = asset_row_key(reference)
        edit = CriterionChange(resource, "remove", _link_key(target, row), target)
        planned.append(
            _Planned(
                edit.key,
                row,
                "remove",
                reference.asset_type,
                reference.label,
                target,
                entry.kind,
                edit=edit,
            )
        )
    for item in entry.add:
        row = asset_row_key(item)
        key = _link_key(target, row)
        if isinstance(item, GoogleAdsExistingAsset):
            asset = item.asset
            edit = CriterionChange(
                resource,
                "add",
                key,
                target,
                {owner_field: target, "asset": asset.resource_name, "fieldType": asset.asset_type},
            )
            planned.append(
                _Planned(
                    key, row, "add", asset.asset_type, asset.label, target, entry.kind, edit=edit
                )
            )
        else:
            planned.append(
                _Planned(key, row, "add", item.asset_type, item.label, target, entry.kind, new=item)
            )
    return planned


def _plan_change(change: GoogleAdsAssetChange) -> _Planned:
    asset = change.asset.resource_name
    edit = FieldChange("asset", asset, change.content.values())
    return _Planned(
        asset, asset, "change", change.asset.asset_type, change.content.label, edit=edit
    )


def _asset_problem(live: LiveAssets, name: str, asset_type: str) -> str | None:
    asset = live.assets.get(name)
    if asset is None:
        return _ASSET_MISSING
    if asset.source == "AUTOMATICALLY_CREATED":
        return _MADE_BY_GOOGLE
    if asset.asset_type != asset_type:
        return _WRONG_TYPE.format(expected=_TYPE_NOUNS.get(asset_type, "sitelink or callout"))
    return None


def _target_problem(live: LiveAssets, entry: GoogleAdsAssetTarget) -> str | None:
    target = live.targets.get(entry.target_key)
    noun = _NOUNS[entry.kind]
    if target is None:
        return f"This {noun} no longer exists in Google Ads."
    if target.status == "REMOVED":
        return f"This {noun} has been removed, so its assets can't change."
    return None


def _linked_same(live: LiveAssets, target: str, asset: _NewAsset) -> str | None:
    """The link of an asset on the target with the same content as a new one, if any."""
    values = asset.values()
    return next(
        (
            link.resource_name
            for link in live.links.get(target, ())
            if link.asset.asset_type == asset.asset_type and link.asset.values == values
        ),
        None,
    )


def _plan_live(entry: GoogleAdsAssetTarget, live: LiveAssets) -> tuple[list[_Planned], str | None]:
    """Plans one target against what's live, with each problem that stops a change."""
    problem = _target_problem(live, entry)
    planned = []
    for item in _plan_target(entry):
        if item.new is not None:
            linked = _linked_same(live, entry.target_key, item.new) is not None
            planned.append(replace(item, linked=linked, refused=problem))
            continue
        asset = item.row.removeprefix("asset:")
        name = f"customers/{entry.customer_id}/assets/{asset}"
        before = live.link(entry.target_key, name)
        reason = problem
        if reason is None and item.action == "add":
            reason = _asset_problem(live, name, item.asset_type)
        edit = replace(item.edit, before=before) if item.edit is not None else None
        asset_live = live.assets.get(name)
        label = asset_live.label if asset_live else item.label
        planned.append(replace(item, edit=edit, label=label, refused=reason))
    return planned, problem


def _plan_change_live(change: GoogleAdsAssetChange, live: LiveAssets) -> _Planned:
    item = _plan_change(change)
    name = change.asset.resource_name
    problem = _asset_problem(live, name, change.asset.asset_type)
    asset = live.assets.get(name)
    if item.edit is None or asset is None or problem is not None:
        return replace(item, refused=problem)
    return replace(item, edit=replace(item.edit, before=dict(asset.values)))


def _new_asset_parts(customer_id: str, planned: Sequence[_Planned]) -> list[_Planned]:
    """One create per new asset content with a link to send, followed by its links."""
    links: dict[str, list[_Planned]] = defaultdict(list)
    for item in planned:
        if item.new is not None and not item.linked:
            links[item.row].append(item)
    parts: list[_Planned] = []
    for row, items in links.items():
        first = items[0]
        if all(item.refused is not None for item in items):
            parts.extend(items)
            continue
        parts.append(
            _Planned(
                _create_key(customer_id, row),
                row,
                "create",
                first.asset_type,
                first.label,
                new=first.new,
            )
        )
        parts.extend(items)
    return parts


def _asset_build(
    customer_id: str, parts: Sequence[_Planned]
) -> tuple[CampaignBuild, list[_Planned]]:
    """Builds each new asset with its links, leaving out refused links.

    Returns:
        The build, and the links left out of it.
    """
    build = CampaignBuild(customer_id)
    left_out: list[_Planned] = []
    created: dict[str, str | None] = {}
    for item in parts:
        if item.action == "create" and item.new is not None:
            created[item.row] = build.create(
                "asset", _asset_body(item.new), label=item.label, source=item.key
            )
            continue
        name = created.get(item.row)
        if name is None or item.refused is not None or item.target is None:
            left_out.append(item)
            continue
        resource, owner_field = _LINKS[item.target_kind or "campaign"]
        build.create(
            resource,
            {owner_field: item.target, "asset": name, "fieldType": item.asset_type},
            label=item.label,
            source=item.key,
        )
    return build, left_out


def _account_plan(
    targets: Sequence[GoogleAdsAssetTarget],
    changes: Sequence[GoogleAdsAssetChange],
    live: LiveAssets,
) -> tuple[dict[str, list[_Planned]], dict[str, str | None]]:
    """Plans every target and change in one account, by target key or asset resource name."""
    planned: dict[str, list[_Planned]] = {}
    problems: dict[str, str | None] = {}
    for entry in targets:
        planned[entry.target_key], problems[entry.target_key] = _plan_live(entry, live)
    for change in changes:
        item = _plan_change_live(change, live)
        planned[item.key], problems[item.key] = [item], None
    return planned, problems


async def _read_live(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    targets: Sequence[GoogleAdsAssetTarget],
    changes: Sequence[GoogleAdsAssetChange],
) -> LiveAssets:
    assets = [item.asset.asset_id for item in changes]
    for target in targets:
        assets.extend(reference.asset_id for reference in target.remove)
        assets.extend(item.asset.asset_id for item in target.add if item.type == "existing")
    return await read_assets(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        campaign_ids=[t.campaign.campaign_id for t in targets if t.kind == "campaign"],
        ad_group_ids=[t.ad_group.ad_group_id for t in targets if t.kind == "ad_group"],
        asset_ids=assets,
    )


def _edit_values(live: LiveAssets) -> dict[str, Mapping[str, Any]]:
    """Each link and named asset's live values, keyed as the edits name them."""
    values: dict[str, Mapping[str, Any]] = {
        name: asset.values for name, asset in live.assets.items()
    }
    for target, links in live.links.items():
        for link in links:
            row = f"asset:{link.asset.resource_name.rsplit('/', 1)[1]}"
            values[_link_key(target, row)] = {"resourceName": link.resource_name}
    return values


def _split(
    request: GoogleAdsUpdateAssetsRequest,
) -> dict[str, tuple[list[GoogleAdsAssetTarget], list[GoogleAdsAssetChange]]]:
    by_account: dict[str, tuple[list[GoogleAdsAssetTarget], list[GoogleAdsAssetChange]]] = {}
    for target in request.entries:
        by_account.setdefault(target.customer_id, ([], []))[0].append(target)
    for change in request.change:
        by_account.setdefault(change.asset.customer_id, ([], []))[1].append(change)
    return by_account


async def google_ads_update_assets(
    ctx: RunContext[RuntimeDeps],
    entries: Annotated[
        list[GoogleAdsAssetTarget] | None,
        Field(
            max_length=MAX_ASSET_TARGETS,
            description="One entry per campaign or ad group, with the assets to add and remove.",
        ),
    ] = None,
    change: Annotated[
        list[GoogleAdsAssetChange] | None,
        Field(
            max_length=MAX_ASSET_CHANGES,
            description="New content for existing sitelinks and callouts, wherever they're used.",
        ),
    ] = None,
) -> ToolReturn[dict[str, Any]]:
    request = validated_request(
        GoogleAdsUpdateAssetsRequest, {"entries": entries or [], "change": change or []}
    )
    display = approved_display_args(ctx)
    shown_targets = display.get("_checks") if isinstance(display.get("_checks"), Mapping) else {}
    shown_changes = display.get("_changes") if isinstance(display.get("_changes"), Mapping) else {}
    by_account = _split(request)

    async def operation(entry: ResolvedContextEntry, _selected: Sequence[Any]) -> Any:
        targets, changes = by_account[entry.external_id]
        client: GoogleAdsClient | None = None
        planned: dict[str, list[_Planned]] = {}
        pending: PendingIntegrationOperationDetail | None = None

        async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
            nonlocal client, pending
            client = await google_ads_client(ctx, entry)
            for target in targets:
                planned[target.target_key] = _approved_target(
                    target, shown_targets.get(target.target_key)
                )
            for item in changes:
                approved = _approved_change(item, shown_changes.get(item.asset.resource_name))
                planned[approved.key] = [approved]
            pending = _pending_detail(entry, planned)
            return pending

        async def execute() -> IntegrationAuditOutcome[dict[str, Any]]:
            if client is None or pending is None or not planned:
                raise RuntimeError("Google Ads asset preparation did not complete")
            try:
                ledger = await _send(client, entry, targets, changes, planned)
            except asyncio.CancelledError as exc:
                attach_interrupted_evidence(exc, pending, identity_keys=_IDENTITY)
                raise
            detail = terminal_operation_detail(pending, ledger, identity_keys=_IDENTITY)
            data = _result(entry, planned, shown_targets, ledger)
            status = audit_status(detail)
            return IntegrationAuditOutcome(
                data,
                status=status,
                external_ref=",".join(ledger.external_refs)[:1000] or None,
                operation_detail=detail,
                unverified_result=data if status is AuditStatus.UNVERIFIED else None,
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_ads_update_assets",
            operation=_OPERATION,
            execute=execute,
            prepare_pending_operation=prepare_pending_operation,
        )

    references = [
        *(getattr(target, target.kind) for target in request.entries),
        *(item.asset for item in request.change),
    ]
    results = await run_context_targets(
        ctx, binding=GOOGLE_ADS_WRITE_BINDING, references=references, operation=operation
    )
    return split_fan_out_tool_return(results)


async def _send(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    targets: Sequence[GoogleAdsAssetTarget],
    changes: Sequence[GoogleAdsAssetChange],
    planned: Mapping[str, Sequence[_Planned]],
) -> GoogleAdsMutationLedger:
    """Sends changes to what exists, then builds new assets with their links, in one ledger."""
    items = [item for group in planned.values() for item in group]
    edits = [replace(i.edit, refused=i.refused) for i in items if i.edit is not None]
    parts = _new_asset_parts(entry.external_id, items)
    linked = [item for item in items if item.linked]
    ledgers: list[GoogleAdsMutationLedger] = []
    if linked:
        ledgers.append(_parts_ledger(linked, skipped=True))
    if edits:
        try:
            result = await apply_edits(
                client,
                customer_id=entry.external_id,
                login_customer_id=login_customer_id(entry),
                edits=edits,
                read=_reader(client, entry, targets, changes),
                family=_FAMILY,
                operation=_OPERATION,
            )
        except asyncio.CancelledError as exc:
            sent = getattr(exc, "ledger", None)
            if sent is not None:
                rest = (
                    [_parts_ledger(parts, code="CANCELLED", message=_INTERRUPTED)] if parts else []
                )
                exc.ledger = joined_ledger([*ledgers, sent, *rest], family=_FAMILY)
            raise
        ledgers.append(result.ledger)
    if parts:
        ledgers.extend(await _send_new_assets(client, entry, parts, ledgers))
    return joined_ledger(ledgers, family=_FAMILY)


async def _send_new_assets(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    parts: Sequence[_Planned],
    earlier: Sequence[GoogleAdsMutationLedger],
) -> list[GoogleAdsMutationLedger]:
    build, left_out = _asset_build(entry.external_id, parts)
    ledgers: list[GoogleAdsMutationLedger] = []
    refused = [replace(item, refused=item.refused or NOT_SHOWN) for item in left_out]
    if build.steps:
        keys = [step.source for step in build.steps]
        try:
            built = await send_build(
                client,
                build,
                login_customer_id=login_customer_id(entry),
                family=_FAMILY,
                operation=_OPERATION,
            )
        except asyncio.CancelledError as exc:
            exc.ledger = joined_ledger(
                [
                    *earlier,
                    _keyed(exc.ledger, keys),
                    *([_parts_ledger(refused)] if refused else []),
                ],
                family=_FAMILY,
            )
            raise
        ledgers.append(_keyed(built.ledger, keys))
    if refused:
        ledgers.append(_parts_ledger(refused))
    return ledgers


def _keyed(ledger: GoogleAdsMutationLedger, keys: Sequence[str]) -> GoogleAdsMutationLedger:
    """Names each build step by its change's key, as the audit record names every change."""
    parents = []
    for parent, key in zip(ledger.parents, keys, strict=True):
        identity = freeze_fields({"object": key, "settings": "create"})
        effects = tuple(replace(effect, fields=identity) for effect in parent.effects)
        parents.append(replace(parent, identity=identity, effects=effects))
    return replace(ledger, parents=tuple(parents))


def _parts_ledger(
    parts: Sequence[_Planned],
    *,
    skipped: bool = False,
    code: str = "REFUSED",
    message: str | None = None,
) -> GoogleAdsMutationLedger:
    """Records new asset links that weren't sent: already linked, refused, or interrupted."""
    fields = [{"object": item.key, "settings": "create"} for item in parts]
    return build_mutation_ledger(
        family=_FAMILY,
        action="update",
        parent_fields=fields,
        skipped_indices=dict.fromkeys(range(len(parts)), "already_set") if skipped else {},
        submitted=[] if skipped else list(enumerate(fields)),
        outcomes=[]
        if skipped
        else [("failed", None, code, message or item.refused or NOT_SHOWN) for item in parts],
        projection=GoogleAdsMutationProjection(
            applied_key="updated", skipped_key="already_set", errors_key="errors"
        ),
    )


def _reader(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    targets: Sequence[GoogleAdsAssetTarget],
    changes: Sequence[GoogleAdsAssetChange],
) -> Callable[[Sequence[Edit]], Awaitable[Mapping[str, Mapping[str, Any]]]]:
    async def read(_edits: Sequence[Edit]) -> Mapping[str, Mapping[str, Any]]:
        return _edit_values(await _read_live(client, entry, targets, changes))

    return read


def _shown_rows(check: Any) -> tuple[dict[tuple[Any, Any], Mapping[str, Any]], str | None] | None:
    if not isinstance(check, Mapping) or check.get("unavailable") is not False:
        return None
    rows = {
        (row.get("row"), row.get("action")): row
        for row in check.get("rows") or ()
        if isinstance(row, Mapping)
    }
    problem = check.get("problem")
    return rows, problem if isinstance(problem, str) else None


def _approved_target(target: GoogleAdsAssetTarget, check: Any) -> list[_Planned]:
    """Plans against what the approver saw, so `apply_edits` refuses anything changed since.

    A target the operator added on the card is sent only once Google checked it.
    """
    planned = _plan_target(target)
    shown = _shown_rows(check)
    if shown is None:
        return [replace(item, refused=NOT_SHOWN) for item in planned]
    rows, problem = shown
    approved = []
    for item in planned:
        row = rows.get((item.row, item.action))
        if row is None:
            approved.append(replace(item, refused=NOT_SHOWN))
            continue
        before = row.get("before") if isinstance(row.get("before"), str) else None
        reason = problem or (row.get("problem") if isinstance(row.get("problem"), str) else None)
        edit = replace(item.edit, before=before) if item.edit is not None else None
        label = row.get("label") if isinstance(row.get("label"), str) else item.label
        linked = item.new is not None and before is not None
        approved.append(replace(item, edit=edit, label=label, linked=linked, refused=reason))
    return approved


def _approved_change(change: GoogleAdsAssetChange, check: Any) -> _Planned:
    item = _plan_change(change)
    if not isinstance(check, Mapping) or check.get("unavailable") is not False:
        return replace(item, refused=NOT_SHOWN)
    before = check.get("before")
    problem = check.get("problem") if isinstance(check.get("problem"), str) else None
    if item.edit is None or not isinstance(before, Mapping):
        return replace(item, refused=problem or NOT_SHOWN)
    return replace(item, edit=replace(item.edit, before=dict(before)), refused=problem)


def _pending_detail(
    entry: ResolvedContextEntry, planned: Mapping[str, Sequence[_Planned]]
) -> PendingIntegrationOperationDetail:
    items = [item for group in planned.values() for item in group]
    # The same changes `_send` records: edits, links already in place, then the build's parts.
    recorded = [item for item in items if item.edit is not None or item.linked]
    recorded.extend(_new_asset_parts(entry.external_id, items))
    groups: dict[tuple[str, str], list[IntegrationOperationIntent]] = defaultdict(list)
    for item in recorded:
        groups[item.target_kind or "asset", item.action].append(
            IntegrationOperationIntent(fields={"object": item.key})
        )
    return PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key=f"{kind}:{action}",
                action=action,
                entity_type=f"google_ads_{kind}_asset" if kind != "asset" else "google_ads_asset",
                items=intents,
            )
            for (kind, action), intents in groups.items()
        ],
    )


def _result(
    entry: ResolvedContextEntry,
    planned: Mapping[str, Sequence[_Planned]],
    shown: Mapping[str, Any],
    ledger: GoogleAdsMutationLedger,
) -> dict[str, Any]:
    """Returns every row for the card, and the counts with what didn't happen for the agent."""
    parents = {dict(parent.identity)["object"]: parent for parent in ledger.parents}
    outcomes: list[dict[str, Any]] = []
    for key, items in planned.items():
        check = shown.get(key)
        name = check.get("name") if isinstance(check, Mapping) else None
        for item in items:
            parent = parents[item.key]
            effect = parent.effects[0] if parent.effects else None
            if parent.decision == "skipped":
                outcome = "not_found" if item.action == "remove" else "already_set"
            elif effect is None or effect.outcome == "unverified":
                outcome = "unverified"
            else:
                outcome = _APPLIED[item.action] if effect.outcome == "applied" else "failed"
            outcomes.append(
                {
                    "target_kind": item.target_kind,
                    "target_name": str(name or item.target) if item.target else None,
                    "action": item.action,
                    "asset_type": item.asset_type,
                    "asset_label": item.label,
                    "outcome": outcome,
                    "error_code": effect.error_code if effect else None,
                    "message": effect.message if effect else None,
                }
            )
    counts = Counter(row["outcome"] for row in outcomes)
    totals = {
        key: counts.get(key, 0)
        for key in (
            "added",
            "removed",
            "changed",
            "already_set",
            "not_found",
            "failed",
            "unverified",
        )
    }
    missed = [row for row in outcomes if row["outcome"] in {"failed", "unverified"}]
    base = {"account_id": entry.external_id, "counts": totals}
    return {
        "display_result": {**base, "outcomes": outcomes, "outcomes_truncated": False},
        "model_result": {
            **base,
            "outcomes": missed[:_MAX_MODEL_OUTCOMES],
            "outcomes_truncated": len(missed) > _MAX_MODEL_OUTCOMES,
        },
    }


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Adds each account's facts, and per target and change what's live, the problems, and Google's dry run."""
    request = GoogleAdsUpdateAssetsRequest.model_validate(args)
    entries = writable_entries(deps.active_context)
    targets: dict[str, dict[str, Any]] = {}
    changes: dict[str, dict[str, Any]] = {}
    by_account = _split(request)
    for customer_id, (account_targets, account_changes) in by_account.items():
        checked = await _account_checks(
            deps, entries.get(customer_id), account_targets, account_changes
        )
        targets.update(checked[0])
        changes.update(checked[1])
    accounts = approval_accounts(entries[item] for item in by_account if item in entries)
    return {**args, "_accounts": accounts, "_checks": targets, "_changes": changes}


async def _account_checks(
    deps: RuntimeDeps,
    entry: ResolvedContextEntry | None,
    targets: Sequence[GoogleAdsAssetTarget],
    changes: Sequence[GoogleAdsAssetChange],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Reads one account and dry runs its changes; an unreadable account is unavailable."""
    try:
        if entry is None:
            raise LookupError("Google Ads account not selected")
        client = await google_ads_client_for_principal(
            deps.db, actor=deps.user, workspace=deps.workspace, entry=entry
        )
        live = await _read_live(client, entry, targets, changes)
        planned, problems = _account_plan(targets, changes, live)
        google = await _dry_run(client, entry, planned, live)
    except (IntegrationError, LookupError):
        unavailable = {"unavailable": True}
        return (
            {target.target_key: unavailable for target in targets},
            {item.asset.resource_name: unavailable for item in changes},
        )
    return (
        {
            target.target_key: _target_check(
                target, live, planned[target.target_key], problems[target.target_key], google
            )
            for target in targets
        },
        {
            item.asset.resource_name: _change_check(
                planned[item.asset.resource_name][0], live, google
            )
            for item in changes
        },
    )


async def _dry_run(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    planned: Mapping[str, Sequence[_Planned]],
    live: LiveAssets,
) -> dict[str, str]:
    """Returns Google's reason for each change it would reject, by key.

    A rejected new asset, or a rejection of the whole build, applies to each of its links.
    """
    items = [item for group in planned.values() for item in group]
    edits = [replace(i.edit, refused=i.refused) for i in items if i.edit is not None]
    problems: dict[str, str] = {}
    if edits:
        values = _edit_values(live)

        async def read(_edits: Sequence[Edit]) -> Mapping[str, Mapping[str, Any]]:
            return values

        prepared = await prepare_edits(
            client,
            customer_id=entry.external_id,
            login_customer_id=login_customer_id(entry),
            edits=edits,
            read=read,
            operation=_OPERATION,
        )
        for edit, sent in zip(edits, prepared, strict=True):
            if sent.refused and edit.refused is None:
                problems[edit.key] = f"Google says: {sent.refused}"
    parts = _new_asset_parts(entry.external_id, items)
    build, _left_out = _asset_build(entry.external_id, parts)
    if build.steps:
        links_of = defaultdict(list)
        for part in parts:
            links_of[part.row].append(part.key)
        rows = {part.key: part.row for part in parts}
        for problem in await dry_run_build(
            client, build, login_customer_id=login_customer_id(entry), operation=_OPERATION
        ):
            if problem.step is None:
                keys = [part.key for part in parts]
            elif problem.step.resource == "asset":
                keys = links_of[rows[problem.step.source]]
            else:
                keys = [problem.step.source]
            for key in keys:
                problems.setdefault(key, f"Google says: {problem.message}")
    return problems


def _target_check(
    target: GoogleAdsAssetTarget,
    live: LiveAssets,
    planned: Sequence[_Planned],
    problem: str | None,
    google: Mapping[str, str],
) -> dict[str, Any]:
    """Builds the card's view of one target, and the live state approval plans against."""
    owner = live.targets.get(target.target_key)
    links = live.links.get(target.target_key, ())
    rows = []
    for item in planned:
        reason = None if problem else item.refused or google.get(item.key)
        if item.new is not None:
            before = _linked_same(live, target.target_key, item.new)
        else:
            before = item.edit.before if isinstance(item.edit, CriterionChange) else None
        if item.action == "remove":
            state = "change" if before else "not_found"
        else:
            state = "already_set" if before else "change"
        rows.append(
            {
                "row": item.row,
                "action": item.action,
                "asset_type": item.asset_type,
                "label": item.label,
                "before": before,
                "state": state,
                "problem": reason,
            }
        )
    return {
        "unavailable": False,
        "kind": target.kind,
        "name": owner.name if owner else getattr(target, target.kind).label,
        "status": owner.status if owner else None,
        "campaign_name": owner.campaign_name if owner else None,
        "problem": problem,
        "now": {
            asset_type: sum(1 for link in links if link.asset.asset_type == asset_type)
            for asset_type in ASSET_PATHS
        },
        "rows": rows,
    }


def _change_check(item: _Planned, live: LiveAssets, google: Mapping[str, str]) -> dict[str, Any]:
    asset = live.assets.get(item.key)
    uses = live.used_in.get(item.key, ())
    edit = item.edit if isinstance(item.edit, FieldChange) else None
    return {
        "unavailable": False,
        "label": asset.label if asset else item.label,
        "asset_type": item.asset_type,
        "before": dict(asset.values) if asset else None,
        "state": "already_set" if edit is not None and edit.unchanged else "change",
        "used_in": list(uses[:_MAX_USES_SHOWN]),
        "use_count": len(uses),
        "problem": item.refused or google.get(item.key),
    }


DEFINITION = RuntimeToolDefinition(
    name="google_ads_update_assets",
    function=google_ads_update_assets,
    description=(
        "Add, remove, and edit Google Ads sitelinks and callouts in one approval. Each entry "
        "names one campaign or ad_group by kind and carries add and remove lists. add takes "
        "new assets ({type: sitelink, link_text up to 25 characters, description1 and "
        "description2 up to 35 each, both or neither, final_url} or {type: callout, text up "
        "to 25 characters}, each with optional start_date and end_date) or existing ones "
        "({type: existing, asset}). A new asset added to several targets is made once and "
        "linked to each. remove unlinks an asset; it stays in the account, because Google "
        "Ads doesn't delete assets. change gives existing assets new content, "
        "which changes them everywhere they're used. To add the same assets to several "
        "campaigns, give each campaign its own entry. An asset already linked, or a "
        "removal that isn't there, is reported without a change. Google shows sitelinks "
        "only when a campaign has at least two, and best with four or more."
    ),
    provider="google_ads",
    label="Update Google Ads Assets",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=300,
    output_model=GoogleAdsUpdateAssetsOutput,
    max_public_result_chars=_MAX_PUBLIC_RESULT_CHARS,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    approval_display_args=_approval_display_args,
    approval_input_model=GoogleAdsUpdateAssetsRequest,
    # An edit changes what Google has to answer, so approval waits for a new check.
    approval_review_fields=("entries", "change"),
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Updating Ad Assets",
        completed_label="Updated Ad Assets",
        failed_label="Couldn't Update Ad Assets",
        approval_title="Update Ad Assets",
        approval_prompt="The agent wants to change the sitelinks and callouts these Google Ads campaigns show.",
        approve_label="Approve & Update",
        arg_fields=(
            ToolFieldPresentation(
                key="entries",
                label="Assets",
                editable=True,
                format="structured",
                # The first kind authorises a review; the others are the targets' kinds.
                entity_kinds=("google_ads_campaign", "google_ads_ad_group", "google_ads_asset"),
            ),
            ToolFieldPresentation(
                key="change",
                label="Asset Changes",
                editable=True,
                format="structured",
                entity_kinds=("google_ads_asset",),
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
