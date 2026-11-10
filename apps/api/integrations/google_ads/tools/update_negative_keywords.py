# apps/api/integrations/google_ads/tools/update_negative_keywords.py

"""Approval-only tool that adds and removes negative keywords on campaigns, ad groups, and lists."""

import asyncio
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
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
from ..operations.build import CampaignBuild, dry_run_build, send_build
from ..operations.edits import CriterionChange, Edit, apply_edits, prepare_edits
from ..operations.mutation_outcomes import (
    GoogleAdsMutationLedger,
    GoogleAdsMutationProjection,
    build_mutation_ledger,
    freeze_fields,
    joined_ledger,
)
from ..operations.negative_keyword_criteria import (
    BlockedKeywords,
    LiveNegatives,
    list_use_key,
    negative_key,
    read_negative_keywords,
)
from .schemas.negative_keywords import (
    MAX_NEGATIVE_KEYWORD_TARGETS,
    GoogleAdsListNegatives,
    GoogleAdsNegativeKeywordChange,
    GoogleAdsNewListNegatives,
    GoogleAdsUpdateNegativeKeywordsOutput,
    GoogleAdsUpdateNegativeKeywordsRequest,
)
from .utils.accounts import approval_accounts
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

_OPERATION = "update_negative_keywords"
_FAMILY = "negative_keywords"
_IDENTITY = ("object",)
# Keyword rows and campaign rows for the most a call can change, with room for long names.
_MAX_PUBLIC_RESULT_CHARS = 1_000_000
_MAX_MODEL_OUTCOMES = 50

_NOUNS = {"campaign": "campaign", "ad_group": "ad group", "list": "list"}
_RESOURCES = {
    "campaign": ("campaignCriterion", "campaign"),
    "ad_group": ("adGroupCriterion", "adGroup"),
    "list": ("sharedCriterion", "sharedSet"),
}
_NOT_SHOWN = (
    "Google Ads couldn't check this before approval, so it wasn't changed. Ask the agent to "
    "prepare the change again."
)
_LIST_EXISTS = "A negative keyword list with this name already exists. Add to that list instead."
_CAMPAIGN_MISSING = "This campaign no longer exists in Google Ads."
_CAMPAIGN_REMOVED = "This campaign has been removed, so it can't use the list."
_BLOCKS = "Blocks “{keyword}”, a keyword you bid on in {ad_group}."
_LIST_BLOCKS = (
    "The list's “{negative}” would block “{keyword}”, a keyword you bid on in {ad_group}."
)
_INTERRUPTED = "This wasn't sent, because the change was interrupted."
_APPLIED = {"add": "added", "remove": "removed", "create": "created"}

type _Item = Literal["keyword", "campaign", "list"]
type _Action = Literal["add", "remove", "create"]


@dataclass(frozen=True, slots=True)
class _Planned:
    """One change, with what the card and the result say about it."""

    key: str
    item: _Item
    action: _Action
    # The keyword text, the campaign's name, or the new list's name.
    name: str
    match_type: str | None = None
    # A change to something that exists; a new list's parts are build steps instead.
    edit: CriterionChange | None = None
    # A new list's step: its resource and its create body without the list's name.
    resource: str = ""
    body: Mapping[str, Any] = field(default_factory=dict)
    campaign: str | None = None
    # Why it mustn't be sent, such as a problem shown on the card.
    refused: str | None = None

    @property
    def before(self) -> str | None:
        return self.edit.before if self.edit is not None else None


def _campaign_name(customer_id: str, campaign_id: str) -> str:
    return f"customers/{customer_id}/campaigns/{campaign_id}"


