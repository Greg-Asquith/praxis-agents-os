# apps/api/integrations/meta_ads/tools/create_ad_set.py

"""Approval-only tool that creates one ad set in an existing campaign."""

from collections.abc import Mapping
from typing import Annotated, Any, Literal, get_args

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
from services.integrations.report_results import ReportResultBudget
from utils.metadata import metadata_str

from ..client import MetaAdsClient
from ..entity_resolvers.ad_set import ad_set_reference
from ..entity_resolvers.utils import asset_read_args
from ..goals import GOAL_KEYS, MetaAdsConversionEvent, MetaAdsGoal
from ..models import MetaAdsId
from ..operations.ad_rows import ad_effect
from ..operations.create_ad_set import (
    AD_SET_GROUP,
    OPERATION,
    AdSetPlan,
    AdSetRun,
    campaign_problems,
    create_ad_set,
    eu_transparency,
    minimum_problem,
    plan_ad_set,
    reaches_eu,
    read_ad_set_account,
    store_url,
)
from ..operations.create_objects import validate_create
from ..operations.list_assets import (
    read_application_references,
    read_audience_references,
    read_page_references,
    read_pixel_references,
)
from ..operations.list_custom_conversions import list_custom_conversions
from ..operations.list_objects import read_objects_by_id
from ..operations.object_run import readback_message
from ..operations.targeting import MetaAdsTargeting
from ..references import (
    MetaAdsApplicationReference,
    MetaAdsCampaignReference,
    MetaAdsPageReference,
    MetaAdsPixelReference,
)
from .schemas.ad_sets import (
    MetaAdsAdSetBudget,
    MetaAdsAdSetPlacements,
    MetaAdsCreateAdSetOutput,
    MetaAdsCreateAdSetRequest,
)
from .schemas.budgets import BID_STRATEGIES, MetaAdsBidStrategy, MetaAdsBudgetAmount
from .schemas.campaigns import MetaAdsNewObjectStatus
from .schemas.conversions import CUSTOM_CONVERSIONS_MAX_ROWS, MetaAdsConversion
from .utils.ad_preparation import hydrate_references, required_currency
from .utils.bindings import META_ADS_WRITE_BINDING, RESULTS_FIELD
from .utils.client import meta_ads_available, meta_ads_client_for_principal
from .utils.create_operation import (
    ensure_name_free,
    given,
    run_create_tool,
    selected_account,
    validated,
)
from .utils.mutation_evidence import (
    account_pin,
    meta_ads_account_target,
)
from .utils.schedule import account_schedule

_CAMPAIGN_CHANGED = (
    "The campaign changed after approval. Ask the agent to prepare the ad set again."
)

type Amount = Annotated[MetaAdsBudgetAmount | None, Field(description="In the account currency.")]


