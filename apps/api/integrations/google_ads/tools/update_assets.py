# apps/api/integrations/google_ads/tools/update_assets.py

"""Approval-only tool that adds, removes, and edits ad assets on campaigns and ad groups."""

import hashlib
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Annotated, Any, Literal

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext, ToolReturn

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
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    PendingIntegrationOperationDetail,
)
from services.integrations.approved_display_args import approved_display_args
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import split_fan_out_tool_return
from services.integrations.context.targeted import run_context_targets

from ..client import GoogleAdsClient
from ..operations.assets import ASSET_PATHS, LiveAsset, LiveAssets, new_asset_body, read_assets
from ..operations.build import CampaignBuild, dry_run_build
from ..operations.edits import CriterionChange, Edit, FieldChange, ReadState, prepare_edits
from ..operations.media import image_fits
from ..operations.mutation_outcomes import GoogleAdsMutationLedger
from .schemas.assets import (
    MAX_ASSET_CHANGES,
    MAX_ASSET_TARGETS,
    MAX_ASSETS_PER_TARGET,
    GoogleAdsAssetChange,
    GoogleAdsAssetTarget,
    GoogleAdsExistingAsset,
    GoogleAdsPrice,
    GoogleAdsUpdateAssetsOutput,
    GoogleAdsUpdateAssetsRequest,
    NewAsset,
    asset_row_key,
)
from .utils.accounts import NOT_SHOWN, account_facts, approval_accounts, writable_entries
from .utils.bindings import GOOGLE_ADS_WRITE_BINDING, RESULTS_FIELD
from .utils.client import google_ads_available, google_ads_client_for_principal
from .utils.edit_runs import EditBuildPlan, run_approved_edits_then_build
from .utils.mutation_evidence import google_ads_account_target
from .utils.requests import validated_request
from .utils.routing import login_customer_id

_OPERATION = "update_assets"
_FAMILY = "assets"
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
_TOO_MANY = "This {noun} would have more than 20 {plural}. Remove some first, or add fewer."
_WRONG_CURRENCY = "Prices must be in the account's currency, {currency}."
# The image shapes Google takes for each image field type on Search campaigns.
_IMAGE_SHAPES = {
    "AD_IMAGE": frozenset({"MARKETING_IMAGE", "SQUARE_MARKETING_IMAGE"}),
    "BUSINESS_LOGO": frozenset({"LOGO"}),
}
_IMAGE_MISFIT = {
    "AD_IMAGE": (
        "Google shows images beside ads only when they're square (at least 300 by 300 pixels) or "
        "landscape (at least 600 by 314 pixels)."
    ),
    "BUSINESS_LOGO": "A business logo must be square and at least 128 by 128 pixels.",
}
_TOO_MANY_USES = (
    "These assets are used in too many campaigns and ad groups to check at once. "
    "Change fewer assets in one request."
)
_APPLIED = {"add": "added", "remove": "removed", "change": "changed"}
_TYPE_NOUNS = {
    "SITELINK": "sitelink",
    "CALLOUT": "callout",
    "STRUCTURED_SNIPPET": "structured snippet",
    "CALL": "call asset",
    "PRICE": "price asset",
    "IMAGE": "image",
}
# By field type, which for an image is where it shows.
_FIELD_PLURALS = {
    "SITELINK": "sitelinks",
    "CALLOUT": "callouts",
    "STRUCTURED_SNIPPET": "structured snippets",
    "CALL": "call assets",
    "PRICE": "price assets",
    "AD_IMAGE": "images",
    "BUSINESS_LOGO": "business logos",
}

type _Action = Literal["add", "remove", "change", "create"]


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
    # A new asset the target already links with the same content has that link as its edit.
    edit: Edit | None = None
    new: NewAsset | None = None
    refused: str | None = None
    # Google's field type for a link when it isn't the asset's type, such as `AD_IMAGE`.
    image_field_type: str | None = None

    @property
    def field_type(self) -> str:
        return self.image_field_type or self.asset_type


def _link_key(target: str, row: str) -> str:
    """Names a link for the audit record; a new asset's content is hashed to keep it short."""
    if row.startswith("asset:"):
        return f"{target}|{row}"
    return f"{target}|new:{hashlib.sha256(row.encode()).hexdigest()[:16]}"


