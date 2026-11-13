# apps/api/integrations/google_ads/tools/create_campaign.py

"""Approval-only tool that builds a complete Search or Performance Max campaign in one request."""

import asyncio
from collections import Counter
from collections.abc import Sequence
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from core.exceptions.integration import (
    IntegrationError,
    IntegrationFailureDisposition,
    IntegrationValidationError,
)
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
from services.integrations.context.targeted import run_context_scope
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..client import GoogleAdsClient
from ..operations.build import BuildResult, BuildStep, CampaignBuild, dry_run_build, send_build
from ..operations.conversion_settings import LiveAccountGoal
from ..operations.performance_max import AssetGroupItem
from ..operations.search_ad_groups import AdGroupItem, add_search_ad_group
from ..operations.search_campaigns import CampaignItem, add_search_campaign, new_campaign_facts
from ..operations.search_targeting import read_locations
from ..references import (
    GoogleAdsAdGroupReference,
    GoogleAdsCampaignReference,
)
from .schemas.ad_groups import MAX_NEW_AD_GROUPS, MAX_RESULT_PROBLEMS, GoogleAdsNewAdGroup
from .schemas.campaigns import (
    GoogleAdsCreateCampaignOutput,
    GoogleAdsCreateCampaignRequest,
    GoogleAdsNewCampaign,
    GoogleAdsNewPerformanceMaxCampaign,
    GoogleAdsNewSearchCampaign,
    NewCampaign,
)
from .schemas.performance_max import MAX_NEW_ASSET_GROUPS, GoogleAdsNewAssetGroup
from .utils.accounts import account_facts, approval_accounts, sole_writable_entry
from .utils.ad_group_builds import (
    MAX_AUDIT_ITEM_CHARS,
    STRATEGY_NAMES,
    ad_group_item_fields,
    ad_group_problems,
)
from .utils.bindings import GOOGLE_ADS_WRITE_BINDING, RESULTS_FIELD
from .utils.client import google_ads_available, google_ads_client, google_ads_client_for_principal
from .utils.mutation_evidence import (
    attach_interrupted_evidence,
    audit_status,
    google_ads_account_target,
    terminal_operation_detail,
)
from .utils.performance_max_builds import (
    account_problems,
    compile_performance_max,
    created_asset_groups,
    performance_max_checks,
    performance_max_problems,
    read_account_facts,
)
from .utils.requests import validated_request
from .utils.routing import login_customer_id

_OPERATION = "create_campaign"
_IDENTITY = ("step",)
_KINDS = (
    "budget",
    "campaign",
    "location",
    "excluded_location",
    "ad_group",
    "keyword",
    "negative_keyword",
    "ad",
    "asset",
    "language",
    "conversion_goal",
    "text_asset",
    "brand_link",
    "asset_group",
    "listing_filter",
    "asset_group_link",
    "search_theme",
    "audience_signal",
)
_ONE_ACCOUNT = (
    "A campaign goes in one account. Ask the user to select exactly one Google Ads account "
    "with permission to make changes in Active Context."
)
_ACCOUNT_CHANGED = "The approved Google Ads account is no longer selected. Ask for approval again."

type _Source = CampaignItem | AdGroupItem | AssetGroupItem