async def meta_ads_create_ad_set(
    ctx: RunContext[RuntimeDeps],
    campaign: Annotated[
        MetaAdsCampaignReference, Field(description="Existing campaign the ad set goes in.")
    ],
    name: Annotated[str, Field(description="Ad set name, up to 400 characters.")],
    goal: Annotated[MetaAdsGoal, Field(description="What the ad set optimises for.")],
    targeting: Annotated[MetaAdsTargeting, Field(description="Who the ad set reaches.")],
    status: Annotated[
        MetaAdsNewObjectStatus,
        Field(description="paused unless the operator asks for the ad set to be active."),
    ] = "paused",
    page: Annotated[
        MetaAdsPageReference | None, Field(description="Page for awareness and Page likes goals.")
    ] = None,
    pixel: Annotated[
        MetaAdsPixelReference | None,
        Field(description="Pixel that measures website conversions."),
    ] = None,
    conversion_event: Annotated[
        MetaAdsConversionEvent | None,
        Field(description="Pixel event to optimise for, such as PURCHASE."),
    ] = None,
    custom_conversion_id: Annotated[
        MetaAdsId | None,
        Field(description="Custom conversion from meta_ads_list_conversions, instead of an event."),
    ] = None,
    app: Annotated[
        MetaAdsApplicationReference | None, Field(description="App for app installs.")
    ] = None,
    app_store: Annotated[
        Literal["google_play", "app_store"] | None, Field(description="For app installs.")
    ] = None,
    placements: Annotated[
        MetaAdsAdSetPlacements | None,
        Field(description="Omit for automatic placements, which usually cost less."),
    ] = None,
    budget: Annotated[
        MetaAdsAdSetBudget | None,
        Field(description="Only when the campaign has no budget of its own."),
    ] = None,
    bid_strategy: Annotated[
        MetaAdsBidStrategy | None,
        Field(description="Only when the campaign sets no strategy; defaults to highest_volume."),
    ] = None,
    bid_amount: Amount = None,
    min_roas: Annotated[
        str | None, Field(description="Minimum return on ad spend, such as 2.5, for roas_goal.")
    ] = None,
    min_daily_spend: Amount = None,
    max_daily_spend: Amount = None,
    pay_per_click: Annotated[
        bool, Field(description="link_clicks only: pay per link click, not per impression.")
    ] = False,
    start_date: Annotated[
        str | None, Field(description="YYYY-MM-DD in the account's time zone.")
    ] = None,
    end_date: Annotated[str | None, Field(description="YYYY-MM-DD in the account's time zone.")] = (
        None
    ),
    eu_payer: Annotated[
        str | None, Field(description="Who pays for ads shown in the EU, from the operator.")
    ] = None,
    eu_beneficiary: Annotated[
        str | None, Field(description="Who ads shown in the EU benefit, from the operator.")
    ] = None,
) -> dict[str, Any]:
    request = validated(
        MetaAdsCreateAdSetRequest,
        given({key: value for key, value in locals().items() if key != "ctx"}),
    )
    return await run_create_tool(
        ctx,
        _account_entry(ctx.deps, request.account_id),
        tool_name="meta_ads_create_ad_set",
        operation=OPERATION,
        check_edits=lambda proposed: _check_campaign_kept(proposed, request),
        prepare=lambda client, entry: _prepare(client, entry, request),
        pending_detail=lambda entry, prepared: _pending_detail(entry, prepared[0]),
        run=lambda client, entry, prepared: create_ad_set(
            client, account_id=entry.external_id, currency=prepared[1], plan=prepared[0]
        ),
        result=lambda run, entry, prepared: {
            "account_id": entry.external_id,
            "currency": prepared[1],
            "ad_set": _row(run, request, prepared[0], entry, prepared[1]),
        },
    )


def _pending_detail(
    entry: ResolvedContextEntry, plan: AdSetPlan
) -> PendingIntegrationOperationDetail:
    return PendingIntegrationOperationDetail(
        target=meta_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key=AD_SET_GROUP,
                action="create_ad_set",
                entity_type="meta_ads_ad_set",
                items=[IntegrationOperationIntent(fields=plan.intent_fields)],
            )
        ],
    )


def _account_entry(deps: RuntimeDeps, account_id: str) -> ResolvedContextEntry:
    return selected_account(
        deps,
        account_id,
        "The campaign must belong to one Meta ad account selected in Active Context. Ask "
        "the user to select it.",
    )


def _check_campaign_kept(proposed: Mapping[str, Any], request: MetaAdsCreateAdSetRequest) -> None:
    """The campaign is the one thing the card can't change; everything else is checked live."""
    campaign = proposed.get("campaign")
    if (
        not isinstance(campaign, Mapping)
        or campaign.get("campaign_id") != request.campaign.campaign_id
    ):
        raise ModelRetry(_CAMPAIGN_CHANGED)


async def _prepare(
    client: MetaAdsClient, entry: ResolvedContextEntry, request: MetaAdsCreateAdSetRequest
) -> tuple[AdSetPlan, str]:
    """Re-reads the campaign, account, and assets, checks every rule, then has Meta dry-run it."""
    account_id = entry.external_id
    campaigns = await read_objects_by_id(
        client,
        account_id=account_id,
        object_type="campaign",
        object_ids=[request.campaign.campaign_id],
        currency=required_currency(entry),
    )
    campaign = campaigns.get(request.campaign.campaign_id)
    if campaign is None:
        raise ModelRetry("The campaign is no longer in this ad account. Choose it again.")
    store = await _check_assets(client, entry, request)
    request = await _with_live_audiences(client, entry, request)
    if problems := campaign_problems(request, campaign):
        raise ModelRetry(" ".join(problems))
    account = await read_ad_set_account(client, account_id=account_id, request=request)
    schedule = account_schedule(request.start_date, request.end_date, account.timezone_name)
    if problem := minimum_problem(request, account, schedule.days):
        raise ModelRetry(problem)
    try:
        eu = eu_transparency(request, account)
    except ValueError as exc:
        raise ModelRetry(str(exc)) from None
    await ensure_name_free(
        client,
        entry,
        object_type="adset",
        name=request.name,
        currency=account.currency,
        taken=f"An ad set called {request.name} is already in this campaign.",
        campaign_ids=[request.campaign.campaign_id],
    )
    plan = plan_ad_set(
        request,
        campaign,
        campaign_id=request.campaign.campaign_id,
        currency=account.currency,
        start_time=schedule.start_time,
        end_time=schedule.end_time,
        eu=eu,
        object_store_url=store,
        status=request.status,
    )
    if reason := await validate_create(
        client, account_id=account_id, edge="adsets", data=plan.body, operation=OPERATION
    ):
        raise ModelRetry(f"Meta Ads rejected this ad set, so nothing was created. {reason}")
    return plan, account.currency