def _plan(entry: GoogleAdsNegativeKeywordChange) -> list[_Planned]:
    """Compiles one target's changes, with removals first, against nothing read yet."""
    owner = entry.target_key
    if isinstance(entry, GoogleAdsNewListNegatives):
        return _new_list_plan(entry)
    resource, owner_field = _RESOURCES[entry.kind]
    planned: list[_Planned] = []
    for action, keywords in (("remove", entry.remove), ("add", entry.add)):
        for keyword in keywords:
            body: dict[str, Any] = {
                owner_field: owner,
                "keyword": {"text": keyword.text, "matchType": keyword.match_type},
            }
            if entry.kind != "list":
                body["negative"] = True
            key = negative_key(owner, keyword.text, keyword.match_type)
            edit = CriterionChange(
                resource=resource,
                action=action,
                key=key,
                owner=owner,
                criterion=body if action == "add" else {},
            )
            planned.append(
                _Planned(key, "keyword", action, keyword.text, keyword.match_type, edit=edit)
            )
    if isinstance(entry, GoogleAdsListNegatives):
        for action, campaigns in (
            ("remove", entry.remove_from_campaigns),
            ("add", entry.apply_to_campaigns),
        ):
            for reference in campaigns:
                campaign = _campaign_name(reference.customer_id, reference.campaign_id)
                key = list_use_key(campaign, owner)
                edit = CriterionChange(
                    resource="campaignSharedSet",
                    action=action,
                    key=key,
                    owner=campaign,
                    criterion={"campaign": campaign, "sharedSet": owner} if action == "add" else {},
                )
                planned.append(
                    _Planned(key, "campaign", action, reference.label, edit=edit, campaign=campaign)
                )
    return planned


def _new_list_plan(entry: GoogleAdsNewListNegatives) -> list[_Planned]:
    owner = entry.target_key
    planned = [
        _Planned(
            owner,
            "list",
            "create",
            entry.new_list,
            resource="sharedSet",
            body={"name": entry.new_list, "type": "NEGATIVE_KEYWORDS"},
        )
    ]
    planned.extend(
        _Planned(
            negative_key(owner, keyword.text, keyword.match_type),
            "keyword",
            "add",
            keyword.text,
            keyword.match_type,
            resource="sharedCriterion",
            body={"keyword": {"text": keyword.text, "matchType": keyword.match_type}},
        )
        for keyword in entry.add
    )
    for reference in entry.apply_to_campaigns:
        campaign = _campaign_name(reference.customer_id, reference.campaign_id)
        planned.append(
            _Planned(
                list_use_key(campaign, owner),
                "campaign",
                "add",
                reference.label,
                resource="campaignSharedSet",
                body={"campaign": campaign},
                campaign=campaign,
            )
        )
    return planned


def _with_before(planned: _Planned, before: str | None) -> _Planned:
    if planned.edit is None:
        return planned
    return replace(planned, edit=replace(planned.edit, before=before))


def _refused(planned: Iterable[_Planned], reason: str | None) -> list[_Planned]:
    return [replace(item, refused=item.refused or reason) if reason else item for item in planned]