async def google_ads_create_campaign(
    ctx: RunContext[RuntimeDeps],
    campaign: Annotated[
        GoogleAdsNewCampaign,
        Field(description="The campaign's type and settings: budget, bidding, and locations."),
    ],
    ad_groups: Annotated[
        list[GoogleAdsNewAdGroup] | None,
        Field(
            max_length=MAX_NEW_AD_GROUPS,
            description="For Search: ad groups, each with keywords and at least one ad.",
        ),
    ] = None,
    asset_groups: Annotated[
        list[GoogleAdsNewAssetGroup] | None,
        Field(
            max_length=MAX_NEW_ASSET_GROUPS,
            description="For Performance Max: 1 to 5 asset groups.",
        ),
    ] = None,
    status: Literal["PAUSED", "ENABLED"] = "PAUSED",
) -> dict[str, Any]:
    request = _request(campaign, ad_groups, asset_groups, status)
    selected = sole_writable_entry(ctx.deps.active_context)
    if selected is None:
        raise ModelRetry(_ONE_ACCOUNT)

    async def operation(entry: ResolvedContextEntry) -> Any:
        client: GoogleAdsClient | None = None
        build = CampaignBuild(entry.external_id)
        pending: PendingIntegrationOperationDetail | None = None

        async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
            nonlocal client, pending
            accounts = approved_display_args(ctx).get("_accounts")
            if accounts != approval_accounts([entry]):
                raise ModelRetry(_ACCOUNT_CHANGED)
            today = account_facts(entry).today()
            # The card can change every setting, so check the rules again as approved.
            refusal = " ".join(_problems(request, entry.external_id, today))
            if refusal:
                raise IntegrationValidationError(
                    refusal,
                    provider_key="google_ads",
                    failure_disposition=IntegrationFailureDisposition.NOT_DISPATCHED,
                )
            client = await google_ads_client(ctx, entry)
            goals = await _account_goals(client, entry, request)
            _compile(build, request, request.campaign, today, range(_group_count(request)), goals)
            pending = _pending_detail(entry, request, build)
            return pending

        async def execute() -> IntegrationAuditOutcome[dict[str, Any]]:
            if client is None or pending is None:
                raise RuntimeError("Google Ads campaign creation preparation did not complete")
            try:
                built = await send_build(
                    client,
                    build,
                    login_customer_id=login_customer_id(entry),
                    family="campaigns",
                    operation=_OPERATION,
                )
            except asyncio.CancelledError as exc:
                attach_interrupted_evidence(exc, pending, identity_keys=_IDENTITY)
                raise
            detail = terminal_operation_detail(pending, built.ledger, identity_keys=_IDENTITY)
            data = _result(entry, request, build, built)
            status = audit_status(detail)
            return IntegrationAuditOutcome(
                data,
                status=status,
                external_ref=",".join(built.ledger.external_refs)[:1000] or None,
                operation_detail=detail,
                unverified_result=data if status is AuditStatus.UNVERIFIED else None,
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_ads_create_campaign",
            operation=_OPERATION,
            execute=execute,
            prepare_pending_operation=prepare_pending_operation,
        )

    results = await run_context_scope(
        ctx,
        binding=GOOGLE_ADS_WRITE_BINDING,
        provider_scope_id=selected.external_id,
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


def _request(
    campaign: GoogleAdsNewSearchCampaign | GoogleAdsNewPerformanceMaxCampaign,
    ad_groups: list[GoogleAdsNewAdGroup] | None,
    asset_groups: list[GoogleAdsNewAssetGroup] | None,
    status: str,
) -> GoogleAdsCreateCampaignRequest:
    return validated_request(
        GoogleAdsCreateCampaignRequest,
        {
            "campaign": campaign,
            "ad_groups": ad_groups or [],
            "asset_groups": asset_groups or [],
            "status": status,
        },
    )


def _group_count(request: GoogleAdsCreateCampaignRequest) -> int:
    return len(request.ad_groups if request.campaign.type == "search" else request.asset_groups)


async def _account_goals(
    client: GoogleAdsClient, entry: ResolvedContextEntry, request: GoogleAdsCreateCampaignRequest
) -> tuple[LiveAccountGoal, ...]:
    """Reads what a Performance Max campaign needs from the account, refusing what it lacks.

    Returns:
        The account's conversion goals when the campaign chooses its own, otherwise none.
    """
    campaign = request.campaign
    if campaign.type == "search":
        return ()
    facts = await read_account_facts(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        campaign=campaign,
    )
    refusal = " ".join(account_problems(campaign, facts))
    if refusal:
        raise IntegrationValidationError(
            refusal,
            provider_key="google_ads",
            failure_disposition=IntegrationFailureDisposition.NOT_DISPATCHED,
        )
    return facts.goals


def _validate_args(
    ctx: RunContext[RuntimeDeps],
    campaign: GoogleAdsNewSearchCampaign | GoogleAdsNewPerformanceMaxCampaign,
    ad_groups: list[GoogleAdsNewAdGroup] | None = None,
    asset_groups: list[GoogleAdsNewAssetGroup] | None = None,
    status: Literal["PAUSED", "ENABLED"] = "PAUSED",
) -> None:
    """Refuses a campaign that couldn't serve before asking the operator to approve it."""
    request = _request(campaign, ad_groups, asset_groups, status)
    entry = sole_writable_entry(ctx.deps.active_context)
    problems = _problems(request, entry.external_id if entry else None, None)
    if problems:
        raise ModelRetry(" ".join(problems))


def _problems(
    request: GoogleAdsCreateCampaignRequest, customer_id: str | None, today: date | None
) -> list[str]:
    """Why Google would refuse the campaign, or it couldn't serve: what the card also shows.

    Args:
        customer_id: The account the campaign goes in, when known.
        today: The date in the account time zone, to check the dates; None leaves them out.
    """
    campaign = request.campaign
    problems = _campaign_problems(campaign, today)
    if campaign.type == "performance_max":
        return [*problems, *performance_max_problems(request, customer_id)]
    budget = campaign.budget
    if customer_id and budget.kind == "shared" and budget.budget.customer_id != customer_id:
        problems.append("Choose a shared budget from the account the campaign goes in.")
    facts = new_campaign_facts(campaign)
    for ad_group in request.ad_groups:
        problems.extend(_serving_problems(ad_group))
        problems.extend(ad_group_problems(ad_group, facts))
    return problems


def _campaign_problems(campaign: NewCampaign, today: date | None) -> list[str]:
    problems = []
    if not campaign.locations:
        problems.append("Choose at least one location, so the ads don't show everywhere.")
    if today is not None and campaign.start_date and campaign.start_date < today:
        problems.append("The start date is in the past. Choose today or later.")
    if today is not None and campaign.end_date and campaign.end_date < today:
        problems.append("The end date is in the past. Choose today or later.")
    return problems


def _serving_problems(ad_group: GoogleAdsNewAdGroup) -> list[str]:
    """What a Search ad group needs before Google can show its ads."""
    problems = []
    if not ad_group.keywords:
        problems.append(f"{ad_group.name}: needs at least one keyword to serve.")
    if not ad_group.ads:
        problems.append(f"{ad_group.name}: needs at least one ad to serve.")
    return problems


def _compile(
    build: CampaignBuild,
    request: GoogleAdsCreateCampaignRequest,
    campaign: GoogleAdsNewSearchCampaign | GoogleAdsNewPerformanceMaxCampaign,
    today: date,
    indexes: Sequence[int],
    goals: Sequence[LiveAccountGoal] = (),
) -> None:
    if campaign.type == "performance_max":
        compile_performance_max(build, request, campaign, today, indexes, goals)
        return
    name = add_search_campaign(build, campaign, status=request.status, today=today)
    for index in indexes:
        add_search_ad_group(
            build, request.ad_groups[index], index=index, campaign=name, status=request.status
        )


def _source(step: BuildStep) -> _Source:
    if not isinstance(step.source, CampaignItem | AdGroupItem | AssetGroupItem):
        raise TypeError("Google Ads campaign builds record where each step came from")
    return step.source


def _group_index(source: _Source) -> int:
    """The ad group or asset group a step belongs to, or -1 for the campaign's own objects."""
    if isinstance(source, AdGroupItem):
        return source.ad_group
    if isinstance(source, AssetGroupItem):
        return source.asset_group
    return -1


def _group_names(request: GoogleAdsCreateCampaignRequest) -> list[str]:
    groups = request.ad_groups if request.campaign.type == "search" else request.asset_groups
    return [group.name for group in groups]


def _pending_detail(
    entry: ResolvedContextEntry, request: GoogleAdsCreateCampaignRequest, build: CampaignBuild
) -> PendingIntegrationOperationDetail:
    # One group for the campaign's own objects and one per ad or asset group, so names are
    # stored once.
    items: dict[int, list[IntegrationOperationIntent]] = {}
    for position, step in enumerate(build.steps):
        source = _source(step)
        items.setdefault(_group_index(source), []).append(
            IntegrationOperationIntent(
                fields={
                    "step": str(position),
                    "kind": source.kind,
                    "item": step.label[:MAX_AUDIT_ITEM_CHARS],
                }
            )
        )
    campaign = request.campaign
    names = _group_names(request)
    group_type = "google_ads_ad_group" if campaign.type == "search" else "google_ads_asset_group"
    group_key = "ad_group" if campaign.type == "search" else "asset_group"
    return PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key="campaign" if index < 0 else f"{group_key}:{index}",
                action="create",
                entity_type="google_ads_campaign" if index < 0 else group_type,
                display_name=campaign.name if index < 0 else names[index],
                fields={"status": request.status}
                | (
                    {"type": campaign.type, "bidding": campaign.bidding.strategy}
                    if index < 0
                    else {}
                ),
                items=intents,
            )
            for index, intents in sorted(items.items())
        ],
    )