def _linked(item: _Planned, link: str) -> _Planned:
    """Gives a new asset the target already links an edit that only checks the link is there."""
    resource, owner_field = _LINKS[item.target_kind or "campaign"]
    customer_id = link.split("/")[1]
    asset_id = link.rsplit("/", 1)[1].split("~")[1]
    body = {
        owner_field: item.target,
        "asset": f"customers/{customer_id}/assets/{asset_id}",
        "fieldType": item.field_type,
    }
    edit = CriterionChange(resource, "add", item.key, item.target or "", body, before=link)
    return replace(item, edit=edit)


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
            field_type = item.link_field_type
            edit = CriterionChange(
                resource,
                "add",
                key,
                target,
                {owner_field: target, "asset": asset.resource_name, "fieldType": field_type},
            )
            planned.append(
                _Planned(
                    key,
                    row,
                    "add",
                    asset.asset_type,
                    asset.label,
                    target,
                    entry.kind,
                    edit=edit,
                    image_field_type=field_type if field_type != asset.asset_type else None,
                )
            )
        else:
            planned.append(
                _Planned(key, row, "add", item.asset_type, item.label, target, entry.kind, new=item)
            )
    return planned


def _plan_change(change: GoogleAdsAssetChange) -> _Planned:
    asset = change.asset.resource_name
    edit = FieldChange("asset", asset, change.content.values_by_path())
    return _Planned(
        asset, asset, "change", change.asset.asset_type, change.content.label, edit=edit
    )


def _asset_problem(
    live: LiveAssets, name: str, asset_type: str, field_type: str | None = None
) -> str | None:
    asset = live.assets.get(name)
    if asset is None:
        return _ASSET_MISSING
    if asset.source == "AUTOMATICALLY_CREATED":
        return _MADE_BY_GOOGLE
    if asset.asset_type != asset_type:
        return _WRONG_TYPE.format(expected=_TYPE_NOUNS.get(asset_type, "linkable asset"))
    if field_type in _IMAGE_SHAPES:
        return _image_problem(asset, field_type)
    return None


def _image_problem(asset: LiveAsset, field_type: str) -> str | None:
    """Why Google won't show the image where it's linked, from its size."""
    fits = set(image_fits(*asset.size)[0]) if asset.size else set()
    return None if fits & _IMAGE_SHAPES[field_type] else _IMAGE_MISFIT[field_type]


def _currency_problem(asset: NewAsset | None, currency: str | None) -> str | None:
    if isinstance(asset, GoogleAdsPrice) and currency and asset.currency_code != currency:
        return _WRONG_CURRENCY.format(currency=currency)
    return None


def _target_problem(live: LiveAssets, entry: GoogleAdsAssetTarget) -> str | None:
    target = live.targets.get(entry.target_key)
    noun = _NOUNS[entry.kind]
    if target is None:
        return f"This {noun} no longer exists in Google Ads."
    if target.status == "REMOVED":
        return f"This {noun} has been removed, so its assets can't change."
    return None


def _linked_same(
    live: LiveAssets, target: str, asset: NewAsset, removed: frozenset[str]
) -> str | None:
    """The link of an asset staying on the target with the same content as a new one, if any."""
    values = asset.values_by_path()
    return next(
        (
            link.resource_name
            for link in live.links.get(target, ())
            if link.asset.asset_type == asset.asset_type
            and link.asset.values == values
            and link.asset.resource_name not in removed
        ),
        None,
    )


def _plan_live(
    entry: GoogleAdsAssetTarget, live: LiveAssets, currency: str | None = None
) -> tuple[list[_Planned], str | None]:
    """Plans one target against what's live, with each problem that stops a change."""
    problem = _target_problem(live, entry)
    assets = f"customers/{entry.customer_id}/assets"
    removed = frozenset(f"{assets}/{reference.asset_id}" for reference in entry.remove)
    planned = []
    for item in _plan_target(entry):
        if item.new is not None:
            link = _linked_same(live, entry.target_key, item.new, removed)
            reason = problem or _currency_problem(item.new, currency)
            planned.append(replace(_linked(item, link) if link else item, refused=reason))
            continue
        name = f"{assets}/{item.row.removeprefix('asset:')}"
        reason = problem
        if reason is None and item.action == "add":
            reason = _asset_problem(live, name, item.asset_type, item.image_field_type)
        # An addition matches only a link of the same field type; a removal takes any.
        link = live.link(entry.target_key, name, item.field_type if item.action == "add" else None)
        edit = replace(item.edit, before=link) if item.edit else None
        asset = live.assets.get(name)
        if asset is not None:
            item = replace(item, label=asset.label)
            # A removal names its link by the asset, whatever type the reference gives.
            if asset.asset_type in ASSET_PATHS:
                item = replace(item, asset_type=asset.asset_type)
        if item.action == "remove" and link and "~" in link:
            field_type = link.rsplit("~", 1)[1]
            item = replace(
                item, image_field_type=field_type if field_type != item.asset_type else None
            )
        planned.append(replace(item, edit=edit, refused=reason))
    return _within_limit(entry, live, planned), problem