async def _check_assets(
    client: MetaAdsClient, entry: ResolvedContextEntry, request: MetaAdsCreateAdSetRequest
) -> str | None:
    """Confirms the account can use the Page, pixel, app, and custom conversion; returns the app's store page."""
    read_args = asset_read_args(entry, ReportResultBudget("meta_ads", OPERATION))
    if request.page is not None:
        pages, _more = await read_page_references(client, **read_args)
        if request.page.page_id not in {page.page_id for page in pages}:
            raise ModelRetry(
                f"This ad account can't advertise as the Page {request.page.label}. Choose one "
                "from meta_ads_list_assets."
            )
    if request.pixel is not None:
        pixels, _more = await read_pixel_references(client, **read_args)
        if request.pixel.pixel_id not in {pixel.pixel_id for pixel in pixels}:
            raise ModelRetry(
                f"This ad account can't use the pixel {request.pixel.label}. Choose one from "
                "meta_ads_list_assets."
            )
    if request.custom_conversion_id is not None:
        conversion = await _custom_conversion(client, entry, request.custom_conversion_id)
        if conversion is None or conversion.is_archived or conversion.is_unavailable:
            raise ModelRetry(
                "That custom conversion isn't usable in this ad account. Choose one from "
                "meta_ads_list_conversions."
            )
        if request.pixel is not None and conversion.pixel_id not in (None, request.pixel.pixel_id):
            raise ModelRetry(
                f"The custom conversion {conversion.name or conversion.id} counts events from "
                "another pixel. Choose that pixel, or a custom conversion on this one."
            )
    if request.app is None or request.app_store is None:
        return None
    apps, _more = await read_application_references(client, **read_args)
    live = next((app for app in apps if app.application_id == request.app.application_id), None)
    if live is None:
        raise ModelRetry(
            f"This ad account can't advertise the app {request.app.label}. Choose one from "
            "meta_ads_list_assets."
        )
    if (url := store_url(live, request.app_store)) is None:
        raise ModelRetry(f"Meta has no {request.app_store} page for {live.label}.")
    return url


async def _custom_conversion(
    client: MetaAdsClient, entry: ResolvedContextEntry, conversion_id: str
) -> MetaAdsConversion | None:
    conversions = await list_custom_conversions(
        client, account_id=entry.external_id, limit=CUSTOM_CONVERSIONS_MAX_ROWS
    )
    return next((item for item in conversions.conversions if item.id == conversion_id), None)


async def _with_live_audiences(
    client: MetaAdsClient, entry: ResolvedContextEntry, request: MetaAdsCreateAdSetRequest
) -> MetaAdsCreateAdSetRequest:
    """Re-reads the audiences, so rules such as no lookalikes use Meta's own subtype."""
    targeting = request.targeting
    ids = sorted(
        {item.audience_id for item in (*targeting.audiences, *targeting.excluded_audiences)}
    )
    if not ids:
        return request
    read_args = asset_read_args(entry, ReportResultBudget("meta_ads", OPERATION))
    found, _more = await read_audience_references(client, **read_args, audience_ids=ids)
    live = {audience.audience_id: audience for audience in found}
    if set(ids) - set(live):
        raise ModelRetry(
            "Some audiences are no longer in this ad account. Choose them again from "
            "meta_ads_list_assets."
        )
    return request.model_copy(
        update={
            "targeting": targeting.model_copy(
                update={
                    "audiences": [live[item.audience_id] for item in targeting.audiences],
                    "excluded_audiences": [
                        live[item.audience_id] for item in targeting.excluded_audiences
                    ],
                }
            )
        }
    )


