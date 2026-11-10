# apps/api/integrations/google_ads/tools/update_ad_groups.py

"""Approval-only tool that changes the names, bids, targets, URL options, and ad rotation of Google Ads ad groups."""

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import replace
from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import RunContext

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
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.context.targeted import run_context_targets
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..client import GoogleAdsClient
from ..operations.ad_group_settings import (
    CAMPAIGN_BIDDING_GUARDS,
    SETTING_PATHS,
    AdGroupSetting,
    LiveAdGroupSettings,
    api_value,
    card_settings,
    read_ad_group_settings,
)
from ..operations.edits import Edit, EditResult, FieldChange, apply_edits, prepare_edits
from .schemas.ad_group_updates import (
    MAX_AD_GROUP_UPDATES,
    GoogleAdsAdGroupUpdate,
    GoogleAdsUpdateAdGroupsOutput,
    GoogleAdsUpdateAdGroupsRequest,
)
from .utils.accounts import NOT_SHOWN, account_facts, approval_accounts, writable_entries
from .utils.ad_group_builds import STRATEGY_NAMES
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

_OPERATION = "update_ad_groups"
_IDENTITY = ("object",)
_OUTCOMES = {"applied": "updated", "failed": "failed", "unverified": "unverified"}
_BIDS: tuple[AdGroupSetting, ...] = ("cpc_bid", "target_cpa", "target_roas")
_BID_NAMES = {"cpc_bid": "CPC bid", "target_cpa": "target CPA", "target_roas": "target ROAS"}
# The campaign target each ad group override needs under a standard strategy.
_CAMPAIGN_TARGETS = {
    "target_cpa": ("MAXIMIZE_CONVERSIONS", "target CPA"),
    "target_roas": ("MAXIMIZE_CONVERSION_VALUE", "target ROAS"),
}

_MISSING = "This ad group no longer exists in Google Ads."
_REMOVED = "This ad group has been removed, so its settings can't change."
_CAMPAIGN_REMOVED = "This ad group's campaign has been removed, so its settings can't change."
_NOT_USED = "{campaign} uses {strategy}, so Google doesn't use an ad group {bid}."
_NO_CAMPAIGN_TARGET = (
    "{campaign} has no {target}, so its ad groups can't override one. Set a {target} on the "
    "campaign first."
)


def _bid_problem(setting: AdGroupSetting, live: LiveAdGroupSettings) -> str | None:
    """Names the campaign's strategy when Google wouldn't use the bid or target being set."""
    if setting in live.bids_used:
        return None
    strategy, target = _CAMPAIGN_TARGETS.get(setting, (None, ""))
    if live.strategy_type == strategy and not live.portfolio:
        return _NO_CAMPAIGN_TARGET.format(campaign=live.campaign_name, target=target)
    return _NOT_USED.format(
        campaign=live.campaign_name, strategy=_strategy_name(live), bid=_BID_NAMES[setting]
    )


def _strategy_name(live: LiveAdGroupSettings) -> str:
    name = STRATEGY_NAMES.get(live.strategy_type, "its own bidding")
    return f"a {name} portfolio strategy" if live.portfolio else name


def _edit(change: GoogleAdsAdGroupUpdate) -> FieldChange:
    bids = any(setting in _BIDS for setting in change.requested)
    return FieldChange(
        resource="adGroup",
        resource_name=change.resource_name,
        requested={
            SETTING_PATHS[setting]: api_value(setting, value)
            for setting, value in change.requested.items()
        },
        compared=CAMPAIGN_BIDDING_GUARDS if bids else (),
    )


def _setting_problems(
    change: GoogleAdsAdGroupUpdate, live: LiveAdGroupSettings
) -> dict[AdGroupSetting, str]:
    """Refuses a bid or target the campaign's strategy doesn't use; removing one always works."""
    current = live.settings()
    problems: dict[AdGroupSetting, str] = {}
    for setting in _BIDS:
        value = change.requested.get(setting)
        if value is not None and value != current[setting] and (p := _bid_problem(setting, live)):
            problems[setting] = p
    return problems