def _within_limit(
    entry: GoogleAdsAssetTarget, live: LiveAssets, planned: Sequence[_Planned]
) -> list[_Planned]:
    """Refuses the additions of a field type that would leave the target with more than Google allows."""

    def changes(item: _Planned) -> bool:
        return item.refused is None and (item.edit is None or not item.edit.unchanged)

    counts = Counter(
        link.field_type or link.asset.asset_type for link in live.links.get(entry.target_key, ())
    )
    for item in planned:
        if changes(item):
            counts[item.field_type] += 1 if item.action == "add" else -1
    return [
        replace(
            item,
            refused=_TOO_MANY.format(
                noun=_NOUNS[entry.kind], plural=_FIELD_PLURALS.get(item.field_type, "assets")
            ),
        )
        if item.action == "add"
        and changes(item)
        and counts[item.field_type] > MAX_ASSETS_PER_TARGET
        else item
        for item in planned
    ]


def _plan_change_live(
    change: GoogleAdsAssetChange, live: LiveAssets, currency: str | None = None
) -> _Planned:
    item = _plan_change(change)
    name = change.asset.resource_name
    problem = _asset_problem(live, name, change.asset.asset_type) or _currency_problem(
        change.content, currency
    )
    asset = live.assets.get(name)
    if item.edit is None or asset is None or problem is not None:
        return replace(item, refused=problem)
    return replace(item, edit=replace(item.edit, before=dict(asset.values)))


