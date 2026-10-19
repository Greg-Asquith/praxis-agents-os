# apps/api/integrations/meta_ads/tools/schedule_budget_increases.py

"""Approval-only tool that raises a Meta daily budget during high-demand periods."""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
from ..money import minor_to_amount
from ..operations.budget_schedules import (
    MetaAdsExistingPeriod,
    MetaAdsPeriodReview,
    MetaAdsPlannedPeriod,
    MetaAdsScheduleObjectType,
    add_periods,
    can_schedule_budgets,
    count_problem,
    local_time,
    read_periods,
    review_periods,
    schedule_problem,
)
from ..operations.list_objects import read_objects_by_id
from ..operations.mutations import MetaAdsMutationLedger
from ..references import MetaAdsAdSetReference, MetaAdsCampaignReference
from ..throttle import ensure_account_available
from .schemas.budget_schedules import (
    MAX_NEW_PERIODS,
    MetaAdsBudgetPeriod,
    MetaAdsBudgetScheduleOutput,
    MetaAdsScheduleBudgetIncreasesRequest,
)
from .schemas.objects import MetaAdsObject
from .utils.ad_preparation import hydrate_references, required_currency
from .utils.bindings import META_ADS_BINDING, META_ADS_WRITE_BINDING, RESULTS_FIELD
from .utils.client import meta_ads_available, meta_ads_client, meta_ads_client_for_principal
from .utils.create_operation import validated
from .utils.mutation_evidence import (
    attach_interrupted_evidence,
    audit_status,
    meta_ads_account_target,
    terminal_operation_detail,
)

_OPERATION = "schedule_budget_increases"
_CHECKS_KEY = "_schedule_checks"
_GROUP_KEYS = {
    "campaign": "campaigns:add-budget-schedules",
    "adset": "ad-sets:add-budget-schedules",
}
_ENTITY_TYPES = {"campaign": "meta_ads_campaign", "adset": "meta_ads_ad_set"}
_NO_CAPABILITY = (
    "Meta doesn't let this ad account schedule budget increases through its API. "
    "Add them in Ads Manager instead."
)
_CHANGED = (
    "The daily budget changed since you approved these increases, so none were added. "
    "Ask the agent to prepare them again."
)
_NOT_SHOWN = (
    "The budget couldn't be checked before approval, so no increases were added. "
    "Ask the agent to prepare them again."
)

type _Reference = MetaAdsCampaignReference | MetaAdsAdSetReference
type _Key = tuple[str, MetaAdsScheduleObjectType, str]


@dataclass
class _Review:
    """The campaign or ad set as it is now, with each requested period checked against it."""

    object_type: MetaAdsScheduleObjectType
    item: MetaAdsObject
    existing: list[MetaAdsExistingPeriod] = field(default_factory=list)
    periods: list[MetaAdsPeriodReview] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def daily_budget(self) -> str | None:
        budget = self.item.budget
        return budget.amount if budget is not None and budget.kind == "daily" else None


@dataclass(frozen=True, slots=True)
class _Prepared:
    review: _Review
    currency: str
    zone: ZoneInfo
    periods: list[MetaAdsPlannedPeriod]


async def meta_ads_schedule_budget_increases(
    ctx: RunContext[RuntimeDeps],
    periods: Annotated[
        list[MetaAdsBudgetPeriod],
        Field(
            min_length=1,
            max_length=MAX_NEW_PERIODS,
            description="High-demand periods to add, each with one increase.",
        ),
    ],
    campaign: Annotated[
        MetaAdsCampaignReference | None,
        Field(description="Campaign that holds a daily campaign budget."),
    ] = None,
    ad_set: Annotated[
        MetaAdsAdSetReference | None,
        Field(description="Ad set that holds its own daily budget."),
    ] = None,
) -> dict[str, Any]:
    request = validated(
        MetaAdsScheduleBudgetIncreasesRequest,
        {"campaign": campaign, "ad_set": ad_set, "periods": periods},
    )
    _require_proposed(proposed_args(ctx), request)
    shown = approved_display_args(ctx).get(_CHECKS_KEY)

    async def operation(entry: ResolvedContextEntry, _selected: Sequence[_Reference]) -> Any:
        client: MetaAdsClient | None = None
        prepared: _Prepared | None = None
        pending: PendingIntegrationOperationDetail | None = None

        async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
            nonlocal client, prepared, pending
            ensure_account_available(entry.external_id, operation=_OPERATION)
            client = await meta_ads_client(ctx, entry)
            prepared = await _prepare(client, entry, request, shown)
            pending = _pending_detail(entry, prepared)
            return pending

        async def execute() -> IntegrationAuditOutcome[dict[str, Any]]:
            if client is None or prepared is None or pending is None:
                raise RuntimeError("Meta Ads budget schedule preparation did not complete")
            try:
                ledger = await add_periods(
                    client,
                    account_id=entry.external_id,
                    object_id=prepared.review.item.id,
                    periods=prepared.periods,
                )
            except asyncio.CancelledError as exc:
                attach_interrupted_evidence(
                    exc, pending, identity_key="period", refs_mean_changed=True
                )
                raise
            detail = terminal_operation_detail(pending, ledger, identity_key="period")
            result = _result(entry, prepared, ledger)
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
            tool_name="meta_ads_schedule_budget_increases",
            operation=_OPERATION,
            execute=execute,
            prepare_pending_operation=prepare_pending_operation,
        )

    results = await run_context_targets(
        ctx, binding=META_ADS_WRITE_BINDING, references=[request.reference], operation=operation
    )
    return {"results": serialize_fan_out_results(results)}


