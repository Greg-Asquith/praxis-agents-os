# apps/api/integrations/meta_ads/tools/update_ads.py

"""Approval-only tool that renames existing Meta ads, sets their own times, or changes their creative."""

import asyncio
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Any
from zoneinfo import ZoneInfo

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
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)
from utils.metadata import metadata_str

from ..client import MetaAdsClient
from ..creative_features import OFFERED_CHANGE_KEYS, offered_catalogue
from ..operations.ad_review import review_state
from ..operations.edit_ad import ad_values, edit_body, edit_problems, requested_values
from ..operations.edit_creative import (
    CreativeEdit,
    creative_body,
    plan_creative_edit,
    thumbnail_problem,
)
from ..operations.edit_impact import creative_notes
from ..operations.list_objects import read_objects_by_id
from ..operations.mutations import MetaAdsMutationLedger
from ..operations.read_creative import read_live_creatives
from ..operations.update_fields import FieldChange, same_value, update_fields, validate_fields
from ..references import MetaAdsAdReference, MetaAdsPageReference
from ..throttle import ensure_account_available, ensure_headroom
from ..tools.schemas.objects import MetaAdsObject
from .schemas.ad_edits import (
    MAX_AD_EDITS,
    MetaAdsAdEdit,
    MetaAdsUpdateAdsOutput,
    MetaAdsUpdateAdsRequest,
)
from .schemas.ads import APP_BUTTONS, WEBSITE_BUTTONS, media_key
from .utils.ad_preparation import (
    check_posts,
    hydrate_references,
    library_media,
    required_currency,
)
from .utils.bindings import META_ADS_WRITE_BINDING, RESULTS_FIELD
from .utils.client import (
    meta_ads_available,
    meta_ads_client,
    meta_ads_client_for_principal,
    meta_ads_entries,
)
from .utils.create_operation import validated
from .utils.mutation_evidence import (
    attach_interrupted_evidence,
    audit_status,
    meta_ads_account_target,
    terminal_operation_detail,
)
from .utils.schedule import account_zone

_OPERATION = "update_ads"
_GROUP = "ads:update-settings"
# Each ad takes about three calls, so the run needs Meta's usage below this percentage.
_USAGE_LIMIT = 75.0
_CHANGED = (
    "This ad changed since you approved it, so it wasn't changed. Ask the agent to prepare "
    "the change again."
)
_NOT_SHOWN = (
    "This ad couldn't be checked before approval, so it wasn't changed. Ask the agent to "
    "prepare the change again."
)

type _Key = tuple[str, str]


@dataclass
class _Review:
    """One ad as it is now, with what the edit would break."""

    edit: MetaAdsAdEdit
    ad: MetaAdsObject
    values: dict[str, str | None]
    # The ad's own times must fall inside its ad set's schedule.
    ad_set: MetaAdsObject | None = None
    creative: CreativeEdit | None = None
    body: dict[str, str] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    @property
    def requested(self) -> dict[str, str | None]:
        return dict(requested_values(self.edit))

    @property
    def compared(self) -> tuple[str, ...]:
        """The values the approver saw that must still hold when the change is sent."""
        return (*self.requested, *(("creative_id",) if self.edit.creative else ()))

    @property
    def unchanged(self) -> bool:
        return self.edit.creative is None and all(
            same_value(self.values[key], value) for key, value in self.requested.items()
        )

    @property
    def notes(self) -> list[str]:
        if self.creative is None:
            return []
        live = self.creative.live
        return creative_notes(
            before=live.enabled,
            after=self.creative.enabled,
            new_post="post" in self.creative.changed,
            shop=live.destination_type == "WEBSITE_AND_SHOP",
        )