def _outcome(effect_outcome: str | None) -> str:
    return "created" if effect_outcome == "applied" else (effect_outcome or "unverified")


def _result(
    entry: ResolvedContextEntry,
    request: GoogleAdsCreateCampaignRequest,
    build: CampaignBuild,
    built: BuildResult,
) -> dict[str, Any]:
    counts: Counter[tuple[str, str]] = Counter()
    created: dict[int, str] = {}
    outcomes: dict[int, str] = {}
    campaign_outcome = "unverified"
    campaign_name: str | None = None
    budget_name: str | None = None
    problems: dict[str, dict[str, Any]] = {}
    for step, parent in zip(build.steps, built.ledger.parents, strict=True):
        source = _source(step)
        effect = parent.effects[0]
        counts[(source.kind, effect.outcome)] += 1
        applied = effect.outcome == "applied" and effect.external_ref
        if source.kind in {"ad_group", "asset_group"}:
            outcomes[_group_index(source)] = effect.outcome
            if applied:
                created[_group_index(source)] = effect.external_ref
        elif source.kind == "campaign":
            campaign_outcome = effect.outcome
            campaign_name = effect.external_ref if applied else None
        elif source.kind == "budget" and applied:
            budget_name = effect.external_ref
        # An atomic refusal puts the same reason on every step, so the table lists it once.
        if effect.outcome != "applied" and effect.message and len(problems) < MAX_RESULT_PROBLEMS:
            problems.setdefault(
                effect.message,
                {
                    "item": step.label,
                    "kind": source.kind,
                    "message": effect.message,
                    "error_code": effect.error_code,
                },
            )
    campaign_id = _last_id(campaign_name)
    data: dict[str, Any] = {
        "account_id": entry.external_id,
        "campaign_name": request.campaign.name,
        "campaign_type": request.campaign.type,
        "requested_status": request.status,
        "outcome": _outcome(campaign_outcome),
        "campaign": _campaign_reference(entry.external_id, request, campaign_name, budget_name),
        "kinds": [
            {
                "kind": kind,
                "created": counts[(kind, "applied")],
                "failed": counts[(kind, "failed")],
                "unverified": counts[(kind, "unverified")],
            }
            for kind in _KINDS
            if any(counts[(kind, outcome)] for outcome in ("applied", "failed", "unverified"))
        ],
        "problems": list(problems.values()),
    }
    if request.campaign.type == "search":
        data["ad_groups"] = [
            {
                "name": ad_group.name,
                "outcome": _outcome(outcomes.get(index)),
                "reference": _ad_group_reference(
                    entry.external_id, request.status, campaign_name, ad_group, created.get(index)
                ),
                "keywords": len(ad_group.keywords),
                "negative_keywords": len(ad_group.negative_keywords),
                "ads": len(ad_group.ads),
            }
            for index, ad_group in enumerate(request.ad_groups)
        ]
    else:
        data["asset_groups"] = created_asset_groups(
            request.asset_groups,
            outcomes,
            created,
            customer_id=entry.external_id,
            campaign_id=campaign_id,
            status=request.status,
        )
    return data