def _key(reference: _Reference) -> _Key:
    return reference.account_id, _object_type(reference), reference.provider_entity_id


def _object_type(reference: _Reference) -> MetaAdsScheduleObjectType:
    return "campaign" if isinstance(reference, MetaAdsCampaignReference) else "adset"


def _require_proposed(
    proposed: Mapping[str, Any], request: MetaAdsScheduleBudgetIncreasesRequest
) -> None:
    """The card can change and drop periods, but never add one or change the target."""
    try:
        original = MetaAdsScheduleBudgetIncreasesRequest.model_validate(proposed)
    except ValidationError:
        original = None
    if (
        original is None
        or _key(original.reference) != _key(request.reference)
        or len(request.periods) > len(original.periods)
    ):
        raise ModelRetry(
            "A period or target was added after approval. Ask the agent to prepare it again."
        )


def _zone(entry: ResolvedContextEntry) -> ZoneInfo:
    try:
        return ZoneInfo(metadata_str(entry.permissions_metadata.get("timezone_name")) or "")
    except (ZoneInfoNotFoundError, ValueError):
        raise ModelRetry(
            "This ad account's time zone is unknown. Use Look for New Resources on the "
            "Meta Ads connection, then try again."
        ) from None


async def _review(
    client: MetaAdsClient,
    entry: ResolvedContextEntry,
    request: MetaAdsScheduleBudgetIncreasesRequest,
    *,
    now: datetime,
) -> _Review:
    """Re-reads the target, its periods, and the account capability, then checks each period."""
    reference = request.reference
    object_type = _object_type(reference)
    found = await read_objects_by_id(
        client,
        account_id=entry.external_id,
        object_type=object_type,
        object_ids=[reference.provider_entity_id],
        currency=required_currency(entry),
    )
    item = found.get(reference.provider_entity_id)
    if item is None:
        raise ModelRetry(
            "This campaign or ad set is no longer in this ad account. Choose it again."
        )
    review = _Review(object_type=object_type, item=item)
    if problem := schedule_problem(object_type, item):
        review.problems.append(problem)
        return review
    if not await can_schedule_budgets(client, account_id=entry.external_id):
        review.problems.append(_NO_CAPABILITY)
        return review
    review.existing = await read_periods(client, account_id=entry.external_id, object_id=item.id)
    review.periods = review_periods(
        request.periods,
        review.existing,
        daily_budget=review.daily_budget or "0",
        currency=required_currency(entry),
        zone=_zone(entry),
        now=now,
    )
    if problem := count_problem(len(review.existing), len(request.periods)):
        review.problems.append(problem)
    return review


async def _prepare(
    client: MetaAdsClient,
    entry: ResolvedContextEntry,
    request: MetaAdsScheduleBudgetIncreasesRequest,
    shown: Any,
) -> _Prepared:
    """Checks every period again, refuses a stale budget, and stops if any period breaks a rule."""
    review = await _review(client, entry, request, now=datetime.now(UTC))
    problems = [
        *review.problems,
        *(
            f"Period {number}: {period.problem}"
            for number, period in enumerate(review.periods, start=1)
            if period.problem
        ),
    ]
    if problems:
        raise ModelRetry(
            f"These budget increases can't be added, so nothing was changed. {' '.join(problems)}"
        )
    if not isinstance(shown, Mapping) or shown.get("unavailable") is not False:
        raise ModelRetry(_NOT_SHOWN)
    if shown.get("daily_budget") != review.daily_budget:
        raise ModelRetry(_CHANGED)
    return _Prepared(
        review=review,
        currency=required_currency(entry),
        zone=_zone(entry),
        periods=[period.planned for period in review.periods if period.planned is not None],
    )


def _pending_detail(
    entry: ResolvedContextEntry, prepared: _Prepared
) -> PendingIntegrationOperationDetail:
    review = prepared.review
    items = []
    for period in prepared.periods:
        fields = {
            "period": str(period.number),
            "object_id": review.item.id,
            "object_name": review.item.name,
            "time_start": period.start.isoformat(),
            "time_end": period.end.isoformat(),
            "daily_budget": review.daily_budget,
            "increase_amount": period.increase_amount,
            "increase_percent": str(period.increase_percent) if period.increase_percent else None,
            "currency": prepared.currency,
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
                key=_GROUP_KEYS[review.object_type],
                action="add_budget_schedule",
                entity_type=_ENTITY_TYPES[review.object_type],
                items=items,
            )
        ],
    )