async def meta_ads_update_ads(
    ctx: RunContext[RuntimeDeps],
    changes: Annotated[
        list[MetaAdsAdEdit],
        Field(
            min_length=1,
            max_length=MAX_AD_EDITS,
            description="One entry per ad, with only the settings that change.",
        ),
    ],
) -> dict[str, Any]:
    request = validated(MetaAdsUpdateAdsRequest, {"changes": changes})
    _require_proposed(proposed_args(ctx), request)
    checks = approved_display_args(ctx).get("_checks")
    shown = checks if isinstance(checks, Mapping) else {}
    edits = {_key(edit.ad): edit for edit in request.changes}

    async def operation(entry: ResolvedContextEntry, selected: Sequence[Any]) -> Any:
        client: MetaAdsClient | None = None
        changes: list[FieldChange] = []
        changed: dict[str, tuple[str, ...]] = {}
        pending: PendingIntegrationOperationDetail | None = None
        zone: ZoneInfo | None = None
        account_edits = [edits[_key(reference)] for reference in selected]

        async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
            nonlocal client, changes, changed, pending, zone
            ensure_account_available(entry.external_id, operation=_OPERATION)
            ensure_headroom(entry.external_id, operation=_OPERATION, limit=_USAGE_LIMIT)
            zone = account_zone(metadata_str(entry.permissions_metadata.get("timezone_name")))
            client = await meta_ads_client(ctx, entry)
            changes, changed = await _prepare(client, entry, account_edits, shown, zone)
            pending = _pending_detail(entry, changes, edits, changed)
            return pending

        async def execute() -> IntegrationAuditOutcome[dict[str, Any]]:
            if client is None or pending is None or zone is None:
                raise RuntimeError("Meta Ads ad edit preparation did not complete")
            read_zone = zone
            # Each ad as read back, for its review and delivery status after a new creative.
            read: dict[str, MetaAdsObject] = {}

            def values(item: MetaAdsObject) -> dict[str, str | None]:
                read[item.id] = item
                return ad_values(item, read_zone)

            try:
                ledger = await update_fields(
                    client,
                    account_id=entry.external_id,
                    currency=required_currency(entry),
                    changes=changes,
                    values=values,
                    action=_OPERATION,
                    group_key=_GROUP,
                    operation=_OPERATION,
                )
            except asyncio.CancelledError as exc:
                attach_interrupted_evidence(exc, pending, identity_key="object_id")
                raise
            detail = terminal_operation_detail(pending, ledger, identity_key="object_id")
            result = _result(entry, read_zone, changes, ledger, changed, read)
            status = audit_status(detail)
            return IntegrationAuditOutcome(
                result,
                status=status,
                external_ref=",".join(ledger.external_refs)[:1000] or None,
                operation_detail=detail,
                unverified_result=result if status is AuditStatus.UNVERIFIED else None,
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="meta_ads_update_ads",
            operation=_OPERATION,
            execute=execute,
            prepare_pending_operation=prepare_pending_operation,
        )

    results = await run_context_targets(
        ctx,
        binding=META_ADS_WRITE_BINDING,
        references=[edit.ad for edit in request.changes],
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


def _key(reference: MetaAdsAdReference) -> _Key:
    return reference.account_id, reference.ad_id


def _require_proposed(proposed: Mapping[str, Any], request: MetaAdsUpdateAdsRequest) -> None:
    """The card can change values and drop settings or ads, but never add one."""
    try:
        original = MetaAdsUpdateAdsRequest.model_validate(proposed).changes
    except ValidationError:
        original = []
    settings = {_key(edit.ad): _proposed_settings(edit) for edit in original}
    for edit in request.changes:
        if not _proposed_settings(edit) <= settings.get(_key(edit.ad), set()):
            raise ModelRetry(
                "A setting or ad was added after approval. Ask the agent to prepare it again."
            )


def _proposed_settings(edit: MetaAdsAdEdit) -> set[str]:
    """A creative counts as one setting, since the card can edit any part of it."""
    return {*edit.settings, *(("creative",) if edit.creative else ())}


async def _review_account(
    client: MetaAdsClient,
    entry: ResolvedContextEntry,
    edits: Sequence[MetaAdsAdEdit],
    zone: ZoneInfo,
) -> list[_Review]:
    """Re-reads each ad and its ad set, applies Meta's rules, and asks Meta to check."""
    account_id = entry.external_id
    currency = required_currency(entry)
    now = datetime.now(UTC)
    ads = await read_objects_by_id(
        client,
        account_id=account_id,
        object_type="ad",
        object_ids=[edit.ad.ad_id for edit in edits],
        currency=currency,
    )
    if any(edit.ad.ad_id not in ads for edit in edits):
        raise ModelRetry("Some ads are no longer in this ad account. Choose them again.")
    ad_sets = await read_objects_by_id(
        client,
        account_id=account_id,
        object_type="adset",
        object_ids=[item.adset_id for item in ads.values() if item.adset_id],
        currency=currency,
    )
    reviews: list[_Review] = []
    for edit in edits:
        ad = ads[edit.ad.ad_id]
        ad_set = ad_sets.get(ad.adset_id or "")
        review = _Review(edit=edit, ad=ad, values=ad_values(ad, zone), ad_set=ad_set)
        if ad_set is None:
            review.problems.append("This ad's ad set couldn't be read.")
        else:
            review.problems.extend(edit_problems(edit, ad, ad_set, zone=zone, now=now))
        reviews.append(review)
    await _plan_creatives(client, entry, reviews)
    for review in reviews:
        ad = review.ad
        if not review.problems and not review.unchanged:
            review.body = {**edit_body(review.edit, zone), **review.body}
            if reason := await validate_fields(
                client,
                account_id=account_id,
                object_id=ad.id,
                body=review.body,
                operation=_OPERATION,
            ):
                review.problems.append(reason)
    return reviews


async def _plan_creatives(
    client: MetaAdsClient, entry: ResolvedContextEntry, reviews: Sequence[_Review]
) -> None:
    """Builds each new creative from the live one, reading new media and posts once."""
    account_id = entry.external_id
    wanted = [
        review for review in reviews if review.edit.creative is not None and not review.problems
    ]
    if not wanted:
        return
    lives = await read_live_creatives(
        client, account_id=account_id, ad_ids=[r.ad.id for r in wanted], operation=_OPERATION
    )
    for review in wanted:
        live = lives[review.ad.id]
        if isinstance(live, str):
            review.problems.append(live)
        elif review.edit.creative is not None and review.ad_set is not None:
            review.creative = plan_creative_edit(
                live,
                review.edit.creative,
                ad=review.ad,
                ad_set=review.ad_set,
                account_id=account_id,
            )
            review.problems.extend(review.creative.problems)
    planned = [r for r in wanted if r.creative is not None and not r.problems]
    media = await _read_new_media(client, entry, planned)
    for review in planned:
        creative, ad_set = review.creative, review.ad_set
        if creative is None or ad_set is None or review.problems:
            continue
        available = {**creative.live.media, **media}
        if problem := thumbnail_problem(creative, available):
            review.problems.append(problem)
            continue
        pixel = ad_set.promoted_object.pixel_id if ad_set.promoted_object else None
        review.body = creative_body(creative, available, adset_id=ad_set.id, pixel_id=pixel)


async def _read_new_media(
    client: MetaAdsClient, entry: ResolvedContextEntry, reviews: Sequence[_Review]
) -> dict[Any, Any]:
    """Re-reads chosen library media and posts through the account; a miss refuses those ads."""
    items = {
        media_key(item): item
        for review in reviews
        if review.creative is not None
        for item in review.creative.new_media
    }
    posts = [r.creative.new_post for r in reviews if r.creative and r.creative.new_post]
    try:
        await check_posts(client, entry, posts)
        return await library_media(client, entry, list(items.values()))
    except ModelRetry as exc:
        for review in reviews:
            if review.creative and (review.creative.new_media or review.creative.new_post):
                review.problems.append(str(exc))
        return {}


async def _prepare(
    client: MetaAdsClient,
    entry: ResolvedContextEntry,
    edits: Sequence[MetaAdsAdEdit],
    shown: Mapping[str, Any],
    zone: ZoneInfo,
) -> tuple[list[FieldChange], dict[str, tuple[str, ...]]]:
    """Checks every edit again, refuses stale ones, and stops if Meta rejects any.

    Returns:
        The changes to send, and the creative parts each ad with a new creative changes.
    """
    reviews = await _review_account(client, entry, edits, zone)
    if problems := [
        f"{review.ad.name or review.ad.id}: {problem}"
        for review in reviews
        for problem in review.problems
    ]:
        raise ModelRetry(
            f"These ad changes can't be made, so nothing was changed. {' '.join(problems)}"
        )
    changes = [
        FieldChange(
            object_type="ad",
            before=review.ad,
            before_values={key: review.values[key] for key in review.compared},
            requested=review.requested,
            body=review.body,
            refused=_stale(review, shown.get(review.ad.id)),
            replaces={"creative_id": review.ad.creative_id} if review.edit.creative else {},
        )
        for review in reviews
    ]
    changed = {
        review.ad.id: review.creative.changed for review in reviews if review.creative is not None
    }
    return changes, changed


def _stale(review: _Review, shown: Any) -> str | None:
    """Refuses an edit whose settings differ from the values the approver saw."""
    before = shown.get("before") if isinstance(shown, Mapping) else None
    if not isinstance(before, Mapping):
        return _NOT_SHOWN
    for key in review.compared:
        if key not in before or not same_value(review.values[key], before[key]):
            return _CHANGED
    return None


def _pending_detail(
    entry: ResolvedContextEntry,
    changes: Sequence[FieldChange],
    edits: Mapping[_Key, MetaAdsAdEdit],
    changed: Mapping[str, tuple[str, ...]],
) -> PendingIntegrationOperationDetail:
    items: list[IntegrationOperationIntent] = []
    for change in changes:
        creative = edits[(entry.external_id, change.object_id)].creative
        fields = {
            "object_id": change.object_id,
            "object_name": change.before.name,
            "before": dict(change.before_values),
            # Names and ad text are public, so the record keeps them as approved.
            "requested": dict(change.requested),
            "creative": {
                "changed": list(changed.get(change.object_id, ())),
                "requested": creative.model_dump(mode="json", exclude_none=True),
            }
            if creative is not None
            else None,
        }
        items.append(
            IntegrationOperationIntent(
                fields={key: value for key, value in fields.items() if value is not None}
            )
        )
    return PendingIntegrationOperationDetail(
        target=meta_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key=_GROUP, action="update_ad_settings", entity_type="meta_ads_ad", items=items
            )
        ],
    )