@dataclass(frozen=True, slots=True)
class _Live:
    """One account's live state, and what follows from it for each target."""

    negatives: LiveNegatives
    blocked: BlockedKeywords

    def target_problem(self, entry: GoogleAdsNegativeKeywordChange) -> str | None:
        if isinstance(entry, GoogleAdsNewListNegatives):
            names = self.negatives.list_names
            return _LIST_EXISTS if entry.new_list.casefold() in names else None
        owner = self.negatives.owners.get(entry.target_key)
        noun = _NOUNS[entry.kind]
        if owner is None:
            return f"This {noun} no longer exists in Google Ads."
        if owner.status == "REMOVED":
            return f"This {noun} has been removed, so its negative keywords can't change."
        return None

    def scope(self, entry: GoogleAdsNegativeKeywordChange) -> tuple[set[str], str | None]:
        """The campaigns, or the ad group, whose searches the target's negatives cover."""
        if entry.kind == "ad_group":
            return set(), entry.target_key
        if entry.kind == "campaign":
            return {entry.target_key}, None
        campaigns = set(self.negatives.list_campaigns.get(entry.target_key, ()))
        for item in _plan(entry):
            if item.item == "campaign" and item.campaign is not None:
                (campaigns.add if item.action == "add" else campaigns.discard)(item.campaign)
        return campaigns, None

    def item_problem(self, entry: GoogleAdsNegativeKeywordChange, item: _Planned) -> str | None:
        if item.action != "add" or item.item == "list":
            return None
        if item.item == "keyword" and item.match_type is not None:
            campaigns, ad_group = self.scope(entry)
            hit = self.blocked.first(
                item.name, item.match_type, campaigns=campaigns, ad_group=ad_group
            )
            return _BLOCKS.format(keyword=hit.text, ad_group=hit.ad_group_name) if hit else None
        owner = self.negatives.owners.get(item.campaign or "")
        if owner is None:
            return _CAMPAIGN_MISSING
        if owner.status == "REMOVED":
            return _CAMPAIGN_REMOVED
        removed = {keyword.pair for keyword in entry.remove}
        for text, match_type in self.negatives.list_keywords.get(entry.target_key, ()):
            if (text.casefold(), match_type) in removed:
                continue
            hit = self.blocked.first(
                text, match_type, campaigns={item.campaign or ""}, ad_group=None
            )
            if hit:
                return _LIST_BLOCKS.format(
                    negative=text, keyword=hit.text, ad_group=hit.ad_group_name
                )
        return None

    def plan(self, entry: GoogleAdsNegativeKeywordChange) -> tuple[list[_Planned], str | None]:
        """Plans one target against what's live, with each problem that stops a change."""
        problem = self.target_problem(entry)
        planned = [
            replace(
                _with_before(item, self.negatives.criteria.get(item.key)),
                name=self._name(item),
                refused=problem or self.item_problem(entry, item),
            )
            for item in _plan(entry)
        ]
        return planned, problem

    def _name(self, item: _Planned) -> str:
        owner = self.negatives.owners.get(item.campaign or "") if item.item == "campaign" else None
        return owner.name if owner else item.name


async def _read_live(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    changes: Sequence[GoogleAdsNegativeKeywordChange],
    *,
    check_keywords: bool,
) -> LiveNegatives:
    def ids(kind: str, attribute: str) -> list[str]:
        return [
            getattr(getattr(change, kind), attribute) for change in changes if change.kind == kind
        ]

    return await read_negative_keywords(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        campaign_ids=ids("campaign", "campaign_id"),
        ad_group_ids=ids("ad_group", "ad_group_id"),
        shared_set_ids=[
            change.negative_list.shared_set_id
            for change in changes
            if isinstance(change, GoogleAdsListNegatives)
        ],
        list_campaign_ids=[
            campaign.campaign_id for change in changes for campaign in change.campaigns
        ],
        check_keywords=check_keywords
        and any(item.action == "add" for change in changes for item in _plan(change)),
    )


def _list_build(
    customer_id: str, planned: Sequence[_Planned]
) -> tuple[CampaignBuild, list[_Planned]]:
    """Builds each new list with its keywords and campaigns, leaving out refused parts.

    Returns:
        The build, and the parts left out of it. A refused list leaves out all its parts.
    """
    build = CampaignBuild(customer_id)
    left_out: list[_Planned] = []
    owner: str | None = None
    for item in planned:
        if item.item == "list":
            owner = None
            if item.refused is None:
                owner = build.create("sharedSet", item.body, label=item.name, source=item.key)
            else:
                left_out.append(item)
            continue
        if owner is None or item.refused is not None:
            left_out.append(item)
            continue
        build.create(
            item.resource, {**item.body, "sharedSet": owner}, label=item.name, source=item.key
        )
    return build, left_out


def _new_list_parts(planned: Mapping[str, Sequence[_Planned]]) -> list[_Planned]:
    """Each new list's parts in order, with every part of a refused list refused too."""
    parts: list[_Planned] = []
    for items in planned.values():
        if items and items[0].item == "list" and items[0].edit is None:
            parts.extend(_refused(items, items[0].refused))
    return parts


