# apps/api/integrations/meta_ads/tools/create_campaign.py

"""Approval-only tool that creates one campaign in a selected ad account."""

from typing import Annotated, Any

from pydantic import Field
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
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    PendingIntegrationOperationDetail,
)
from services.integrations.context.domain import ResolvedContextEntry
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
)
from ..operations.create_objects import validate_create
from ..operations.object_run import readback_message
from .schemas.budgets import BID_STRATEGIES, MetaAdsBidStrategy, MetaAdsBudgetAmount
from .schemas.campaigns import (
    OBJECTIVES,
    MetaAdsCampaignBudget,
    MetaAdsCreateCampaignOutput,
    MetaAdsCreateCampaignRequest,
    MetaAdsNewObjectStatus,
    MetaAdsObjective,
    MetaAdsSpecialAdCategory,
)
from .utils.bindings import META_ADS_WRITE_BINDING, RESULTS_FIELD
from .utils.client import meta_ads_available, meta_ads_client_for_principal
from .utils.create_operation import ensure_name_free, given, run_create_tool, validated
from .utils.mutation_evidence import (
    account_pin,
    meta_ads_account_target,
)
from .utils.schedule import account_schedule


async def meta_ads_create_campaign(
    ctx: RunContext[RuntimeDeps],
    name: Annotated[str, Field(description="Campaign name, up to 400 characters.")],
    objective: Annotated[MetaAdsObjective, Field(description="What the campaign is for.")],
    budget: Annotated[
        MetaAdsCampaignBudget,
        Field(description="Who holds the budget: the campaign, daily or lifetime, or ad sets."),
    ],
    status: Annotated[
        MetaAdsNewObjectStatus,
        Field(description="paused unless the operator asks for the campaign to be active."),
    ] = "paused",
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
    request = validated(
        MetaAdsCreateCampaignRequest,
        given({key: value for key, value in locals().items() if key != "ctx"}),
    )
    return await run_create_tool(
        ctx,
        _account_entry(ctx.deps),
        tool_name="meta_ads_create_campaign",
        operation=OPERATION,
        prepare=lambda client, entry: _prepare(client, entry, request),
        pending_detail=lambda entry, prepared: _pending_detail(entry, prepared[0]),
        run=lambda client, entry, prepared: create_campaign(
            client, account_id=entry.external_id, currency=prepared[1], plan=prepared[0]
        ),
        result=lambda run, entry, prepared: {
            "account_id": entry.external_id,
            "currency": prepared[1],
            "campaign": _row(run, request, entry, prepared[1]),
        },
    )


def _pending_detail(
    entry: ResolvedContextEntry, plan: CampaignPlan
) -> PendingIntegrationOperationDetail:
    return PendingIntegrationOperationDetail(
        target=meta_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key=CAMPAIGN_GROUP,
                action="create_campaign",
                entity_type="meta_ads_campaign",
                items=[IntegrationOperationIntent(fields=plan.intent_fields)],
            )
        ],
    )


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


async def _prepare(
    client: MetaAdsClient, entry: ResolvedContextEntry, request: MetaAdsCreateCampaignRequest
) -> tuple[CampaignPlan, str]:
    """Re-reads the account, checks its status and minimums, then has Meta dry-run the body."""
    account = await read_campaign_account(client, account_id=entry.external_id)
    schedule = account_schedule(request.start_date, request.end_date, account.timezone_name)
    if problems := account_problems(request, account, schedule.days):
        raise ModelRetry(" ".join(problems))
    await ensure_name_free(
        client,
        entry,
        object_type="campaign",
        name=request.name,
        currency=account.currency,
        taken=f"A campaign called {request.name} is already in this ad account.",
    )
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
    request = validated(MetaAdsCreateCampaignRequest, given(values))
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
        "Create one campaign in the one writable Meta ad account selected in Active "
        "Context, in one approval. It is created paused unless status is active; use active "
        "only when the operator asks for it to run as soon as it exists, and say so. The "
        "operator can change any setting on the approval card, and every rule is checked "
        "again against the edited campaign. This is "
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
            ToolFieldPresentation(
                key="status",
                label="Status",
                editable=True,
                options=("paused", "active"),
            ),
            ToolFieldPresentation(
                key="objective", label="Objective", editable=True, options=tuple(OBJECTIVES)
            ),
            ToolFieldPresentation(key="budget", label="Budget", editable=True, format="structured"),
            ToolFieldPresentation(
                key="bid_strategy",
                label="Bid Strategy",
                editable=True,
                options=tuple(BID_STRATEGIES),
            ),
            ToolFieldPresentation(
                key="special_ad_categories",
                label="Special Ad Categories",
                editable=True,
                format="structured",
            ),
            ToolFieldPresentation(key="start_date", label="Start Date", editable=True),
            ToolFieldPresentation(key="end_date", label="End Date", editable=True),
            ToolFieldPresentation(
                key="spend_limit", label="Spending Limit", editable=True, secondary=True
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