def _result(
    entry: ResolvedContextEntry,
    zone: ZoneInfo,
    changes: Sequence[FieldChange],
    ledger: MetaAdsMutationLedger,
    changed: Mapping[str, tuple[str, ...]],
    read: Mapping[str, MetaAdsObject],
) -> dict[str, Any]:
    parents = {dict(parent.identity)["object_id"]: parent for parent in ledger.parents}
    rows = []
    for change in changes:
        parent = parents[change.object_id]
        effect = parent.effects[0] if parent.effects else None
        observed = dict(effect.fields) if effect is not None else {}
        after = read.get(change.object_id)
        rows.append(
            {
                "ad_id": change.object_id,
                "name": change.before.name,
                "changes": [
                    {
                        "setting": key,
                        "before": change.before_values[key],
                        "requested": value,
                        "after": change.before_values[key]
                        if parent.decision == "skipped"
                        else _read_value(observed.get(f"after.{key}")),
                    }
                    for key, value in change.requested.items()
                ],
                "creative": {
                    "changed": list(changed.get(change.object_id, ())),
                    "before_creative_id": change.before.creative_id,
                    "after_creative_id": _read_value(observed.get("after.creative_id")),
                    "review": review_state(after.effective_status) if after else "unknown",
                    "effective_status": after.effective_status if after else None,
                }
                if change.replaces
                else None,
                "outcome": {"applied": "updated", "skipped": "already_set"}.get(
                    parent.outcome, parent.outcome
                ),
                "error_code": effect.error_code if effect is not None else None,
                "message": effect.message if effect is not None else None,
            }
        )
    return {"account_id": entry.external_id, "time_zone": zone.key, "ads": rows}