def _ad_group_problem(live: LiveAdGroupSettings | None) -> str | None:
    if live is None:
        return _MISSING
    if live.status == "REMOVED":
        return _REMOVED
    return _CAMPAIGN_REMOVED if live.campaign_status == "REMOVED" else None


async def google_ads_update_ad_groups(
    ctx: RunContext[RuntimeDeps],
    changes: Annotated[
        list[GoogleAdsAdGroupUpdate],
        Field(
            min_length=1,
            max_length=MAX_AD_GROUP_UPDATES,
            description="One entry per ad group, with only the settings that change.",
        ),
    ],
) -> dict[str, Any]:
    request = validated_request(GoogleAdsUpdateAdGroupsRequest, {"changes": changes})
    display = approved_display_args(ctx).get("_checks")
    shown: Mapping[str, Any] = display if isinstance(display, Mapping) else {}
    by_key = {
        (change.ad_group.customer_id, change.ad_group.ad_group_id): change
        for change in request.changes
    }

    async def operation(entry: ResolvedContextEntry, selected: Sequence[Any]) -> Any:
        account_changes = [
            by_key[reference.customer_id, reference.ad_group_id] for reference in selected
        ]
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
            pending = _pending_detail(entry, account_changes, shown)
            return pending

        async def execute() -> IntegrationAuditOutcome[dict[str, Any]]:
            if client is None or pending is None or not edits:
                raise RuntimeError("Google Ads ad group update preparation did not complete")
            try:
                result = await apply_edits(
                    client,
                    customer_id=entry.external_id,
                    login_customer_id=login_customer_id(entry),
                    edits=edits,
                    read=_reader(client, entry, account_changes),
                    family="ad_group_settings",
                    operation=_OPERATION,
                )
            except asyncio.CancelledError as exc:
                attach_interrupted_evidence(exc, pending, identity_keys=_IDENTITY)
                raise
            detail = terminal_operation_detail(pending, result.ledger, identity_keys=_IDENTITY)
            data = _result(entry, account_changes, shown, result)
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
            tool_name="google_ads_update_ad_groups",
            operation=_OPERATION,
            execute=execute,
            prepare_pending_operation=prepare_pending_operation,
        )

    results = await run_context_targets(
        ctx,
        binding=GOOGLE_ADS_WRITE_BINDING,
        references=[change.ad_group for change in request.changes],
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


def _approved_edit(change: GoogleAdsAdGroupUpdate, check: Any) -> FieldChange:
    """Builds the edit against the values the approver saw, so `apply_edits` refuses stale ones.

    The check must be for exactly these settings, and any problem it showed still stands.
    """
    edit = _edit(change)
    if (
        not isinstance(check, Mapping)
        or check.get("unavailable") is not False
        or check.get("requested") != change.requested
    ):
        return replace(edit, refused=NOT_SHOWN)
    problems = check.get("problems")
    problem = check.get("problem") or next(
        iter(problems.values() if isinstance(problems, Mapping) else ()), None
    )
    if problem:
        return replace(edit, refused=str(problem))
    values = check.get("values")
    return replace(edit, before=edit.live(values if isinstance(values, Mapping) else {}) or {})


def _reader(
    client: GoogleAdsClient, entry: ResolvedContextEntry, changes: Sequence[GoogleAdsAdGroupUpdate]
) -> Callable[[Sequence[Edit]], Awaitable[Mapping[str, Mapping[str, Any]]]]:
    ad_group_ids = [change.ad_group.ad_group_id for change in changes]

    async def read(_edits: Sequence[Edit]) -> Mapping[str, Mapping[str, Any]]:
        live = await read_ad_group_settings(
            client,
            customer_id=entry.external_id,
            login_customer_id=login_customer_id(entry),
            ad_group_ids=ad_group_ids,
        )
        return {name: item.values for name, item in live.items()}

    return read


def _text(check: Any, key: str) -> str:
    value = check.get(key) if isinstance(check, Mapping) else None
    return str(value or "")


def _name(change: GoogleAdsAdGroupUpdate, check: Any) -> str:
    return _text(check, "name") or change.ad_group.label


def _pending_detail(
    entry: ResolvedContextEntry,
    changes: Sequence[GoogleAdsAdGroupUpdate],
    shown: Mapping[str, Any],
) -> PendingIntegrationOperationDetail:
    """Records which settings change on each ad group; URL values stay out of the audit record."""
    return PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key="ad_group:update-settings",
                action="update_settings",
                entity_type="google_ads_ad_group",
                items=[
                    IntegrationOperationIntent(
                        fields={
                            "object": change.resource_name,
                            "name": _name(change, shown.get(change.resource_name)),
                            "settings": ",".join(change.requested),
                        }
                    )
                    for change in changes
                ],
            )
        ],
    )


