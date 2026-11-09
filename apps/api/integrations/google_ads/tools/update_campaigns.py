# apps/api/integrations/google_ads/tools/update_campaigns.py

"""Approval-only tool that changes the names, dates, URL options, and networks of Google Ads campaigns."""

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import replace
from datetime import date
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
from ..operations.campaign_settings import (
    SETTING_PATHS,
    CampaignSetting,
    LiveCampaignSettings,
    api_value,
    card_value,
    read_campaign_settings,
)
from ..operations.edits import Edit, EditResult, FieldChange, apply_edits, prepare_edits
from .schemas.campaign_updates import (
    MAX_CAMPAIGN_UPDATES,
    GoogleAdsCampaignUpdate,
    GoogleAdsUpdateCampaignsOutput,
    GoogleAdsUpdateCampaignsRequest,
)
from .utils.accounts import account_facts, approval_accounts
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

_OPERATION = "update_campaigns"
_IDENTITY = ("object",)
_OUTCOMES = {"applied": "updated", "failed": "failed", "unverified": "unverified"}
# The channels on which each network can change. Search campaigns always show on Google Search.
_NETWORK_CHANNELS: dict[CampaignSetting, frozenset[str]] = {
    "search_partners": frozenset({"SEARCH", "SHOPPING"}),
    "display_expansion": frozenset({"SEARCH"}),
}

_MISSING = "This campaign no longer exists in Google Ads."
_REMOVED = "This campaign has been removed, so its settings can't change."
_NOT_SHOWN = (
    "Google Ads couldn't check this before approval, so it wasn't changed. Ask the agent to "
    "prepare the change again."
)
_STARTED = "This campaign has already started, so Google Ads won't change its start date."
_START_PAST = "Choose a start date after today."
_END_PAST = "Choose an end date of today or later."
_END_BEFORE_START = "The end date must be on or after the start date ({start})."
_NETWORK = {
    "search_partners": "Search Partners can only change on Search and Shopping campaigns.",
    "display_expansion": "Display expansion can only change on Search campaigns.",
}


def _edit(change: GoogleAdsCampaignUpdate) -> FieldChange:
    return FieldChange(
        resource="campaign",
        resource_name=change.resource_name,
        requested={
            SETTING_PATHS[setting]: api_value(setting, value)
            for setting, value in change.requested.items()
        },
    )


def _setting_problems(
    change: GoogleAdsCampaignUpdate, live: LiveCampaignSettings, today: date
) -> dict[CampaignSetting, str]:
    """Google's date and network rules for the settings that change, checked before asking it."""
    requested = change.requested
    current = live.settings()
    changing = {s: v for s, v in requested.items() if v != current[s]}
    problems: dict[CampaignSetting, str] = {}
    now = today.isoformat()
    live_start = current["start_date"]
    if "start_date" in changing:
        if live_start is not None and live_start <= now:
            problems["start_date"] = _STARTED
        elif changing["start_date"] <= now:
            problems["start_date"] = _START_PAST
    if "end_date" in changing and changing["end_date"] is not None and changing["end_date"] < now:
        problems["end_date"] = _END_PAST
    start = requested.get("start_date", live_start)
    end = requested["end_date"] if "end_date" in requested else current["end_date"]
    if start and end and end < start and not problems.keys() & {"start_date", "end_date"}:
        setting: CampaignSetting = "end_date" if "end_date" in changing else "start_date"
        if setting in changing:
            problems[setting] = _END_BEFORE_START.format(start=start)
    for network, channels in _NETWORK_CHANNELS.items():
        if network in changing and live.channel not in channels:
            problems[network] = _NETWORK[network]
    return problems


def _campaign_problem(live: LiveCampaignSettings | None) -> str | None:
    if live is None:
        return _MISSING
    return _REMOVED if live.status == "REMOVED" else None