def _new_asset_parts(customer_id: str, planned: Sequence[_Planned]) -> list[_Planned]:
    """One create per new asset content with a link to send, followed by its links."""
    links: dict[str, list[_Planned]] = defaultdict(list)
    for item in planned:
        if item.new is not None and item.edit is None:
            links[item.row].append(item)
    parts: list[_Planned] = []
    for row, items in links.items():
        first = items[0]
        if all(item.refused is not None for item in items):
            parts.extend(items)
            continue
        digest = hashlib.sha256(row.encode()).hexdigest()[:16]
        parts.append(
            _Planned(
                f"customers/{customer_id}/newAssets/{digest}",
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
                "asset", new_asset_body(item.new), label=item.label, source=item.key
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
    currency: str,
) -> tuple[dict[str, list[_Planned]], dict[str, str | None]]:
    """Plans every target and change in one account, by target key or asset resource name."""
    planned: dict[str, list[_Planned]] = {}
    problems: dict[str, str | None] = {}
    for entry in targets:
        planned[entry.target_key], problems[entry.target_key] = _plan_live(entry, live, currency)
    for change in changes:
        item = _plan_change_live(change, live, currency)
        planned[item.key], problems[item.key] = [item], None
    return planned, problems


async def _read_live(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    targets: Sequence[GoogleAdsAssetTarget],
    changes: Sequence[GoogleAdsAssetChange],
    *,
    with_uses: bool = True,
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
        with_uses=with_uses,
    )


def _edit_values(live: LiveAssets, items: Sequence[_Planned]) -> dict[str, Mapping[str, Any]]:
    """Each link and named asset's live values, keyed as the edits name them."""
    values: dict[str, Mapping[str, Any]] = {
        name: asset.values for name, asset in live.assets.items()
    }
    # An image added as one field type isn't there when it's linked only as the other.
    wanted = {item.key: item.field_type for item in items if item.action == "add"}
    present = set()
    for target, links in live.links.items():
        for link in links:
            row = f"asset:{link.asset.resource_name.rsplit('/', 1)[1]}"
            key = _link_key(target, row)
            actual = link.field_type or link.asset.asset_type
            if wanted.get(key, actual) == actual:
                values[key] = {"resourceName": link.resource_name}
            present.add(link.resource_name)
    # A new asset the target already links is checked by that link's own name.
    for item in items:
        if item.new is not None and item.edit is not None and item.edit.before in present:
            values[item.key] = {"resourceName": item.edit.before}
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
        planned: dict[str, list[_Planned]] = {}

        def plan() -> EditBuildPlan:
            for target in targets:
                planned[target.target_key] = _approved_target(
                    target, shown_targets.get(target.target_key)
                )
            for item in changes:
                approved = _approved_change(item, shown_changes.get(item.asset.resource_name))
                planned[approved.key] = [approved]
            items = [item for group in planned.values() for item in group]
            build, left_out = _asset_build(
                entry.external_id, _new_asset_parts(entry.external_id, items)
            )
            return EditBuildPlan(
                edits=[replace(i.edit, refused=i.refused) for i in items if i.edit is not None],
                build=build,
                refused={item.key: item.refused or NOT_SHOWN for item in left_out},
                pending=_pending_detail(entry, items),
            )

        def read(client: GoogleAdsClient) -> ReadState:
            async def values(_edits: Sequence[Edit]) -> Mapping[str, Mapping[str, Any]]:
                live = await _read_live(client, entry, targets, changes, with_uses=False)
                return _edit_values(live, [item for group in planned.values() for item in group])

            return values

        return await run_approved_edits_then_build(
            ctx,
            entry,
            tool_name="google_ads_update_assets",
            operation=_OPERATION,
            family=_FAMILY,
            plan=plan,
            read=read,
            result=lambda ledger: _result(entry, planned, shown_targets, ledger),
        )

    references = [
        *(getattr(target, target.kind) for target in request.entries),
        *(item.asset for item in request.change),
    ]
    results = await run_context_targets(
        ctx, binding=GOOGLE_ADS_WRITE_BINDING, references=references, operation=operation
    )
    return split_fan_out_tool_return(results)


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
        if item.new is not None:
            item = _linked(item, before) if before else item
        elif item.edit is not None:
            item = replace(item, edit=replace(item.edit, before=before))
        label = row.get("label") if isinstance(row.get("label"), str) else item.label
        shown_type = row.get("asset_type")
        asset_type = shown_type if shown_type in ASSET_PATHS else item.asset_type
        # A removal's field type comes from the link the approver saw.
        shown_field = row.get("field_type")
        if item.action == "remove" and shown_field in _FIELD_PLURALS:
            item = replace(
                item, image_field_type=shown_field if shown_field != asset_type else None
            )
        approved.append(replace(item, label=label, asset_type=asset_type, refused=reason))
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
    entry: ResolvedContextEntry, items: Sequence[_Planned]
) -> PendingIntegrationOperationDetail:
    # Every change the ledger records: the edits, then each new asset with its links.
    recorded = [item for item in items if item.edit is not None]
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
        if live.uses_truncated:
            raise ModelRetry(_TOO_MANY_USES)
        planned, problems = _account_plan(targets, changes, live, account_facts(entry).currency)
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
        values = _edit_values(live, items)

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
                "field_type": item.field_type,
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
        "account_level": item.key in live.account_level,
        "problem": item.refused or google.get(item.key),
    }


DEFINITION = RuntimeToolDefinition(
    name="google_ads_update_assets",
    function=google_ads_update_assets,
    description=(
        "Add, remove, and edit Google Ads sitelinks, callouts, structured snippets, calls, "
        "prices, and images in one approval. Each entry "
        "names one campaign or ad_group by kind and carries add and remove lists. add takes "
        "new assets ({type: sitelink, link_text up to 25 characters, description1 and "
        "description2 up to 35 each, both or neither, final_url} or {type: callout, text up "
        "to 25 characters}, each with optional start_date and end_date; {type: "
        "structured_snippet, header, values: 3 to 10 of up to 25 characters}; {type: call, "
        "country_code, phone_number}; {type: price, price_type, price_qualifier, "
        "currency_code (the account's), offerings: 3 to 8 of {header and description up to "
        "25 each, price, unit, final_url}}) or existing ones ({type: existing, asset}). Images "
        "come from google_ads_upload_media and are linked as existing assets, with field_type "
        "BUSINESS_LOGO for a campaign's logo. A new asset added to several targets is made once and "
        "linked to each. remove unlinks an asset; it stays in the account, because Google "
        "Ads doesn't delete assets. change gives existing assets new content, "
        "which changes them everywhere they're used. content replaces the whole asset, so "
        "repeat every field to keep, such as descriptions and dates. To add the same assets to several "
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
        approval_prompt="The agent wants to change the assets these Google Ads campaigns show with their ads.",
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