def _row(
    run: AdSetRun,
    request: MetaAdsCreateAdSetRequest,
    plan: AdSetPlan,
    entry: ResolvedContextEntry,
    currency: str,
) -> dict[str, Any]:
    effect = ad_effect(run)
    observed = dict(effect.fields)
    created = run.created
    reference = ad_set_reference(entry, created, currency) if created is not None else None
    return {
        "name": created.name if created is not None and created.name else request.name,
        "campaign_id": request.campaign.campaign_id,
        "goal": request.goal,
        "outcome": {"applied": "created"}.get(effect.outcome, effect.outcome),
        "recovered": observed.get("recovered") == "true",
        "verified": effect.outcome == "applied" and created is not None,
        "adset_id": effect.external_ref,
        "effective_status": observed.get("effective_status"),
        "ad_set": reference.model_dump(mode="json") if reference is not None else None,
        "eu_transparency": plan.eu,
        "error_code": effect.error_code,
        "message": readback_message(run),
    }


async def _validate_args(ctx: RunContext[RuntimeDeps], **values: Any) -> None:
    """Checks the ad set against the campaign as referenced; preparation checks it live."""
    request = validated(MetaAdsCreateAdSetRequest, given(values))
    entry = _account_entry(ctx.deps, request.account_id)
    if request.campaign.objective is None:
        raise ModelRetry(
            "Use the campaign reference from meta_ads_list_objects, with its objective and budget."
        )
    if problems := campaign_problems(request, request.campaign):
        raise ModelRetry(" ".join(problems))
    if request.start_date or request.end_date:
        account_schedule(
            request.start_date,
            request.end_date,
            metadata_str(entry.permissions_metadata.get("timezone_name")),
        )


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Hydrates the campaign and assets, and reads the account's minimum and EU defaults."""
    request = MetaAdsCreateAdSetRequest.model_validate(given(args))
    entry = _account_entry(deps, request.account_id)
    display: dict[str, Any] = {**args}
    for key, kind in (
        ("campaign", "meta_ads_campaign"),
        ("page", "meta_ads_page"),
        ("pixel", "meta_ads_pixel"),
        ("app", "meta_ads_application"),
    ):
        if (reference := getattr(request, key)) is not None:
            hydrated = await hydrate_references(deps, kind, key, [reference])
            display[key] = hydrated[0] if hydrated else args[key]
    client = await meta_ads_client_for_principal(
        deps.db, actor=deps.user, workspace=deps.workspace, entry=entry
    )
    account = await read_ad_set_account(client, account_id=entry.external_id, request=request)
    if request.custom_conversion_id is not None:
        conversion = await _custom_conversion(client, entry, request.custom_conversion_id)
        # The card names the custom conversion and checks it against the pixel chosen there.
        display["_custom_conversion"] = (
            {"name": conversion.name, "pixel_id": conversion.pixel_id} if conversion else None
        )
    return {
        **display,
        "_account": account_pin(entry),
        "_account_name": entry.display_name[:500],
        "_currency": account.currency,
        "_timezone": account.timezone_name,
        "_minimum": account.minimum,
        # The minimum depends on the goal, so the card checks it only while the goal is unchanged.
        "_minimum_goal": request.goal,
        "_eu": {
            "applies": reaches_eu(request),
            "default_payer": account.dsa_payor,
            "default_beneficiary": account.dsa_beneficiary,
        },
    }


