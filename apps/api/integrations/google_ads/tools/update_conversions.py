# apps/api/integrations/google_ads/tools/update_conversions.py

"""Approval-only tool that changes conversion action settings and which account goals bid."""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Annotated, Any

from pydantic import Field
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
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    PendingIntegrationOperationDetail,
)
from services.integrations.approved_display_args import approved_display_args
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.context.targeted import run_context_scope

from ..client import GoogleAdsClient
from ..operations.conversion_settings import (
    ACTION_PATHS,
    GOAL_PATHS,
    LiveAccountGoal,
    LiveConversionAction,
    api_value,
    card_value,
    list_conversion_actions,
    read_account_goals,
    read_conversions_last_30_days,
)
from ..operations.edits import Edit, EditResult, FieldChange, prepare_edits
from .schemas.conversions import (
    MAX_CONVERSION_UPDATES,
    GoogleAdsAccountGoalUpdate,
    GoogleAdsConversionActionUpdate,
    GoogleAdsUpdateConversionsOutput,
    GoogleAdsUpdateConversionsRequest,
)
from .utils.accounts import NOT_SHOWN, account_facts, approval_accounts, writable_entry
from .utils.bindings import GOOGLE_ADS_WRITE_BINDING, RESULTS_FIELD
from .utils.client import google_ads_available, google_ads_client_for_principal
from .utils.edit_runs import EditPlan, run_approved_edits
from .utils.mutation_evidence import google_ads_account_target
from .utils.requests import validated_request
from .utils.routing import login_customer_id

_OPERATION = "update_conversions"
_OUTCOMES = {"applied": "updated", "failed": "failed", "unverified": "unverified"}

_MISSING = "This conversion action no longer exists in Google Ads."
_REMOVED = "This conversion action has been removed, so its settings can't change."
_OTHER_OWNER = (
    "Google Ads account {owner} owns this conversion action and tracks conversions for this "
    "account, so change it in that account."
)
_NO_GOAL = "This account has no {category} goal from {origin}."
_NOT_SELECTED = (
    "Google Ads account {customer} isn't in the active context or can't be changed here. Ask "
    "the user to choose it again."
)

type _Item = GoogleAdsConversionActionUpdate | GoogleAdsAccountGoalUpdate


@dataclass(frozen=True, slots=True)
class _Live:
    """One account's conversion actions, account goals, and last 30 days of conversions."""

    actions: Mapping[str, LiveConversionAction]
    goals: Mapping[str, LiveAccountGoal]
    # None when Google's report couldn't be read.
    conversions: Mapping[str, float] | None

    def values(self, name: str) -> Mapping[str, Any] | None:
        live = self.actions.get(name) or self.goals.get(name)
        return live.values if live is not None else None

    def goal_conversions(self, goal: LiveAccountGoal) -> float | None:
        """A goal counts the conversions of every live action in its category and origin."""
        if self.conversions is None:
            return None
        return sum(
            self.conversions.get(action.resource_name, 0.0)
            for action in self.actions.values()
            if action.status != "REMOVED"
            and (action.category, action.origin) == (goal.category, goal.origin)
        )


async def _read_live(
    client: GoogleAdsClient, entry: ResolvedContextEntry, *, with_conversions: bool
) -> _Live:
    """Reads every conversion action and account goal; accounts hold a handful of each."""
    customer, login = entry.external_id, login_customer_id(entry)
    actions = await list_conversion_actions(
        client, customer_id=customer, login_customer_id=login, include_removed=True
    )
    goals = await read_account_goals(client, customer_id=customer, login_customer_id=login)
    conversions = None
    if with_conversions:
        # The card shows recent conversions as context, so a failed read leaves them out.
        try:
            conversions = await read_conversions_last_30_days(
                client, customer_id=customer, login_customer_id=login
            )
        except IntegrationError:
            conversions = None
    return _Live({action.resource_name: action for action in actions}, goals, conversions)


def _items(request: GoogleAdsUpdateConversionsRequest) -> list[_Item]:
    return [*request.changes, *request.account_goals]