def _last_id(resource_name: str | None) -> str | None:
    return resource_name.rsplit("/", 1)[1] if resource_name else None


def _campaign_reference(
    customer_id: str,
    request: GoogleAdsCreateCampaignRequest,
    campaign_name: str | None,
    budget_name: str | None,
) -> dict[str, Any] | None:
    campaign_id = _last_id(campaign_name)
    if campaign_id is None:
        return None
    budget = request.campaign.budget
    budget_id = budget.budget.budget_id if budget.kind == "shared" else _last_id(budget_name)
    return GoogleAdsCampaignReference(
        customer_id=customer_id,
        campaign_id=campaign_id,
        label=request.campaign.name[:500],
        status=request.status,
        campaign_budget_id=budget_id,
    ).model_dump(mode="json")


def _ad_group_reference(
    customer_id: str,
    status: str,
    campaign_name: str | None,
    ad_group: GoogleAdsNewAdGroup,
    resource_name: str | None,
) -> dict[str, Any] | None:
    campaign_id, ad_group_id = _last_id(campaign_name), _last_id(resource_name)
    if campaign_id is None or ad_group_id is None:
        return None
    return GoogleAdsAdGroupReference(
        customer_id=customer_id,
        campaign_id=campaign_id,
        ad_group_id=ad_group_id,
        label=ad_group.name[:500],
        status=status,
    ).model_dump(mode="json")


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Adds the account's facts, Google's location names, and Google's dry run."""
    request = GoogleAdsCreateCampaignRequest.model_validate(args)
    entry = sole_writable_entry(deps.active_context)
    accounts = approval_accounts([entry]) if entry is not None else []
    return {**args, "_accounts": accounts, "_checks": await _checks(deps, entry, request)}


