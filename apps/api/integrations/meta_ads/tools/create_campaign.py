# apps/api/integrations/meta_ads/tools/create_campaign.py

"""Approval-only tool that creates one paused campaign in a selected ad account."""

import asyncio
from collections.abc import Mapping
from typing import Annotated, Any

from pydantic import Field, ValidationError
from pydantic_ai import ModelRetry, RunContext

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
from services.integrations.context.targeted import run_context_scope
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)
from utils.metadata import metadata_str

from ..client import MetaAdsClient
from ..entity_resolvers.campaign import campaign_reference
from ..operations.ad_rows import ad_effect
from ..operations.create_campaign import (
    CAMPAIGN_GROUP,
    OPERATION,
    CampaignPlan,
    CampaignRun,
    account_problems,
    create_campaign,
    plan_campaign,
    read_campaign_account,
    readback_message,
)
from ..operations.create_objects import validate_create
from ..operations.list_objects import list_objects
from ..throttle import ensure_account_available
from .schemas.budgets import MetaAdsBidStrategy, MetaAdsBudgetAmount
from .schemas.campaigns import (
    MetaAdsCampaignBudget,
    MetaAdsCreateCampaignOutput,
    MetaAdsCreateCampaignRequest,
    MetaAdsObjective,
    MetaAdsSpecialAdCategory,
)
from .schemas.objects import OBJECT_STATUSES
from .utils.bindings import META_ADS_WRITE_BINDING, RESULTS_FIELD
from .utils.client import meta_ads_available, meta_ads_client, meta_ads_client_for_principal
from .utils.mutation_evidence import (
    account_pin,
    attach_interrupted_evidence,
    audit_status,
    meta_ads_account_target,
    terminal_operation_detail,
)
from .utils.schedule import account_schedule
from .utils.validation import validation_retry

_ACCOUNT_CHANGED = "The approved ad account is no longer selected. Ask for approval again."
_FIXED_CHANGED = (
    "The objective, budget type, bid strategy, or special ad categories changed after "
    "approval. Ask the agent to prepare the campaign again."
)
_UNDELETED_CAMPAIGN_STATUSES = [s for s in OBJECT_STATUSES["campaign"] if s != "DELETED"]