def _edit(item: _Item) -> FieldChange:
    if isinstance(item, GoogleAdsConversionActionUpdate):
        resource, paths = "conversionAction", ACTION_PATHS
    else:
        resource, paths = "customerConversionGoal", GOAL_PATHS
    return FieldChange(
        resource=resource,
        resource_name=item.resource_name,
        requested={
            paths[setting]: api_value(setting, value) for setting, value in item.requested.items()
        },
    )


def _token(value: str) -> str:
    return value.replace("_", " ").lower()


def _problem(item: _Item, live: _Live, customer_id: str) -> str | None:
    if isinstance(item, GoogleAdsAccountGoalUpdate):
        if item.resource_name in live.goals:
            return None
        return _NO_GOAL.format(category=_token(item.goal.category), origin=_token(item.goal.origin))
    action = live.actions.get(item.resource_name)
    if action is None:
        return _MISSING
    if action.status == "REMOVED":
        return _REMOVED
    if action.owner_customer_id != customer_id:
        return _OTHER_OWNER.format(owner=action.owner_customer_id)
    return None


async def google_ads_update_conversions(
    ctx: RunContext[RuntimeDeps],
    changes: Annotated[
        list[GoogleAdsConversionActionUpdate] | None,
        Field(
            max_length=MAX_CONVERSION_UPDATES,
            description="One entry per conversion action, with only the settings that change.",
        ),
    ] = None,
    account_goals: Annotated[
        list[GoogleAdsAccountGoalUpdate] | None,
        Field(
            max_length=MAX_CONVERSION_UPDATES,
            description="One entry per account goal whose bidding changes.",
        ),
    ] = None,
) -> dict[str, Any]:
    request = validated_request(
        GoogleAdsUpdateConversionsRequest,
        {"changes": changes or [], "account_goals": account_goals or []},
    )
    customer_id = request.customer_id
    if writable_entry(ctx.deps.active_context, customer_id) is None:
        raise ModelRetry(_NOT_SELECTED.format(customer=customer_id))
    display = approved_display_args(ctx).get("_checks")
    shown: Mapping[str, Any] = display if isinstance(display, Mapping) else {}
    items = _items(request)

    async def operation(entry: ResolvedContextEntry) -> Any:
        async def plan(_client: GoogleAdsClient) -> EditPlan:
            edits = [_approved_edit(item, shown.get(item.resource_name)) for item in items]
            return edits, _pending_detail(entry, request, shown)

        async def result(_client: GoogleAdsClient, applied: EditResult) -> dict[str, Any]:
            return _result(entry, items, shown, applied)

        return await run_approved_edits(
            ctx,
            entry,
            tool_name="google_ads_update_conversions",
            operation=_OPERATION,
            family="conversion_settings",
            plan=plan,
            read=lambda client: _reader(client, entry),
            result=result,
        )

    results = await run_context_scope(
        ctx, binding=GOOGLE_ADS_WRITE_BINDING, provider_scope_id=customer_id, operation=operation
    )
    return {"results": serialize_fan_out_results(results)}


def _approved_edit(item: _Item, check: Any) -> FieldChange:
    """Builds the edit against the values the approver saw, so `apply_edits` refuses stale ones."""
    edit = _edit(item)
    if (
        not isinstance(check, Mapping)
        or check.get("unavailable") is not False
        or check.get("requested") != item.requested
    ):
        return replace(edit, refused=NOT_SHOWN)
    if problem := check.get("problem"):
        return replace(edit, refused=str(problem))
    values = check.get("values")
    return replace(edit, before=edit.live(values if isinstance(values, Mapping) else {}) or {})


def _reader(
    client: GoogleAdsClient, entry: ResolvedContextEntry
) -> Callable[[Sequence[Edit]], Awaitable[Mapping[str, Mapping[str, Any]]]]:
    async def read(edits: Sequence[Edit]) -> Mapping[str, Mapping[str, Any]]:
        live = await _read_live(client, entry, with_conversions=False)
        return {edit.key: values for edit in edits if (values := live.values(edit.key))}

    return read


def _text(check: Any, key: str) -> str | None:
    value = check.get(key) if isinstance(check, Mapping) else None
    return str(value) if value else None