def _read_value(value: str | None) -> str | None:
    return None if value in (None, "none") else value


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Hydrates the ads and adds, per ad, its current values and problems."""
    request = MetaAdsUpdateAdsRequest.model_validate(args)
    hydrated = await hydrate_references(
        deps, "meta_ads_ad", "changes", [edit.ad for edit in request.changes]
    )
    changes = [
        {**dict(change), "ad": reference}
        for change, reference in zip(args["changes"], hydrated, strict=True)
    ]
    by_account: dict[str, list[MetaAdsAdEdit]] = defaultdict(list)
    for edit in request.changes:
        by_account[edit.ad.account_id].append(edit)
    entries = meta_ads_entries(deps)
    checks: dict[str, dict[str, Any]] = {}
    for account_id, edits in by_account.items():
        checks.update(await _account_checks(deps, entries.get(account_id), edits))
    display: dict[str, Any] = {**args, "changes": changes, "_checks": checks}
    if any(edit.creative for edit in request.changes):
        display["_automatic_change_catalogue"] = offered_catalogue()
    return display


async def _account_checks(
    deps: RuntimeDeps, entry: ResolvedContextEntry | None, edits: Sequence[MetaAdsAdEdit]
) -> dict[str, dict[str, Any]]:
    """Checks one account's edits; any that can't be read are marked unavailable for the card."""
    try:
        if entry is None:
            raise LookupError("ad account not selected")
        zone = account_zone(metadata_str(entry.permissions_metadata.get("timezone_name")))
        client = await meta_ads_client_for_principal(
            deps.db, actor=deps.user, workspace=deps.workspace, entry=entry
        )
        reviews = await _review_account(client, entry, edits, zone)
    except (IntegrationError, LookupError, ModelRetry):
        return {edit.ad.ad_id: {"unavailable": True} for edit in edits}
    pages = await _page_names(deps, entry, reviews)
    return {
        review.ad.id: {
            "time_zone": zone.key,
            "before": review.values,
            # The values these problems were found for, so the card knows when an edit makes
            # them stale.
            "requested": review.requested,
            "requested_creative": review.edit.creative.model_dump(mode="json", exclude_none=True)
            if review.edit.creative
            else None,
            "problems": review.problems,
            "ad_set_schedule": _schedule(review.ad_set, zone),
            "creative": _creative_check(review, pages),
            "unavailable": False,
        }
        for review in reviews
    }


async def _page_names(
    deps: RuntimeDeps, entry: ResolvedContextEntry, reviews: Sequence[_Review]
) -> dict[str, str]:
    """Names each Page a creative runs as, for the previews; a Page that can't be read has none."""
    page_ids = sorted({r.creative.live.page_id for r in reviews if r.creative is not None})
    if not page_ids:
        return {}
    references = [
        MetaAdsPageReference(account_id=entry.external_id, page_id=page_id, label="Page")
        for page_id in page_ids
    ]
    try:
        hydrated = await hydrate_references(deps, "meta_ads_page", "changes", references)
    except (IntegrationError, LookupError, ModelRetry):
        return {}
    return {str(item.get("page_id")): str(item.get("label")) for item in hydrated}