def _result(
    entry: ResolvedContextEntry, prepared: _Prepared, ledger: MetaAdsMutationLedger
) -> dict[str, Any]:
    parents = {dict(parent.identity)["period"]: parent for parent in ledger.parents}
    periods = []
    for period in prepared.periods:
        effect = parents[str(period.number)].effects[0]
        periods.append(
            {
                "id": dict(effect.fields).get("period_id") if effect.outcome == "applied" else None,
                "start": local_time(period.start, prepared.zone),
                "end": local_time(period.end, prepared.zone),
                "increase_amount": period.increase_amount,
                "increase_percent": period.increase_percent,
                "outcome": "added" if effect.outcome == "applied" else effect.outcome,
                "error_code": effect.error_code,
                "message": effect.message,
            }
        )
    review = prepared.review
    return {
        "account_id": entry.external_id,
        "currency": prepared.currency,
        "time_zone": prepared.zone.key,
        "object_type": review.object_type,
        "object_id": review.item.id,
        "object_name": review.item.name,
        "daily_budget": review.daily_budget,
        "periods": periods,
    }


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Hydrates the target and adds its daily budget, current periods, and each period's problem."""
    request = MetaAdsScheduleBudgetIncreasesRequest.model_validate(args)
    key = "campaign" if request.campaign is not None else "ad_set"
    [reference] = await hydrate_references(
        deps, _ENTITY_TYPES[_object_type(request.reference)], key, [request.reference]
    )
    active_context = deps.active_context
    entry = next(
        (
            entry
            for entry in (
                active_context.compatible_entries(META_ADS_BINDING) if active_context else ()
            )
            if entry.external_id == request.reference.account_id
        ),
        None,
    )
    return {**args, key: reference, _CHECKS_KEY: await _checks(deps, entry, request)}


async def _checks(
    deps: RuntimeDeps,
    entry: ResolvedContextEntry | None,
    request: MetaAdsScheduleBudgetIncreasesRequest,
) -> dict[str, Any]:
    """Returns what the card needs to judge each period, or marks the target unavailable."""
    now = datetime.now(UTC)
    try:
        if entry is None:
            raise LookupError("ad account not selected")
        client = await meta_ads_client_for_principal(
            deps.db, actor=deps.user, workspace=deps.workspace, entry=entry
        )
        review = await _review(client, entry, request, now=now)
        zone = _zone(entry)
    except (IntegrationError, LookupError, ModelRetry):
        return {"unavailable": True}
    currency = required_currency(entry)
    return {
        "unavailable": False,
        "currency": currency,
        "time_zone": zone.key,
        "now": local_time(now, zone),
        "daily_budget": review.daily_budget,
        "problems": review.problems,
        "existing_count": len(review.existing),
        # Periods still to come or under way, so the card can show and avoid them.
        "existing": [
            {
                "start": local_time(item.start, zone),
                "end": local_time(item.end, zone),
                "value_type": item.value_type,
                "value": str(item.value),
                "increase_amount": format(minor_to_amount(item.value, currency), "f")
                if item.value_type == "ABSOLUTE"
                else None,
            }
            for item in sorted(review.existing, key=lambda item: item.start)
            if item.end > now
        ],
        # Each problem with the period it was found for, so the card knows when an edit makes
        # it stale.
        "periods": [
            {**period.request.model_dump(mode="json"), "problem": period.problem}
            for period in review.periods
        ],
    }


DEFINITION = RuntimeToolDefinition(
    name="meta_ads_schedule_budget_increases",
    function=meta_ads_schedule_budget_increases,
    description=(
        "Raise the daily budget of one Meta campaign or ad set during high-demand periods, such "
        "as a Black Friday weekend, adding up to 10 periods in one approval. Name the campaign "
        "when it holds a daily campaign budget, otherwise the ad set that holds its own daily "
        "budget, from meta_ads_list_objects. Each period has start and end as YYYY-MM-DDTHH:MM "
        "in the ad account's time zone, at least 3 hours apart and in the future, and either "
        "increase_amount in the account currency or increase_percent of today's daily budget. "
        "Meta allows at most 8 times the daily budget during a period, 50 periods per campaign "
        "or ad set, and no overlaps. Lifetime budgets can't take increases. Remove or change an "
        "existing period in Ads Manager. Each result reports the periods Meta shows afterwards. "
        "This tool doesn't recommend periods or amounts."
    ),
    provider="meta_ads",
    label="Schedule Meta Ads Budget Increases",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=120,
    output_model=MetaAdsBudgetScheduleOutput,
    integration_binding=META_ADS_WRITE_BINDING,
    availability_check=meta_ads_available,
    approval_display_args=_approval_display_args,
    # Edited periods are checked whole, and again by the tool before anything is sent.
    approval_input_model=MetaAdsScheduleBudgetIncreasesRequest,
    presentation=ToolPresentation(
        icon="meta_ads",
        running_label="Scheduling Meta Ads Budget Increases",
        completed_label="Scheduled Meta Ads Budget Increases",
        failed_label="Couldn't Schedule Meta Ads Budget Increases",
        approval_title="Schedule Meta Ads Budget Increases",
        approval_prompt="The agent wants to raise this budget during these periods.",
        approve_label="Approve & Schedule",
        arg_fields=(
            ToolFieldPresentation(
                key="periods", label="Budget Increases", editable=True, format="structured"
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