def _name(item: _Item, check: Any) -> str:
    if isinstance(item, GoogleAdsAccountGoalUpdate):
        return item.goal.label
    return _text(check, "name") or item.conversion_action.label


def _pending_detail(
    entry: ResolvedContextEntry,
    request: GoogleAdsUpdateConversionsRequest,
    shown: Mapping[str, Any],
) -> PendingIntegrationOperationDetail:
    """Records which settings change on each conversion action and account goal."""
    groups = [
        IntegrationOperationIntentGroup(
            key=key,
            action="update_settings",
            entity_type=entity_type,
            items=[
                IntegrationOperationIntent(
                    fields={
                        "object": item.resource_name,
                        "name": _name(item, shown.get(item.resource_name)),
                        "settings": ",".join(item.requested),
                    }
                )
                for item in items
            ],
        )
        for key, entity_type, items in (
            ("conversion_action:update-settings", "google_ads_conversion_action", request.changes),
            ("account_goal:update-settings", "google_ads_account_goal", request.account_goals),
        )
        if items
    ]
    return PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry), intent_groups=groups
    )


def _card_settings(item: _Item, values: Mapping[str, Any]) -> dict[str, Any]:
    paths = ACTION_PATHS if isinstance(item, GoogleAdsConversionActionUpdate) else GOAL_PATHS
    return {setting: card_value(setting, values.get(path)) for setting, path in paths.items()}


def _result(
    entry: ResolvedContextEntry,
    items: Sequence[_Item],
    shown: Mapping[str, Any],
    result: EditResult,
) -> dict[str, Any]:
    parents = {dict(parent.identity)["object"]: parent for parent in result.ledger.parents}
    outcomes = []
    for item in items:
        name = item.resource_name
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
        after_settings = _card_settings(item, after) if after is not None else {}
        goal = isinstance(item, GoogleAdsAccountGoalUpdate)
        outcomes.append(
            {
                "resource_name": name,
                "kind": "account_goal" if goal else "conversion_action",
                "name": _name(item, check),
                "category": item.goal.category if goal else _text(check, "category"),
                "origin": item.goal.origin if goal else _text(check, "origin"),
                "read_back": skipped or after is not None,
                "settings": [
                    {
                        "setting": setting,
                        "before": current.get(setting),
                        "requested": requested,
                        "after": current.get(setting) if skipped else after_settings.get(setting),
                        "outcome": (
                            "already_set"
                            if setting in current and current[setting] == requested
                            else outcome
                        ),
                    }
                    for setting, requested in item.requested.items()
                ],
                "error_code": effect.error_code if effect is not None else None,
                "message": effect.message if effect is not None else None,
            }
        )
    return {
        "account_id": entry.external_id,
        "currency": account_facts(entry).currency,
        "items": outcomes,
    }


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Adds the account's facts and, per item, its live settings, recent conversions, and Google's dry run."""
    request = GoogleAdsUpdateConversionsRequest.model_validate(args)
    entry = writable_entry(deps.active_context, request.customer_id)
    checks = await _account_checks(deps, entry, _items(request))
    accounts = approval_accounts([entry] if entry is not None else [])
    return {**args, "_accounts": accounts, "_checks": checks}


async def _account_checks(
    deps: RuntimeDeps, entry: ResolvedContextEntry | None, items: Sequence[_Item]
) -> dict[str, dict[str, Any]]:
    """Reads the account and dry runs the changes; an unreadable account is unavailable."""
    try:
        if entry is None:
            raise LookupError("Google Ads account not selected")
        client = await google_ads_client_for_principal(
            deps.db, actor=deps.user, workspace=deps.workspace, entry=entry
        )
        live = await _read_live(client, entry, with_conversions=True)
        problems = {item.resource_name: _problem(item, live, entry.external_id) for item in items}
        rejected = await _dry_run(client, entry, items, live, problems)
    except (IntegrationError, LookupError):
        return {item.resource_name: {"unavailable": True} for item in items}
    return {
        item.resource_name: _check(
            item, live, problems[item.resource_name] or rejected.get(item.resource_name)
        )
        for item in items
    }


async def _dry_run(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    items: Sequence[_Item],
    live: _Live,
    problems: Mapping[str, str | None],
) -> dict[str, str]:
    """Returns Google's rejection per item, asking only about items with no problem yet."""
    checked = [_edit(item) for item in items if problems[item.resource_name] is None]
    if not checked:
        return {}

    async def read(edits: Sequence[Edit]) -> Mapping[str, Mapping[str, Any]]:
        return {edit.key: values for edit in edits if (values := live.values(edit.key))}

    prepared = await prepare_edits(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        edits=checked,
        read=read,
        operation=_OPERATION,
    )
    return {edit.key: f"Google says: {edit.refused}" for edit in prepared if edit.refused}