async def meta_ads_create_campaign(
    ctx: RunContext[RuntimeDeps],
    name: Annotated[str, Field(description="Campaign name, up to 400 characters.")],
    objective: Annotated[MetaAdsObjective, Field(description="What the campaign is for.")],
    budget: Annotated[
        MetaAdsCampaignBudget,
        Field(description="Who holds the budget: the campaign, daily or lifetime, or ad sets."),
    ],
    bid_strategy: Annotated[
        MetaAdsBidStrategy, Field(description="How Meta bids; highest_volume unless asked.")
    ] = "highest_volume",
    special_ad_categories: Annotated[
        list[MetaAdsSpecialAdCategory] | None,
        Field(description="Declared by the operator, never guessed; omit when none apply."),
    ] = None,
    start_date: Annotated[
        str | None, Field(description="YYYY-MM-DD in the account's time zone.")
    ] = None,
    end_date: Annotated[str | None, Field(description="YYYY-MM-DD in the account's time zone.")] = (
        None
    ),
    spend_limit: Annotated[
        MetaAdsBudgetAmount | None,
        Field(description="Most the campaign can ever spend, in the account currency."),
    ] = None,
) -> dict[str, Any]:
    request = _request(_given({key: value for key, value in locals().items() if key != "ctx"}))
    entry = _account_entry(ctx.deps)
    reviewed = approved_display_args(ctx)

    async def operation(selected: ResolvedContextEntry) -> Any:
        client: MetaAdsClient | None = None
        plan: CampaignPlan | None = None
        currency = ""
        pending_detail: PendingIntegrationOperationDetail | None = None

        async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
            nonlocal client, plan, currency, pending_detail
            if reviewed.get("_account") != account_pin(selected):
                raise ModelRetry(_ACCOUNT_CHANGED)
            if _fixed(proposed_args(ctx)) != _fixed(request):
                raise ModelRetry(_FIXED_CHANGED)
            ensure_account_available(selected.external_id, operation=OPERATION)
            client = await meta_ads_client(ctx, selected)
            plan, currency = await _prepare(client, selected, request)
            pending_detail = PendingIntegrationOperationDetail(
                target=meta_ads_account_target(selected),
                intent_groups=[
                    IntegrationOperationIntentGroup(
                        key=CAMPAIGN_GROUP,
                        action="create_campaign",
                        entity_type="meta_ads_campaign",
                        items=[IntegrationOperationIntent(fields=plan.intent_fields)],
                    )
                ],
            )
            return pending_detail

        async def execute() -> IntegrationAuditOutcome[dict[str, Any]]:
            if client is None or plan is None or pending_detail is None:
                raise RuntimeError("Meta Ads campaign preparation did not complete")
            try:
                run = await create_campaign(
                    client, account_id=selected.external_id, currency=currency, plan=plan
                )
            except (asyncio.CancelledError, Exception) as exc:
                attach_interrupted_evidence(
                    exc, pending_detail, identity_key="key", refs_mean_changed=True
                )
                raise
            ledger = run.ledger()
            detail = terminal_operation_detail(pending_detail, ledger, identity_key="key")
            result = {
                "account_id": selected.external_id,
                "currency": currency,
                "campaign": _row(run, request, selected, currency),
            }
            outcome_status = audit_status(detail)
            return IntegrationAuditOutcome(
                result,
                status=outcome_status,
                external_ref=",".join(ledger.external_refs)[:1000] or None,
                operation_detail=detail,
                unverified_result=result if outcome_status is AuditStatus.UNVERIFIED else None,
            )

        return await run_audited_integration_operation(
            ctx,
            selected,
            tool_name="meta_ads_create_campaign",
            operation=OPERATION,
            execute=execute,
            prepare_pending_operation=prepare_pending_operation,
        )

    results = await run_context_scope(
        ctx,
        binding=META_ADS_WRITE_BINDING,
        provider_scope_id=entry.external_id,
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


def _request(values: Mapping[str, Any]) -> MetaAdsCreateCampaignRequest:
    try:
        return MetaAdsCreateCampaignRequest.model_validate(values)
    except ValidationError as exc:
        raise validation_retry(exc) from None


def _account_entry(deps: RuntimeDeps) -> ResolvedContextEntry:
    active = deps.active_context
    entries = active.compatible_entries(META_ADS_WRITE_BINDING) if active else ()
    writable = [entry for entry in entries if entry.write_allowed]
    candidates = writable or (list(entries) if len(entries) == 1 else [])
    if len(candidates) != 1:
        raise ModelRetry(
            "A campaign goes in one ad account. Ask the user to select exactly one writable "
            "Meta ad account in Active Context."
        )
    return candidates[0]


def _fixed(values: Mapping[str, Any] | MetaAdsCreateCampaignRequest) -> list[Any] | None:
    """Reads the settings the card can't change, because later steps depend on them."""
    if not isinstance(values, MetaAdsCreateCampaignRequest):
        try:
            values = MetaAdsCreateCampaignRequest.model_validate(_given(values))
        except ValidationError:
            return None
    return [
        values.objective,
        values.budget.mode,
        values.budget.share_between_ad_sets,
        values.bid_strategy,
        values.special_ad_categories,
    ]


def _given(values: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


async def _prepare(
    client: MetaAdsClient, entry: ResolvedContextEntry, request: MetaAdsCreateCampaignRequest
) -> tuple[CampaignPlan, str]:
    """Re-reads the account, checks its status and minimums, then has Meta dry-run the body."""
    account = await read_campaign_account(client, account_id=entry.external_id)
    schedule = account_schedule(request.start_date, request.end_date, account.timezone_name)
    if problems := account_problems(request, account, schedule.days):
        raise ModelRetry(" ".join(problems))
    await _check_name(client, entry, request, account.currency)
    plan = plan_campaign(
        request,
        currency=account.currency,
        start_time=schedule.start_time,
        end_time=schedule.end_time,
    )
    if reason := await validate_create(
        client,
        account_id=entry.external_id,
        edge="campaigns",
        data=plan.body,
        operation=OPERATION,
    ):
        raise ModelRetry(f"Meta Ads rejected this campaign, so nothing was created. {reason}")
    return plan, account.currency


async def _check_name(
    client: MetaAdsClient,
    entry: ResolvedContextEntry,
    request: MetaAdsCreateCampaignRequest,
    currency: str,
) -> None:
    """A lost reply is found by name, so the name must be free in the ad account."""
    existing = await list_objects(
        client,
        account_id=entry.external_id,
        object_type="campaign",
        statuses=_UNDELETED_CAMPAIGN_STATUSES,
        name_contains=request.name,
        limit=50,
        currency=currency,
    )
    if any(item.name == request.name for item in existing.objects):
        raise ModelRetry(
            f"A campaign called {request.name} is already in this ad account. Choose another name."
        )


def _row(
    run: CampaignRun,
    request: MetaAdsCreateCampaignRequest,
    entry: ResolvedContextEntry,
    currency: str,
) -> dict[str, Any]:
    effect = ad_effect(run)
    observed = dict(effect.fields)
    created = run.created
    reference = campaign_reference(entry, created, currency) if created is not None else None
    return {
        "name": created.name if created is not None and created.name else request.name,
        "objective": request.objective,
        "outcome": {"applied": "created"}.get(effect.outcome, effect.outcome),
        "recovered": observed.get("recovered") == "true",
        "verified": effect.outcome == "applied" and created is not None,
        "campaign_id": effect.external_ref,
        "effective_status": observed.get("effective_status"),
        "campaign": reference.model_dump(mode="json") if reference is not None else None,
        "error_code": effect.error_code,
        "message": readback_message(run),
    }


async def _validate_args(ctx: RunContext[RuntimeDeps], **values: Any) -> None:
    """Checks the rules that hold whatever the account says; preparation checks it live."""
    request = _request(_given(values))
    entry = _account_entry(ctx.deps)
    if request.start_date or request.end_date:
        account_schedule(
            request.start_date,
            request.end_date,
            metadata_str(entry.permissions_metadata.get("timezone_name")),
        )


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Reads the account's currency, time zone, and minimums, so the card shows them."""
    entry = _account_entry(deps)
    client = await meta_ads_client_for_principal(
        deps.db, actor=deps.user, workspace=deps.workspace, entry=entry
    )
    account = await read_campaign_account(client, account_id=entry.external_id)
    return {
        **args,
        "_account": account_pin(entry),
        "_account_name": entry.display_name[:500],
        "_currency": account.currency,
        "_timezone": account.timezone_name,
        "_minimum": account.minimum,
        "_minimum_spend_limit": account.minimum_spend_limit,
    }


DEFINITION = RuntimeToolDefinition(
    name="meta_ads_create_campaign",
    function=meta_ads_create_campaign,
    description=(
        "Create one campaign, paused, in the one writable Meta ad account selected in Active "
        "Context, in one approval. This is "
        "the first step of a new campaign: then create each ad set in it with "
        "meta_ads_create_ad_set, create ads with meta_ads_create_ads, and turn it on with "
        "meta_ads_update_status. Propose it in plain words first, for example 'a sales "
        "campaign at £150 a day, highest volume bidding, starting when you turn it on'. "
        "budget.mode is campaign_daily unless the operator asks otherwise: campaign_daily and "
        "campaign_lifetime take an amount (lifetime needs end_date); ad_set leaves the amount to "
        "each ad set and needs share_between_ad_sets. Use bid_strategy highest_volume unless "
        "the operator asks for a cost per result goal, bid cap, or return on ad spend goal; "
        "each ad set then needs a bid amount or minimum return, and roas_goal needs a sales "
        "campaign with a campaign budget and can't be changed later. If the product could be "
        "housing, employment, credit or other financial services, or gambling, ask the "
        "operator whether it's a special ad category and in which countries; never guess. "
        "Political and social issue campaigns aren't supported."
    ),
    provider="meta_ads",
    label="Create Meta Campaign",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=120,
    args_validator=_validate_args,
    output_model=MetaAdsCreateCampaignOutput,
    integration_binding=META_ADS_WRITE_BINDING,
    availability_check=meta_ads_available,
    approval_display_args=_approval_display_args,
    # Nested edits are checked whole, and again by the tool before anything is sent.
    approval_input_model=MetaAdsCreateCampaignRequest,
    presentation=ToolPresentation(
        icon="meta_ads",
        running_label="Creating Meta Campaign",
        completed_label="Created Meta Campaign",
        failed_label="Couldn't Create Meta Campaign",
        approval_title="Create Meta Campaign",
        approval_prompt="The agent wants to create this campaign in {_account_name}.",
        approve_label="Approve & Create",
        arg_fields=(
            ToolFieldPresentation(key="name", label="Name", editable=True),
            ToolFieldPresentation(key="budget", label="Budget", editable=True, format="structured"),
            ToolFieldPresentation(key="start_date", label="Start Date", editable=True),
            ToolFieldPresentation(key="end_date", label="End Date", editable=True),
            ToolFieldPresentation(
                key="spend_limit", label="Spending Limit", editable=True, secondary=True
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