def _result(
    entry: ResolvedContextEntry,
    changes: Sequence[GoogleAdsAdGroupUpdate],
    shown: Mapping[str, Any],
    result: EditResult,
) -> dict[str, Any]:
    parents = {dict(parent.identity)["object"]: parent for parent in result.ledger.parents}
    ad_groups = []
    for change in changes:
        name = change.resource_name
        check = shown.get(name)
        current = check.get("current") if isinstance(check, Mapping) else None
        current = current if isinstance(current, Mapping) else {}
        parent = parents[name]
        effect = parent.effects[0] if parent.effects else None
        skipped = parent.decision == "skipped"
        outcome = (
            "already_set" if skipped else _OUTCOMES[effect.outcome if effect else "unverified"]
        )
        after = result.after.get(name)
        after_settings = card_settings(after) if after is not None else {}
        settings = []
        for setting, requested in change.requested.items():
            before = current.get(setting)
            settings.append(
                {
                    "setting": setting,
                    "before": before,
                    "requested": requested,
                    "after": before if skipped else after_settings.get(setting),
                    "outcome": "already_set" if before == requested else outcome,
                }
            )
        ad_groups.append(
            {
                "resource_name": name,
                "ad_group_id": change.ad_group.ad_group_id,
                "name": _name(change, check),
                "campaign_name": _text(check, "campaign_name"),
                "read_back": skipped or after is not None,
                "settings": settings,
                "error_code": effect.error_code if effect is not None else None,
                "message": effect.message if effect is not None else None,
            }
        )
    return {
        "account_id": entry.external_id,
        "currency": account_facts(entry).currency,
        "ad_groups": ad_groups,
    }


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Adds each account's facts and, per ad group, its live settings and Google's dry run."""
    request = GoogleAdsUpdateAdGroupsRequest.model_validate(args)
    by_account: dict[str, list[GoogleAdsAdGroupUpdate]] = defaultdict(list)
    for change in request.changes:
        by_account[change.ad_group.customer_id].append(change)
    entries = writable_entries(deps.active_context)
    checks: dict[str, dict[str, Any]] = {}
    for customer_id, changes in by_account.items():
        checks.update(await _account_checks(deps, entries.get(customer_id), changes))
    accounts = approval_accounts(entries[item] for item in by_account if item in entries)
    return {**args, "_accounts": accounts, "_checks": checks}


async def _account_checks(
    deps: RuntimeDeps,
    entry: ResolvedContextEntry | None,
    changes: Sequence[GoogleAdsAdGroupUpdate],
) -> dict[str, dict[str, Any]]:
    """Reads one account's ad groups and dry runs the changes; an unreadable account is unavailable."""
    try:
        if entry is None:
            raise LookupError("Google Ads account not selected")
        client = await google_ads_client_for_principal(
            deps.db, actor=deps.user, workspace=deps.workspace, entry=entry
        )
        live = await read_ad_group_settings(
            client,
            customer_id=entry.external_id,
            login_customer_id=login_customer_id(entry),
            ad_group_ids=[change.ad_group.ad_group_id for change in changes],
        )
        problems = {
            change.resource_name: _setting_problems(change, item)
            for change in changes
            if (item := live.get(change.resource_name)) is not None
        }
        rejected = await _dry_run(client, entry, changes, live, problems)
    except (IntegrationError, LookupError):
        return {change.resource_name: {"unavailable": True} for change in changes}
    return {
        change.resource_name: _check(
            change,
            live.get(change.resource_name),
            problems.get(change.resource_name, {}),
            rejected.get(change.resource_name),
        )
        for change in changes
    }