async def google_ads_update_negative_keywords(
    ctx: RunContext[RuntimeDeps],
    entries: Annotated[
        list[GoogleAdsNegativeKeywordChange],
        Field(
            min_length=1,
            max_length=MAX_NEGATIVE_KEYWORD_TARGETS,
            description="One entry per campaign, ad group, or list, with only what changes.",
        ),
    ],
) -> ToolReturn[dict[str, Any]]:
    request = validated_request(GoogleAdsUpdateNegativeKeywordsRequest, {"entries": entries})
    display = approved_display_args(ctx).get("_checks")
    shown: Mapping[str, Any] = display if isinstance(display, Mapping) else {}
    by_account: dict[str, list[GoogleAdsNegativeKeywordChange]] = defaultdict(list)
    for change in request.entries:
        by_account[change.customer_id].append(change)

    async def operation(entry: ResolvedContextEntry, _selected: Sequence[Any]) -> Any:
        changes = by_account[entry.external_id]
        client: GoogleAdsClient | None = None
        planned: dict[str, list[_Planned]] = {}
        pending: PendingIntegrationOperationDetail | None = None

        async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
            nonlocal client, pending
            client = await google_ads_client(ctx, entry)
            for change in changes:
                planned[change.target_key] = _approved_plan(change, shown.get(change.target_key))
            pending = _pending_detail(entry, changes, planned)
            return pending

        async def execute() -> IntegrationAuditOutcome[dict[str, Any]]:
            if client is None or pending is None or not planned:
                raise RuntimeError("Google Ads negative keyword preparation did not complete")
            try:
                ledger = await _send(client, entry, changes, planned)
            except asyncio.CancelledError as exc:
                attach_interrupted_evidence(exc, pending, identity_keys=_IDENTITY)
                raise
            detail = terminal_operation_detail(pending, ledger, identity_keys=_IDENTITY)
            data = _result(entry, changes, planned, shown, ledger)
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
            tool_name="google_ads_update_negative_keywords",
            operation=_OPERATION,
            execute=execute,
            prepare_pending_operation=prepare_pending_operation,
        )

    # Every reference names its account; a list's campaigns are always in the list's account.
    references = [
        reference
        for change in request.entries
        for reference in (
            *([] if isinstance(change, GoogleAdsNewListNegatives) else [_target(change)]),
            *change.campaigns,
        )
    ]
    results = await run_context_targets(
        ctx, binding=GOOGLE_ADS_WRITE_BINDING, references=references, operation=operation
    )
    return split_fan_out_tool_return(results)


def _target(change: GoogleAdsNegativeKeywordChange) -> Any:
    return getattr(change, {"list": "negative_list"}.get(change.kind, change.kind))


async def _send(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    changes: Sequence[GoogleAdsNegativeKeywordChange],
    planned: Mapping[str, Sequence[_Planned]],
) -> GoogleAdsMutationLedger:
    """Sends changes to what exists, then builds new lists, and records both in one ledger."""
    edits = [
        replace(item.edit, refused=item.refused)
        for items in planned.values()
        for item in items
        if item.edit is not None
    ]
    parts = _new_list_parts(planned)
    ledgers: list[GoogleAdsMutationLedger] = []
    if edits:
        try:
            result = await apply_edits(
                client,
                customer_id=entry.external_id,
                login_customer_id=login_customer_id(entry),
                edits=edits,
                read=_reader(client, entry, changes),
                family=_FAMILY,
                operation=_OPERATION,
            )
        except asyncio.CancelledError as exc:
            if parts:
                exc.ledger = joined_ledger(
                    [exc.ledger, _failed_ledger(parts, "CANCELLED", _INTERRUPTED)], family=_FAMILY
                )
            raise
        ledgers.append(result.ledger)
    if parts:
        ledgers.extend(await _send_lists(client, entry, parts, ledgers))
    return joined_ledger(ledgers, family=_FAMILY)


async def _send_lists(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    parts: Sequence[_Planned],
    earlier: Sequence[GoogleAdsMutationLedger],
) -> list[GoogleAdsMutationLedger]:
    build, left_out = _list_build(entry.external_id, parts)
    ledgers: list[GoogleAdsMutationLedger] = []
    refused = [replace(item, refused=item.refused or _NOT_SHOWN) for item in left_out]
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
                    *([_failed_ledger(refused, "REFUSED")] if refused else []),
                ],
                family=_FAMILY,
            )
            raise
        ledgers.append(_keyed(built.ledger, keys))
    if refused:
        ledgers.append(_failed_ledger(refused, "REFUSED"))
    return ledgers