async def _checks(
    deps: RuntimeDeps, entry: ResolvedContextEntry | None, request: GoogleAdsCreateCampaignRequest
) -> dict[str, Any]:
    """Reads what the card names, then dry runs everything the card can't fault."""
    try:
        if entry is None:
            raise LookupError("Google Ads account not selected")
        client = await google_ads_client_for_principal(
            deps.db, actor=deps.user, workspace=deps.workspace, entry=entry
        )
        today = account_facts(entry).today()
        campaign = request.campaign
        if campaign.type == "performance_max":
            return await performance_max_checks(
                client,
                customer_id=entry.external_id,
                login_customer_id=login_customer_id(entry),
                request=request,
                today=today,
            )
        names = await read_locations(
            client,
            customer_id=entry.external_id,
            login_customer_id=login_customer_id(entry),
            keys=[item.key for item in (*campaign.locations, *campaign.excluded_locations)],
        )
        answers = await _dry_run(client, entry, request, today, set(names))
    except (IntegrationError, LookupError, ModelRetry):
        return {"unavailable": True}
    facts = new_campaign_facts(request.campaign)
    return {
        "unavailable": False,
        "today": today.isoformat(),
        "strategy_name": STRATEGY_NAMES.get(facts.strategy),
        "locations": {key: option.name for key, option in names.items()},
        "unknown_locations": [
            item.key
            for item in (*request.campaign.locations, *request.campaign.excluded_locations)
            if item.key not in names
        ],
        **answers,
    }