def _check(item: _Item, live: _Live, problem: str | None) -> dict[str, Any]:
    """Builds the card's view of one item, and the live values approval plans against."""
    values = live.values(item.resource_name)
    base = {
        "unavailable": False,
        "requested": item.requested,
        "current": _card_settings(item, values) if values is not None else {},
        # What approval plans against, in Google's terms.
        "values": (_edit(item).live(values) or {}) if values is not None else {},
        "problem": problem,
    }
    if isinstance(item, GoogleAdsAccountGoalUpdate):
        goal = live.goals.get(item.resource_name)
        return {**base, "conversions": live.goal_conversions(goal) if goal else None}
    action = live.actions.get(item.resource_name)
    if action is None:
        return {**base, "name": item.conversion_action.label, "conversions": None}
    return {
        **base,
        "name": action.name,
        "type": action.action_type,
        "category": action.category,
        "origin": action.origin,
        "status": action.status,
        "conversions": (
            live.conversions.get(action.resource_name, 0.0)
            if live.conversions is not None
            else None
        ),
    }


DEFINITION = RuntimeToolDefinition(
    name="google_ads_update_conversions",
    function=google_ads_update_conversions,
    description=(
        "Change settings on existing Google Ads conversion actions, and which account goals "
        "count for bidding, in one Google Ads account per call and one approval. Each "
        "`changes` entry names one conversion action (a google_ads_conversion_action "
        "reference) and only the settings that change: status, ENABLED or HIDDEN; primary, "
        "true to make it a primary action that counts in Conversions and bidding, false for "
        "secondary, which only counts in All Conversions; default_value as a decimal string "
        "(zero allowed) with an optional currency code; always_use_default_value; counting, "
        "ONE_PER_CLICK or MANY_PER_CLICK; click_through_days (1 to 90) and view_through_days "
        "(1 to 30). Each `account_goals` entry names one account goal (a "
        "google_ads_conversion_goal reference: a conversion category from one origin, such as "
        "purchases from the website) with biddable true when it should count towards bidding "
        "account-wide and false when it shouldn't. Every entry must be in the same account. "
        "Changing primary actions, values, or bidding goals "
        "changes what Smart Bidding optimises for. This changes existing actions only: it "
        "doesn't create or remove them, set up tags, or change campaign goals. Each result "
        "reports what Google Ads shows after the change."
    ),
    provider="google_ads",
    label="Update Google Ads Conversions",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=120,
    output_model=GoogleAdsUpdateConversionsOutput,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    approval_display_args=_approval_display_args,
    approval_input_model=GoogleAdsUpdateConversionsRequest,
    # An edit changes what Google has to answer, so approval waits for a new check.
    approval_review_fields=("changes", "account_goals"),
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Updating Google Ads Conversions",
        completed_label="Updated Google Ads Conversions",
        failed_label="Couldn't Update Google Ads Conversions",
        approval_title="Change Conversion Settings",
        approval_prompt="The agent wants to change how these Google Ads conversions count.",
        approve_label="Approve & Update",
        arg_fields=(
            ToolFieldPresentation(
                key="changes",
                label="Conversion Action Changes",
                editable=True,
                format="structured",
                entity_kinds=("google_ads_conversion_action",),
            ),
            ToolFieldPresentation(
                key="account_goals",
                label="Account Goal Changes",
                editable=True,
                format="structured",
                entity_kinds=("google_ads_conversion_goal",),
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