def _keyed(ledger: GoogleAdsMutationLedger, keys: Sequence[str]) -> GoogleAdsMutationLedger:
    """Names each build step by its change's key, as the audit record names every change."""
    parents = []
    for parent, key in zip(ledger.parents, keys, strict=True):
        identity = freeze_fields({"object": key, "settings": "create"})
        effects = tuple(replace(effect, fields=identity) for effect in parent.effects)
        parents.append(replace(parent, identity=identity, effects=effects))
    return replace(ledger, parents=tuple(parents))


def _failed_ledger(
    parts: Sequence[_Planned], code: str, message: str | None = None
) -> GoogleAdsMutationLedger:
    fields = [{"object": item.key, "settings": "create"} for item in parts]
    return build_mutation_ledger(
        family=_FAMILY,
        action="update",
        parent_fields=fields,
        skipped_indices={},
        submitted=list(enumerate(fields)),
        outcomes=[("failed", None, code, message or item.refused or _NOT_SHOWN) for item in parts],
        projection=GoogleAdsMutationProjection(
            applied_key="updated", skipped_key="already_set", errors_key="errors"
        ),
    )


def _reader(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    changes: Sequence[GoogleAdsNegativeKeywordChange],
) -> Callable[[Sequence[Edit]], Awaitable[Mapping[str, Mapping[str, Any]]]]:
    existing = [change for change in changes if not isinstance(change, GoogleAdsNewListNegatives)]

    async def read(_edits: Sequence[Edit]) -> Mapping[str, Mapping[str, Any]]:
        live = await _read_live(client, entry, existing, check_keywords=False)
        return live.values()

    return read


def _approved_plan(change: GoogleAdsNegativeKeywordChange, check: Any) -> list[_Planned]:
    """Plans against what the approver saw, so `apply_edits` refuses anything changed since.

    A target the operator added on the card is sent only once Google checked it.
    """
    planned = _plan(change)
    if not isinstance(check, Mapping) or check.get("unavailable") is not False:
        return _refused(planned, _NOT_SHOWN)
    shown = {
        (row.get("item"), row.get("key")): row
        for row in check.get("rows") or ()
        if isinstance(row, Mapping)
    }
    problem = check.get("problem") if isinstance(check.get("problem"), str) else None
    approved: list[_Planned] = []
    for item in planned:
        if item.item == "list":
            approved.append(replace(item, refused=problem))
            continue
        row = shown.get((item.item, _row_key(item)))
        if row is None or row.get("action") != item.action:
            approved.append(replace(item, refused=_NOT_SHOWN))
            continue
        before = row.get("before") if isinstance(row.get("before"), str) else None
        reason = problem or (row.get("problem") if isinstance(row.get("problem"), str) else None)
        approved.append(
            replace(
                _with_before(item, before), name=str(row.get("name") or item.name), refused=reason
            )
        )
    return approved


def _row_key(item: _Planned) -> str:
    """How the card names a row within its target, the same way the server checked it."""
    if item.item == "keyword":
        return f"{item.match_type}:{' '.join(item.name.casefold().split())}"
    return item.campaign or item.key


def _pending_detail(
    entry: ResolvedContextEntry,
    changes: Sequence[GoogleAdsNegativeKeywordChange],
    planned: Mapping[str, Sequence[_Planned]],
) -> PendingIntegrationOperationDetail:
    groups: dict[tuple[str, str, str], list[IntegrationOperationIntent]] = defaultdict(list)
    for change in changes:
        for item in planned[change.target_key]:
            groups[change.kind, item.item, item.action].append(
                IntegrationOperationIntent(fields={"object": item.key})
            )
    return PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key=f"{kind}:{item}:{action}",
                action=action,
                entity_type=f"google_ads_{kind}_negative_{item}",
                items=items,
            )
            for (kind, item, action), items in groups.items()
        ],
    )


