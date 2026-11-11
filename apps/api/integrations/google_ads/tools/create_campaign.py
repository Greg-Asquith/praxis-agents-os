# apps/api/integrations/google_ads/tools/create_campaign.py

"""Approval-only tool that builds a complete Search campaign in one all-or-nothing request."""

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
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.context.targeted import run_context_scope
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..client import GoogleAdsClient
from ..operations.build import BuildResult, BuildStep, CampaignBuild, dry_run_build, send_build
from ..operations.search_ad_groups import AdGroupItem, add_search_ad_group
from ..operations.search_campaigns import CampaignItem, add_search_campaign, new_campaign_facts
from ..operations.search_targeting import read_locations
from ..references import GoogleAdsAdGroupReference, GoogleAdsCampaignReference
from .schemas.ad_groups import MAX_NEW_AD_GROUPS, MAX_RESULT_PROBLEMS, GoogleAdsNewAdGroup
from .schemas.campaigns import (
    GoogleAdsCreateCampaignOutput,
    GoogleAdsCreateCampaignRequest,
    GoogleAdsNewSearchCampaign,
)
from .utils.accounts import account_facts, approval_accounts
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
)
_ONE_ACCOUNT = (
    "A campaign goes in one account. Ask the user to select exactly one Google Ads account "
    "with permission to make changes in Active Context."
)
_ACCOUNT_CHANGED = "The approved Google Ads account is no longer selected. Ask for approval again."

type _Source = CampaignItem | AdGroupItem


async def google_ads_create_campaign(
    ctx: RunContext[RuntimeDeps],
    campaign: Annotated[
        GoogleAdsNewSearchCampaign,
        Field(description="The campaign's settings: budget, bidding, networks, and locations."),
    ],
    ad_groups: Annotated[
        list[GoogleAdsNewAdGroup],
        Field(
            min_length=1,
            max_length=MAX_NEW_AD_GROUPS,
            description="Ad groups, each with keywords and at least one ad.",
        ),
    ],
    status: Literal["PAUSED", "ENABLED"] = "PAUSED",
) -> dict[str, Any]:
    request = _request(campaign, ad_groups, status)
    selected = _account_entry(ctx.deps.active_context)
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
            _compile(build, request, request.campaign, today, range(len(request.ad_groups)))
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
    campaign: GoogleAdsNewSearchCampaign,
    ad_groups: list[GoogleAdsNewAdGroup],
    status: str,
) -> GoogleAdsCreateCampaignRequest:
    return validated_request(
        GoogleAdsCreateCampaignRequest,
        {
            "campaign": campaign,
            "ad_groups": ad_groups,
            "status": status,
        },
    )


def _validate_args(
    ctx: RunContext[RuntimeDeps],
    campaign: GoogleAdsNewSearchCampaign,
    ad_groups: list[GoogleAdsNewAdGroup],
    status: Literal["PAUSED", "ENABLED"] = "PAUSED",
) -> None:
    """Refuses a campaign that couldn't serve before asking the operator to approve it."""
    request = _request(campaign, ad_groups, status)
    entry = _account_entry(ctx.deps.active_context)
    problems = _problems(request, entry.external_id if entry else None, None)
    if problems:
        raise ModelRetry(" ".join(problems))


def _account_entry(active: ResolvedActiveContext | None) -> ResolvedContextEntry | None:
    """Returns the one account in Active Context this run may write to, or None."""
    entries = active.compatible_entries(GOOGLE_ADS_WRITE_BINDING) if active else ()
    writable = [entry for entry in entries if entry.write_allowed]
    return writable[0] if len(writable) == 1 else None


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
    budget = campaign.budget
    if customer_id and budget.kind == "shared" and budget.budget.customer_id != customer_id:
        problems.append("Choose a shared budget from the account the campaign goes in.")
    facts = new_campaign_facts(campaign)
    for ad_group in request.ad_groups:
        problems.extend(_serving_problems(ad_group))
        problems.extend(ad_group_problems(ad_group, facts))
    return problems


def _campaign_problems(campaign: GoogleAdsNewSearchCampaign, today: date | None) -> list[str]:
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
    campaign: GoogleAdsNewSearchCampaign,
    today: date,
    indexes: Sequence[int],
) -> None:
    name = add_search_campaign(build, campaign, status=request.status, today=today)
    for index in indexes:
        add_search_ad_group(
            build, request.ad_groups[index], index=index, campaign=name, status=request.status
        )


def _source(step: BuildStep) -> _Source:
    if not isinstance(step.source, CampaignItem | AdGroupItem):
        raise TypeError("Google Ads campaign builds record where each step came from")
    return step.source