async def _dry_run(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    request: GoogleAdsCreateCampaignRequest,
    today: date,
    known: set[str],
) -> dict[str, list[Any]]:
    """Returns Google's rejections for the campaign, for each ad group, and for the request."""
    campaign = request.campaign
    # Locations Google doesn't know are already a problem on the card, so leave them out.
    checked = campaign.model_copy(
        update={
            "locations": [item for item in campaign.locations if item.key in known],
            "excluded_locations": [
                item for item in campaign.excluded_locations if item.key in known
            ],
        }
    )
    facts = new_campaign_facts(campaign)
    build = CampaignBuild(entry.external_id)
    _compile(
        build,
        request,
        checked,
        today,
        [
            index
            for index, ad_group in enumerate(request.ad_groups)
            if not ad_group_problems(ad_group, facts) and not _serving_problems(ad_group)
        ],
    )
    answers: dict[str, list[Any]] = {
        "campaign_problems": [],
        "problems": [],
        "request_problems": [],
    }
    for problem in await dry_run_build(
        client, build, login_customer_id=login_customer_id(entry), operation=_OPERATION
    ):
        message = f"Google says: {problem.message}"
        if problem.step is None:
            answers["request_problems"].append(message)
            continue
        source = _source(problem.step)
        if isinstance(source, AdGroupItem):
            fields = ad_group_item_fields(request.ad_groups, source)
            answers["problems"].append({**fields, "message": message})
        else:
            answers["campaign_problems"].append(
                {**_campaign_item_fields(checked, source), "message": message}
            )
    return answers


def _campaign_item_fields(
    campaign: GoogleAdsNewSearchCampaign, source: CampaignItem
) -> dict[str, Any]:
    """Names a rejected campaign item by its content, so an edit can tell it's gone."""
    fields: dict[str, Any] = {"kind": source.kind}
    if source.kind == "location":
        fields["key"] = campaign.locations[source.position].key
    elif source.kind == "excluded_location":
        fields["key"] = campaign.excluded_locations[source.position].key
    elif source.kind == "negative_keyword":
        negative = campaign.negative_keywords[source.position]
        fields |= {"text": negative.text, "match_type": negative.match_type}
    elif source.kind in {"asset", "asset_link"}:
        fields["key"] = campaign.assets[source.position].key
    return fields