def _result(
    entry: ResolvedContextEntry,
    changes: Sequence[GoogleAdsNegativeKeywordChange],
    planned: Mapping[str, Sequence[_Planned]],
    shown: Mapping[str, Any],
    ledger: GoogleAdsMutationLedger,
) -> dict[str, Any]:
    """Returns every row for the card, and the counts with what didn't happen for the agent."""
    parents = {dict(parent.identity)["object"]: parent for parent in ledger.parents}
    outcomes: list[dict[str, Any]] = []
    for change in changes:
        check = shown.get(change.target_key)
        target_name = (
            check.get("name") if isinstance(check, Mapping) and check.get("name") else None
        ) or _target_label(change)
        for item in planned[change.target_key]:
            parent = parents[item.key]
            effect = parent.effects[0] if parent.effects else None
            if parent.decision == "skipped":
                outcome = "already_set" if item.action == "add" else "not_found"
            elif effect is None or effect.outcome == "unverified":
                outcome = "unverified"
            else:
                outcome = _APPLIED[item.action] if effect.outcome == "applied" else "failed"
            outcomes.append(
                {
                    "target_kind": change.kind,
                    "target_name": str(target_name),
                    "item": item.item,
                    "action": item.action,
                    "name": item.name,
                    "match_type": item.match_type,
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
            "created",
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


def _target_label(change: GoogleAdsNegativeKeywordChange) -> str:
    if isinstance(change, GoogleAdsNewListNegatives):
        return change.new_list
    return _target(change).label


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Adds each account's facts, and per target what's live, the problems, and Google's dry run."""
    request = GoogleAdsUpdateNegativeKeywordsRequest.model_validate(args)
    by_account: dict[str, list[GoogleAdsNegativeKeywordChange]] = defaultdict(list)
    for change in request.entries:
        by_account[change.customer_id].append(change)
    active = deps.active_context
    entries = {
        entry.external_id: entry
        for entry in (active.compatible_entries(GOOGLE_ADS_WRITE_BINDING) if active else ())
        if entry.write_allowed
    }
    checks: dict[str, dict[str, Any]] = {}
    for customer_id, changes in by_account.items():
        checks.update(await _account_checks(deps, entries.get(customer_id), changes))
    accounts = approval_accounts(entries[item] for item in by_account if item in entries)
    return {**args, "_accounts": accounts, "_checks": checks}


async def _account_checks(
    deps: RuntimeDeps,
    entry: ResolvedContextEntry | None,
    changes: Sequence[GoogleAdsNegativeKeywordChange],
) -> dict[str, dict[str, Any]]:
    """Reads one account and dry runs its changes; an unreadable account is unavailable."""
    try:
        if entry is None:
            raise LookupError("Google Ads account not selected")
        client = await google_ads_client_for_principal(
            deps.db, actor=deps.user, workspace=deps.workspace, entry=entry
        )
        negatives = await _read_live(client, entry, changes, check_keywords=True)
        live = _Live(negatives, BlockedKeywords(negatives.bid_keywords))
        plans = {change.target_key: live.plan(change) for change in changes}
        google = await _dry_run(client, entry, plans)
    except (IntegrationError, LookupError):
        return {change.target_key: {"unavailable": True} for change in changes}
    return {
        change.target_key: _check(change, negatives, *plans[change.target_key], google)
        for change in changes
    }


async def _dry_run(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    plans: Mapping[str, tuple[list[_Planned], str | None]],
) -> dict[str, str]:
    """Returns Google's reason for each change it would reject, by key.

    A rejection of the whole list build applies to each new list.
    """
    planned = {key: items for key, (items, _problem) in plans.items()}
    edits = [
        replace(item.edit, refused=item.refused)
        for items in planned.values()
        for item in items
        if item.edit is not None
    ]
    problems: dict[str, str] = {}
    if edits:
        values = {edit.key: {"resourceName": edit.before} for edit in edits if edit.before}

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
    build, _left_out = _list_build(entry.external_id, _new_list_parts(planned))
    if build.steps:
        for problem in await dry_run_build(
            client, build, login_customer_id=login_customer_id(entry), operation=_OPERATION
        ):
            keys = (
                [problem.step.source]
                if problem.step
                else [step.source for step in build.steps if step.resource == "sharedSet"]
            )
            for key in keys:
                problems.setdefault(key, f"Google says: {problem.message}")
    return problems


def _check(
    change: GoogleAdsNegativeKeywordChange,
    negatives: LiveNegatives,
    planned: Sequence[_Planned],
    problem: str | None,
    google: Mapping[str, str],
) -> dict[str, Any]:
    """Builds the card's view of one target, and the live state approval plans against."""
    if isinstance(change, GoogleAdsNewListNegatives):
        problem = problem or google.get(change.target_key)
        owner = None
    else:
        owner = negatives.owners.get(change.target_key)
    rows = []
    for item in planned:
        if item.item == "list":
            continue
        reason = None if problem else item.refused or google.get(item.key)
        if item.action == "remove":
            state = "change" if item.before else "not_found"
        else:
            state = "already_set" if item.before else "change"
        rows.append(
            {
                "item": item.item,
                "key": _row_key(item),
                "action": item.action,
                "name": item.name,
                "match_type": item.match_type,
                "before": item.before,
                "state": state,
                "problem": reason,
            }
        )
    campaign = negatives.owners.get(owner.campaign) if owner and owner.campaign else None
    return {
        "unavailable": False,
        "kind": change.kind,
        "name": owner.name if owner else _target_label(change),
        "status": owner.status if owner else None,
        "campaign_name": campaign.name if campaign else None,
        "problem": problem,
        "rows": rows,
    }


DEFINITION = RuntimeToolDefinition(
    name="google_ads_update_negative_keywords",
    function=google_ads_update_negative_keywords,
    description=(
        "Add and remove Google Ads negative keywords on campaigns, ad groups, and negative "
        "keyword lists, and choose which campaigns use a list, in one approval. Each entry "
        "names one target by kind: campaign, ad_group, list (an existing negative keyword "
        "list), or new_list (the new list's name, created in the account of its "
        "apply_to_campaigns, which it needs). Each entry "
        "carries add and remove lists of {text, match_type} where match_type is EXACT, "
        "PHRASE, or BROAD; text is the words without match type symbols. A list entry can "
        "also apply_to_campaigns and remove_from_campaigns. Up to 1,000 keywords per call "
        "across entries. To add the same negatives to several campaigns, give each campaign "
        "its own entry. A negative already in place is reported already_set, and a removal "
        "that isn't there is reported not_found, without a change. A negative that would "
        "block a keyword the account bids on in the same campaign or ad group is refused. "
        "To block or add terms from a search terms report, use "
        "google_ads_optimise_search_terms instead."
    ),
    provider="google_ads",
    label="Update Google Ads Negative Keywords",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=300,
    output_model=GoogleAdsUpdateNegativeKeywordsOutput,
    max_public_result_chars=_MAX_PUBLIC_RESULT_CHARS,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    approval_display_args=_approval_display_args,
    approval_input_model=GoogleAdsUpdateNegativeKeywordsRequest,
    # An edit changes what Google has to answer, so approval waits for a new check.
    approval_review_fields=("entries",),
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Updating Negative Keywords",
        completed_label="Updated Negative Keywords",
        failed_label="Couldn't Update Negative Keywords",
        approval_title="Update Negative Keywords",
        approval_prompt="The agent wants to change which searches these Google Ads campaigns block.",
        approve_label="Approve & Update",
        arg_fields=(
            ToolFieldPresentation(
                key="entries",
                label="Negative Keywords",
                editable=True,
                format="structured",
                # The first kind authorises a review; the others are the targets' kinds.
                entity_kinds=(
                    "google_ads_campaign",
                    "google_ads_ad_group",
                    "google_ads_shared_set",
                ),
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