def _pending_detail(
    entry: ResolvedContextEntry, request: GoogleAdsCreateCampaignRequest, build: CampaignBuild
) -> PendingIntegrationOperationDetail:
    # One group for the campaign's own objects and one per ad group, so names are stored once.
    items: dict[int, list[IntegrationOperationIntent]] = {}
    for position, step in enumerate(build.steps):
        source = _source(step)
        group = source.ad_group if isinstance(source, AdGroupItem) else -1
        items.setdefault(group, []).append(
            IntegrationOperationIntent(
                fields={
                    "step": str(position),
                    "kind": source.kind,
                    "item": step.label[:MAX_AUDIT_ITEM_CHARS],
                }
            )
        )
    campaign = request.campaign
    return PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key="campaign" if index < 0 else f"ad_group:{index}",
                action="create",
                entity_type="google_ads_campaign" if index < 0 else "google_ads_ad_group",
                display_name=campaign.name if index < 0 else request.ad_groups[index].name,
                fields={"status": request.status}
                | ({"bidding": campaign.bidding.strategy} if index < 0 else {}),
                items=intents,
            )
            for index, intents in sorted(items.items())
        ],
    )


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
        if isinstance(source, AdGroupItem) and source.kind == "ad_group":
            outcomes[source.ad_group] = effect.outcome
            if applied:
                created[source.ad_group] = effect.external_ref
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
    return {
        "account_id": entry.external_id,
        "campaign_name": request.campaign.name,
        "requested_status": request.status,
        "outcome": "created" if campaign_outcome == "applied" else campaign_outcome,
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
        "ad_groups": [
            {
                "name": ad_group.name,
                "outcome": "created"
                if outcomes.get(index) == "applied"
                else outcomes.get(index, "unverified"),
                "reference": _ad_group_reference(
                    entry.external_id, request.status, campaign_name, ad_group, created.get(index)
                ),
                "keywords": len(ad_group.keywords),
                "negative_keywords": len(ad_group.negative_keywords),
                "ads": len(ad_group.ads),
            }
            for index, ad_group in enumerate(request.ad_groups)
        ],
        "problems": list(problems.values()),
    }


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
    entry = _account_entry(deps.active_context)
    accounts = approval_accounts([entry]) if entry is not None else []
    return {**args, "_accounts": accounts, "_checks": await _checks(deps, entry, request)}


async def _checks(
    deps: RuntimeDeps, entry: ResolvedContextEntry | None, request: GoogleAdsCreateCampaignRequest
) -> dict[str, Any]:
    """Reads Google's names for the locations, then dry runs everything the card can't fault."""
    try:
        if entry is None:
            raise LookupError("Google Ads account not selected")
        client = await google_ads_client_for_principal(
            deps.db, actor=deps.user, workspace=deps.workspace, entry=entry
        )
        today = account_facts(entry).today()
        campaign = request.campaign
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
        "Build a complete Google Ads Search campaign in the one Google Ads account selected in "
        "Active Context, in one approval: its "
        "budget, bidding, networks, locations, dates, negative keywords, and 1 to 20 ad groups, "
        "each with keywords and 1 to 3 responsive search ads, as google_ads_create_ad_groups "
        "takes them. Google creates everything or nothing. budget is {kind: 'new', "
        "daily_amount} in the account currency, or {kind: 'shared', budget} with a shared "
        "budget reference. bidding is one of MANUAL_CPC; MAXIMIZE_CLICKS with optional max_cpc; "
        "MAXIMIZE_CONVERSIONS with optional target_cpa; MAXIMIZE_CONVERSION_VALUE with optional "
        "target_roas as a ratio (3.5 means 350%); or TARGET_IMPRESSION_SHARE with location "
        "(ANYWHERE_ON_PAGE, TOP_OF_PAGE, or ABSOLUTE_TOP_OF_PAGE), share_percent, and max_cpc. "
        "Ad group and keyword click bids are only for MANUAL_CPC; an ad group target_cpa only "
        "when the campaign sets one, and likewise target_roas. locations needs at least one "
        "location key from google_ads_search_targeting; excluded_locations is optional. "
        "location_setting is PRESENCE (people in, or regularly in, a location; the default) or "
        "PRESENCE_OR_INTEREST. Google Search is always on; search_partners and "
        "display_expansion are off unless the user asks. Dates are YYYY-MM-DD in the account "
        "time zone; leave start_date out to start when the campaign is turned on. Set "
        "contains_eu_political_advertising true only when the user says the ads are political "
        "and aimed at the EU. Search campaigns don't take languages. assets on the campaign, or "
        "on one ad group, are up to 20 new sitelinks {type: 'sitelink', link_text (25), "
        "description1 and description2 (35, both or neither), final_url} and callouts "
        "{type: 'callout', text (25)}, with optional start_date and end_date; use pages and "
        "facts from the advertiser's own site. Everything is created paused unless status is "
        "ENABLED. New ads go through Google's policy review."
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
    approval_review_fields=("campaign", "ad_groups"),
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Creating Google Ads Campaign",
        completed_label="Created Google Ads Campaign",
        failed_label="Couldn't Create Google Ads Campaign",
        approval_title="Create Search Campaign",
        approval_prompt="The agent wants to build this Search campaign.",
        approve_label="Create Campaign",
        arg_fields=(
            ToolFieldPresentation(
                key="campaign",
                label="Campaign",
                editable=True,
                format="structured",
                # The first kind authorises a review; the card adds the others from searches.
                entity_kinds=("google_ads_location", "google_ads_campaign_budget"),
            ),
            ToolFieldPresentation(
                key="ad_groups", label="Ad Groups", editable=True, format="structured"
            ),
            ToolFieldPresentation(
                key="status", label="Status", editable=True, options=("PAUSED", "ENABLED")
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