async def _dry_run(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    changes: Sequence[GoogleAdsAdGroupUpdate],
    live: Mapping[str, LiveAdGroupSettings],
    problems: Mapping[str, Mapping[AdGroupSetting, str]],
) -> dict[str, str]:
    """Returns Google's rejection per ad group, asking only about ad groups with no problem yet."""
    checked = [
        _edit(change)
        for change in changes
        if _ad_group_problem(live.get(change.resource_name)) is None
        and not problems.get(change.resource_name)
    ]
    if not checked:
        return {}

    async def read(edits: Sequence[Edit]) -> Mapping[str, Mapping[str, Any]]:
        return {edit.key: live[edit.key].values for edit in edits}

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
    change: GoogleAdsAdGroupUpdate,
    live: LiveAdGroupSettings | None,
    problems: Mapping[AdGroupSetting, str],
    rejected: str | None,
) -> dict[str, Any]:
    """Builds the card's view of one ad group, and the live values approval plans against."""
    return {
        "unavailable": False,
        "name": change.ad_group.label if live is None else live.values.get("name"),
        "campaign_name": live.campaign_name if live else None,
        "status": live.status if live else None,
        # The campaign's strategy, and the bid fields it uses, so the card can explain the rest.
        "strategy_name": _strategy_name(live) if live else None,
        "bids_used": sorted(live.bids_used) if live else [],
        "current": live.settings() if live else {},
        "requested": change.requested,
        # What approval plans against, in Google's terms, for the paths the change reads.
        "values": (_edit(change).live(live.values) or {}) if live else {},
        "problem": _ad_group_problem(live) or rejected,
        "problems": dict(problems),
    }


DEFINITION = RuntimeToolDefinition(
    name="google_ads_update_ad_groups",
    function=google_ads_update_ad_groups,
    description=(
        "Change settings on existing Google Ads ad groups, up to 50 ad groups per call, in one "
        "approval. Each entry names one ad group (a google_ads_ad_group reference) and only the "
        "settings that change: name; cpc_bid, the default click bid, which Google uses only "
        "when the campaign uses Manual CPC; target_cpa, overriding the campaign's target CPA, "
        "only when the campaign uses Target CPA or Maximise Conversions with a target CPA; "
        "target_roas as a ratio (3.5 is 350%), overriding the campaign's target ROAS, only "
        "when the campaign uses Target ROAS or Maximise Conversion Value with a target ROAS "
        'and no portfolio strategy; target_cpa or target_roas "none" removes the override; '
        "url_options with final_url_suffix, tracking_template, and custom_parameters (up to 8 "
        "key and value pairs, replacing the ad group's list), where an empty value clears it; "
        "and ad_rotation, OPTIMIZE or ROTATE_FOREVER. Money is in the account currency. "
        "Status, keywords, ads, targeting, and removal aren't supported here. Each result "
        "reports what Google Ads shows after the change."
    ),
    provider="google_ads",
    label="Update Google Ads Ad Groups",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=120,
    output_model=GoogleAdsUpdateAdGroupsOutput,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    approval_display_args=_approval_display_args,
    approval_input_model=GoogleAdsUpdateAdGroupsRequest,
    # An edit changes what Google has to answer, so approval waits for a new check.
    approval_review_fields=("changes",),
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Updating Google Ads Ad Groups",
        completed_label="Updated Google Ads Ad Groups",
        failed_label="Couldn't Update Google Ads Ad Groups",
        approval_title="Change Ad Group Settings",
        approval_prompt="The agent wants to change settings on these Google Ads ad groups.",
        approve_label="Approve & Update",
        arg_fields=(
            ToolFieldPresentation(
                key="changes",
                label="Ad Group Changes",
                editable=True,
                format="structured",
                entity_kinds=("google_ads_ad_group",),
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