async def google_ads_update_campaigns(
    ctx: RunContext[RuntimeDeps],
    changes: Annotated[
        list[GoogleAdsCampaignUpdate],
        Field(
            min_length=1,
            max_length=MAX_CAMPAIGN_UPDATES,
            description="One entry per campaign, with only the settings that change.",
        ),
    ],
) -> dict[str, Any]:
    request = validated_request(GoogleAdsUpdateCampaignsRequest, {"changes": changes})
    display = approved_display_args(ctx).get("_checks")
    shown: Mapping[str, Any] = display if isinstance(display, Mapping) else {}
    by_key = {
        (change.campaign.customer_id, change.campaign.campaign_id): change
        for change in request.changes
    }

    async def operation(entry: ResolvedContextEntry, selected: Sequence[Any]) -> Any:
        account_changes = [
            by_key[reference.customer_id, reference.campaign_id] for reference in selected
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
                raise RuntimeError("Google Ads campaign update preparation did not complete")
            try:
                result = await apply_edits(
                    client,
                    customer_id=entry.external_id,
                    login_customer_id=login_customer_id(entry),
                    edits=edits,
                    read=_reader(client, entry, account_changes),
                    family="campaign_settings",
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
            tool_name="google_ads_update_campaigns",
            operation=_OPERATION,
            execute=execute,
            prepare_pending_operation=prepare_pending_operation,
        )

    results = await run_context_targets(
        ctx,
        binding=GOOGLE_ADS_WRITE_BINDING,
        references=[change.campaign for change in request.changes],
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


def _approved_edit(change: GoogleAdsCampaignUpdate, check: Any) -> FieldChange:
    """Builds the edit against the values the approver saw, so `apply_edits` refuses stale ones.

    The check must be for exactly these settings, and any problem it showed still stands.
    """
    edit = _edit(change)
    if (
        not isinstance(check, Mapping)
        or check.get("unavailable") is not False
        or check.get("requested") != change.requested
    ):
        return replace(edit, refused=_NOT_SHOWN)
    problems = check.get("problems")
    problem = check.get("problem") or next(
        iter(problems.values() if isinstance(problems, Mapping) else ()), None
    )
    if problem:
        return replace(edit, refused=str(problem))
    values = check.get("values")
    values = values if isinstance(values, Mapping) else {}
    return replace(edit, before={path: values.get(path) for path in edit.requested})


def _reader(
    client: GoogleAdsClient, entry: ResolvedContextEntry, changes: Sequence[GoogleAdsCampaignUpdate]
) -> Callable[[Sequence[Edit]], Awaitable[Mapping[str, Mapping[str, Any]]]]:
    campaign_ids = [change.campaign.campaign_id for change in changes]

    async def read(_edits: Sequence[Edit]) -> Mapping[str, Mapping[str, Any]]:
        live = await read_campaign_settings(
            client,
            customer_id=entry.external_id,
            login_customer_id=login_customer_id(entry),
            campaign_ids=campaign_ids,
        )
        return {name: item.values for name, item in live.items()}

    return read


def _name(change: GoogleAdsCampaignUpdate, check: Any) -> str:
    shown_name = check.get("name") if isinstance(check, Mapping) else None
    return str(shown_name or change.campaign.label)


def _pending_detail(
    entry: ResolvedContextEntry,
    changes: Sequence[GoogleAdsCampaignUpdate],
    shown: Mapping[str, Any],
) -> PendingIntegrationOperationDetail:
    """Records which settings change on each campaign; URL values stay out of the audit record."""
    return PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key="campaign:update-settings",
                action="update_settings",
                entity_type="google_ads_campaign",
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
    changes: Sequence[GoogleAdsCampaignUpdate],
    shown: Mapping[str, Any],
    result: EditResult,
) -> dict[str, Any]:
    parents = {dict(parent.identity)["object"]: parent for parent in result.ledger.parents}
    campaigns = []
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
        settings = []
        for setting, requested in change.requested.items():
            before = current.get(setting)
            if skipped:
                read = before
            else:
                read = card_value(setting, after.get(SETTING_PATHS[setting])) if after else None
            settings.append(
                {
                    "setting": setting,
                    "before": before,
                    "requested": requested,
                    "after": read,
                    "outcome": "already_set" if before == requested else outcome,
                }
            )
        campaigns.append(
            {
                "resource_name": name,
                "campaign_id": change.campaign.campaign_id,
                "name": _name(change, check),
                "read_back": skipped or after is not None,
                "settings": settings,
                "error_code": effect.error_code if effect is not None else None,
                "message": effect.message if effect is not None else None,
            }
        )
    return {"account_id": entry.external_id, "campaigns": campaigns}


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Adds each account's facts and, per campaign, its live settings and Google's dry run."""
    request = GoogleAdsUpdateCampaignsRequest.model_validate(args)
    by_account: dict[str, list[GoogleAdsCampaignUpdate]] = defaultdict(list)
    for change in request.changes:
        by_account[change.campaign.customer_id].append(change)
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
    changes: Sequence[GoogleAdsCampaignUpdate],
) -> dict[str, dict[str, Any]]:
    """Reads one account's campaigns and dry runs the changes; an unreadable account is unavailable."""
    try:
        if entry is None:
            raise LookupError("Google Ads account not selected")
        today = account_facts(entry).today()
        client = await google_ads_client_for_principal(
            deps.db, actor=deps.user, workspace=deps.workspace, entry=entry
        )
        live = await read_campaign_settings(
            client,
            customer_id=entry.external_id,
            login_customer_id=login_customer_id(entry),
            campaign_ids=[change.campaign.campaign_id for change in changes],
        )
        problems = {
            change.resource_name: _setting_problems(change, item, today)
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
    changes: Sequence[GoogleAdsCampaignUpdate],
    live: Mapping[str, LiveCampaignSettings],
    problems: Mapping[str, Mapping[CampaignSetting, str]],
) -> dict[str, str]:
    """Returns Google's rejection per campaign, asking only about campaigns with no problem yet."""
    checked = [
        _edit(change)
        for change in changes
        if _campaign_problem(live.get(change.resource_name)) is None
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
    change: GoogleAdsCampaignUpdate,
    live: LiveCampaignSettings | None,
    problems: Mapping[CampaignSetting, str],
    rejected: str | None,
) -> dict[str, Any]:
    """Builds the card's view of one campaign, and the live values approval plans against."""
    requested = change.requested
    return {
        "unavailable": False,
        "name": change.campaign.label if live is None else live.values.get("name"),
        "status": live.status if live else None,
        "channel": live.channel if live else None,
        "current": live.settings() if live else {},
        "requested": requested,
        # What approval plans against, in Google's terms, for the settings that change.
        "values": {
            SETTING_PATHS[setting]: live.values.get(SETTING_PATHS[setting]) for setting in requested
        }
        if live
        else {},
        "problem": _campaign_problem(live) or rejected,
        "problems": dict(problems),
    }


DEFINITION = RuntimeToolDefinition(
    name="google_ads_update_campaigns",
    function=google_ads_update_campaigns,
    description=(
        "Change settings on existing Google Ads campaigns of any type, up to 50 campaigns per "
        "call, in one approval. Each entry names one campaign and only the settings that "
        "change: name; start_date and end_date as YYYY-MM-DD in the account time zone, with "
        'end_date "none" to run with no end date; url_options with final_url_suffix, '
        "tracking_template, and custom_parameters (up to 8 key and value pairs, replacing the "
        "campaign's list), where an empty value clears it; and networks with search_partners "
        "(Search and Shopping campaigns) and display_expansion (Search campaigns), each on or "
        "off. A campaign that has started can't change its start date, and new dates can't be "
        "in the past. Status, budgets, bidding, targeting, and removal aren't supported here. "
        "Each result reports what Google Ads shows after the change."
    ),
    provider="google_ads",
    label="Update Google Ads Campaigns",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=120,
    output_model=GoogleAdsUpdateCampaignsOutput,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    approval_display_args=_approval_display_args,
    approval_input_model=GoogleAdsUpdateCampaignsRequest,
    # An edit changes what Google has to answer, so approval waits for a new check.
    approval_review_fields=("changes",),
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Updating Google Ads Campaigns",
        completed_label="Updated Google Ads Campaigns",
        failed_label="Couldn't Update Google Ads Campaigns",
        approval_title="Change Campaign Settings",
        approval_prompt="The agent wants to change settings on these Google Ads campaigns.",
        approve_label="Approve & Update",
        arg_fields=(
            ToolFieldPresentation(
                key="changes",
                label="Campaign Changes",
                editable=True,
                format="structured",
                entity_kinds=("google_ads_campaign",),
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