def _creative_check(review: _Review, pages: Mapping[str, str]) -> dict[str, Any] | None:
    """The live creative for the card's before preview, with what the new one changes."""
    creative = review.creative
    if creative is None:
        return None
    live = creative.live
    app = review.ad_set is not None and review.ad_set.objective == "OUTCOME_APP_PROMOTION"
    return {
        "content": live.content,
        "ad_set": {
            "adset_id": review.ad_set.id,
            "label": review.ad_set.name or review.ad_set.id,
            "objective": review.ad_set.objective,
        }
        if review.ad_set
        else None,
        "page_id": live.page_id,
        "page_name": pages.get(live.page_id),
        "changed": list(creative.changed),
        "automatic_changes": sorted(live.enabled & set(OFFERED_CHANGE_KEYS)),
        "buttons": list(APP_BUTTONS if app else WEBSITE_BUTTONS),
        "notes": review.notes,
    }


def _schedule(ad_set: MetaAdsObject | None, zone: ZoneInfo) -> dict[str, str | None] | None:
    """The ad set's start and end as local times, read the way ad times are."""
    if ad_set is None:
        return None
    values = ad_values(ad_set, zone)
    return {"start_at": values["start_at"], "end_at": values["end_at"]}


DEFINITION = RuntimeToolDefinition(
    name="meta_ads_update_ads",
    function=meta_ads_update_ads,
    description=(
        "Change existing Meta ads, up to 50 per call, in one approval. Each entry names one ad "
        "from meta_ads_list_objects and only what changes: name; start_at and end_at as "
        "YYYY-MM-DDTHH:MM in the ad account's time zone, or none to follow the ad set's "
        "schedule again; and creative, with only the parts of what the ad says or shows that "
        "change (primary_text, headline, description, link, call_to_action, url_tags, media, "
        "vertical_media, thumbnail, cards, post for existing post ads, or automatic_changes as "
        "the full list to have on). Praxis reads the ad's live creative, applies the changes, "
        "and switches the ad to a new creative, keeping its ID and results. New media must "
        "already be in the media library: upload Files with meta_ads_upload_media first. "
        "cards replaces every carousel card. A new creative sends the ad back to review, "
        "restarts learning, and leaves likes and comments on the old version; when the "
        "operator would rather keep the old ad's likes and comments, create a new ad with "
        "meta_ads_create_ads and pause the old one instead. Catalogue, collection, "
        "partnership, poll, and lead ads can't change their creative here. Ad start and end "
        "times work only in sales and app promotion campaigns, must fall inside the ad set's "
        "schedule, and can't be in the past. Archived and deleted ads can only be renamed. "
        "Write ad text only from the operator's brief and approved brand material. Change "
        "status with meta_ads_update_status and ad set dates with meta_ads_update_ad_sets. "
        "Meta checks every change before any is made, and each result reports the values, "
        "creative, and review status Meta shows after the change."
    ),
    provider="meta_ads",
    label="Update Meta Ads",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=300,
    output_model=MetaAdsUpdateAdsOutput,
    integration_binding=META_ADS_WRITE_BINDING,
    availability_check=meta_ads_available,
    approval_display_args=_approval_display_args,
    # Edited entries are checked whole, and again by the tool before anything is sent.
    approval_input_model=MetaAdsUpdateAdsRequest,
    presentation=ToolPresentation(
        icon="meta_ads",
        running_label="Updating Meta Ads",
        completed_label="Updated Meta Ads",
        failed_label="Couldn't Update Meta Ads",
        approval_title="Change Meta Ads",
        approval_prompt="The agent wants to change these Meta ads.",
        approve_label="Approve & Update",
        arg_fields=(
            ToolFieldPresentation(
                key="changes", label="Ad Changes", editable=True, format="structured"
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