DEFINITION = RuntimeToolDefinition(
    name="google_ads_create_campaign",
    function=google_ads_create_campaign,
    description=(
        "Build a complete Google Ads campaign in the one Google Ads account selected in Active "
        "Context, in one approval. Google creates everything or nothing, paused unless status is "
        "ENABLED. campaign.type is 'search' (the default) or 'performance_max'. Every campaign "
        "takes name, budget, bidding, locations (at least one location key from "
        "google_ads_search_targeting), excluded_locations, location_setting (PRESENCE, the "
        "default, or PRESENCE_OR_INTEREST), start_date and end_date as YYYY-MM-DD in the account "
        "time zone (leave start_date out to start when it's turned on), and "
        "contains_eu_political_advertising, true only when the user says the ads are political "
        "and aimed at the EU. "
        "SEARCH: ad_groups is 1 to 20 ad groups, each with keywords and 1 to 3 responsive search "
        "ads, as google_ads_create_ad_groups takes them. budget is {kind: 'new', daily_amount} in "
        "the account currency, or {kind: 'shared', budget} with a shared budget reference. "
        "bidding is one of MANUAL_CPC; MAXIMIZE_CLICKS with optional max_cpc; "
        "MAXIMIZE_CONVERSIONS with optional target_cpa; MAXIMIZE_CONVERSION_VALUE with optional "
        "target_roas as a ratio (3.5 means 350%); or TARGET_IMPRESSION_SHARE with location "
        "(ANYWHERE_ON_PAGE, TOP_OF_PAGE, or ABSOLUTE_TOP_OF_PAGE), share_percent, and max_cpc. "
        "Ad group and keyword click bids are only for MANUAL_CPC; an ad group target_cpa only "
        "when the campaign sets one, and likewise target_roas. Google Search is always on; "
        "search_partners and display_expansion are off unless the user asks. Search campaigns "
        "don't take languages. assets on the campaign, or on one ad group, are up to 20 new "
        "sitelinks {type: 'sitelink', link_text (25), description1 and description2 (35, both or "
        "neither), final_url} and callouts {type: 'callout', text (25)}, with optional start_date "
        "and end_date; use pages and facts from the advertiser's own site. "
        "PERFORMANCE_MAX: asset_groups is 1 to 5 asset groups, each with name, final_url, 3 to "
        "15 headlines (30 characters), 1 to 5 long_headlines (90), 2 to 5 descriptions (90, one "
        "of them 60 or fewer), images [{asset, field_type}] with at least one MARKETING_IMAGE "
        "(landscape) and one SQUARE_MARKETING_IMAGE, optional PORTRAIT_MARKETING_IMAGE, "
        "optional videos (YouTube video asset references), up to 25 search_themes, and up to 20 "
        "audience_signals [{kind, key, name}]: user_list, user_interest, or custom_audience "
        "audiences from google_ads_search_targeting, which guide Google without limiting reach. "
        "Images and videos are asset references from google_ads_upload_media; use a field_type "
        "its fits lists. budget is {kind: 'new', daily_amount}; Performance Max can't share a "
        "budget. bidding is MAXIMIZE_CONVERSIONS with optional target_cpa, or "
        "MAXIMIZE_CONVERSION_VALUE with optional target_roas. languages are language keys from "
        "google_ads_search_targeting; none means every language. business_name (25) and logos "
        "[{asset, field_type: LOGO or LANDSCAPE_LOGO}], at least one LOGO and at most 5, are the "
        "campaign's brand. final_url_expansion is on unless the user asks to keep traffic on the "
        "asset groups' pages. conversion_goals left out bids for the account's goals; a list of "
        "{category, origin} bids for those alone. For a retailer, merchant {merchant_id, "
        "feed_label} shows products from a Merchant Center account linked to this account; its "
        "asset groups may then link no assets, and Google makes them from the feed. New ads go "
        "through Google's policy review."
    ),
    provider="google_ads",
    label="Create Google Ads Campaign",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=120,
    output_model=GoogleAdsCreateCampaignOutput,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    args_validator=_validate_args,
    approval_display_args=_approval_display_args,
    approval_input_model=GoogleAdsCreateCampaignRequest,
    approval_review_fields=("campaign", "ad_groups", "asset_groups"),
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Creating Google Ads Campaign",
        completed_label="Created Google Ads Campaign",
        failed_label="Couldn't Create Google Ads Campaign",
        approval_title="Create Campaign",
        approval_prompt="The agent wants to build this campaign.",
        approve_label="Create Campaign",
        arg_fields=(
            ToolFieldPresentation(
                key="campaign",
                label="Campaign",
                editable=True,
                format="structured",
                # The first kind authorises a review; the card adds the others from searches.
                entity_kinds=(
                    "google_ads_location",
                    "google_ads_campaign_budget",
                    "google_ads_language",
                    "google_ads_asset",
                ),
            ),
            ToolFieldPresentation(
                key="ad_groups", label="Ad Groups", editable=True, format="structured"
            ),
            ToolFieldPresentation(
                key="asset_groups",
                label="Asset Groups",
                editable=True,
                format="structured",
                entity_kinds=("google_ads_asset", "google_ads_audience"),
            ),
            ToolFieldPresentation(
                key="status", label="Status", editable=True, options=("PAUSED", "ENABLED")
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