DEFINITION = RuntimeToolDefinition(
    name="meta_ads_create_ad_set",
    function=meta_ads_create_ad_set,
    description=(
        "Create one ad set in an existing campaign of a Meta ad account, in one approval. It is "
        "created paused unless status is active; use active only when the operator asks for it "
        "to run as soon as it exists, and say so. The operator can change every setting but the "
        "campaign on the approval card, and every rule is checked again against the edited ad "
        "set. Build order: find the campaign with meta_ads_list_objects; list the Pages, pixels, "
        "apps, and audiences with meta_ads_list_assets; find places, interests, and languages "
        "with meta_ads_search_targeting and never invent keys; estimate the audience with "
        "meta_ads_estimate_audience and quote Meta's range to the operator; then propose the ad "
        "set in plain words, for example 'UK and Ireland, 25 to 54, interested in running, "
        "automatic placements, optimise for purchases on your pixel, £40 a day'. goal must suit "
        "the campaign's objective: reach, impressions, or ad_recall_lift (awareness, with page); "
        "link_clicks or landing_page_views (traffic); post_engagement, or page_likes with page "
        "(engagement); app_installs with app and app_store (app promotion); website_conversions "
        "with pixel and conversion_event or custom_conversion_id (sales). Set budget only when "
        "the campaign has no budget of its own; a lifetime budget needs end_date. Bids follow "
        "the campaign's strategy: bid_cap and cost_per_result_goal need bid_amount, roas_goal "
        "needs min_roas. Placements are automatic unless the operator asks otherwise. For places "
        "in the EU, Meta needs who pays and who benefits; ask the operator for eu_payer and "
        "eu_beneficiary unless the account has defaults. Housing, employment, and financial "
        "campaigns can't target by age, gender, or postcode. Then create ads in it with "
        "meta_ads_create_ads and turn it on with meta_ads_update_status."
    ),
    provider="meta_ads",
    label="Create Meta Ad Set",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=120,
    args_validator=_validate_args,
    output_model=MetaAdsCreateAdSetOutput,
    integration_binding=META_ADS_WRITE_BINDING,
    availability_check=meta_ads_available,
    approval_display_args=_approval_display_args,
    # Nested edits are checked whole, and again by the tool before anything is sent.
    approval_input_model=MetaAdsCreateAdSetRequest,
    presentation=ToolPresentation(
        icon="meta_ads",
        running_label="Creating Meta Ad Set",
        completed_label="Created Meta Ad Set",
        failed_label="Couldn't Create Meta Ad Set",
        approval_title="Create Meta Ad Set",
        approval_prompt="The agent wants to create this ad set in {_account_name}.",
        approve_label="Approve & Create",
        arg_fields=(
            ToolFieldPresentation(key="name", label="Name", editable=True),
            ToolFieldPresentation(
                key="status", label="Status", editable=True, options=("paused", "active")
            ),
            ToolFieldPresentation(key="goal", label="Goal", editable=True, options=GOAL_KEYS),
            ToolFieldPresentation(
                key="page",
                label="Facebook Page",
                editable=True,
                format="entity",
                entity_kind="meta_ads_page",
                width="half",
            ),
            ToolFieldPresentation(
                key="pixel",
                label="Pixel",
                editable=True,
                format="entity",
                entity_kind="meta_ads_pixel",
                width="half",
            ),
            ToolFieldPresentation(
                key="app",
                label="App",
                editable=True,
                format="entity",
                entity_kind="meta_ads_application",
                width="half",
            ),
            ToolFieldPresentation(
                key="conversion_event",
                label="Conversion Event",
                editable=True,
                options=get_args(MetaAdsConversionEvent.__value__),
                width="half",
            ),
            ToolFieldPresentation(
                key="custom_conversion_id",
                label="Custom Conversion",
                editable=True,
                width="half",
            ),
            ToolFieldPresentation(
                key="app_store",
                label="App Store",
                editable=True,
                options=("google_play", "app_store"),
            ),
            ToolFieldPresentation(key="budget", label="Budget", editable=True, format="structured"),
            ToolFieldPresentation(
                key="placements", label="Placements", editable=True, format="structured"
            ),
            ToolFieldPresentation(
                key="bid_strategy",
                label="Bid Strategy",
                editable=True,
                options=tuple(BID_STRATEGIES),
            ),
            ToolFieldPresentation(key="start_date", label="Start Date", editable=True),
            ToolFieldPresentation(key="end_date", label="End Date", editable=True),
            ToolFieldPresentation(
                key="bid_amount", label="Bid Amount", editable=True, secondary=True
            ),
            ToolFieldPresentation(
                key="targeting",
                label="Targeting",
                editable=True,
                format="structured",
                entity_kinds=(
                    "meta_ads_audience",
                    "meta_ads_targeting_location",
                    "meta_ads_targeting_interest",
                ),
            ),
            ToolFieldPresentation(
                key="min_roas", label="Minimum Return", editable=True, secondary=True
            ),
            ToolFieldPresentation(
                key="min_daily_spend", label="Min Daily Spend", editable=True, secondary=True
            ),
            ToolFieldPresentation(
                key="max_daily_spend", label="Max Daily Spend", editable=True, secondary=True
            ),
            ToolFieldPresentation(
                key="pay_per_click",
                label="Pay Per Click",
                editable=True,
                format="boolean",
                secondary=True,
            ),
            ToolFieldPresentation(
                key="eu_payer", label="EU Payer", editable=True, secondary=True, width="half"
            ),
            ToolFieldPresentation(
                key="eu_beneficiary",
                label="EU Beneficiary",
                editable=True,
                secondary=True,
                width="half",
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
