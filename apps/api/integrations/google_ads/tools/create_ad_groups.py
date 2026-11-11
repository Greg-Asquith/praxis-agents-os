# apps/api/integrations/google_ads/tools/create_ad_groups.py

"""Approval-only tool that creates Search ad groups with their keywords and ads in one request."""

import asyncio
from collections import Counter
from collections.abc import Sequence
from typing import Annotated, Any, Literal

from pydantic import Field
from pydantic_ai import RunContext

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
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.context.targeted import run_context_targets
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..client import GoogleAdsClient
from ..operations.build import BuildResult, CampaignBuild, dry_run_build, send_build
from ..operations.search_ad_groups import (
    AdGroupItem,
    SearchCampaignFacts,
    add_search_ad_group,
    read_search_campaign,
)
from ..references import GoogleAdsAdGroupReference, GoogleAdsCampaignReference
from .schemas.ad_groups import (
    MAX_NEW_AD_GROUPS,
    MAX_RESULT_PROBLEMS,
    GoogleAdsCreateAdGroupsOutput,
    GoogleAdsCreateAdGroupsRequest,
    GoogleAdsNewAdGroup,
)
from .utils.accounts import approval_accounts, writable_entry
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

_OPERATION = "create_ad_groups"
_IDENTITY = ("step",)
_MISSING = "This campaign is removed, or no longer exists in Google Ads."
_NOT_SEARCH = "New ad groups with keywords only go in Search campaigns."
_KINDS = ("ad_group", "keyword", "negative_keyword", "ad", "asset")


def _campaign_name(reference: GoogleAdsCampaignReference) -> str:
    return f"customers/{reference.customer_id}/campaigns/{reference.campaign_id}"


async def google_ads_create_ad_groups(
    ctx: RunContext[RuntimeDeps],
    campaign: Annotated[
        GoogleAdsCampaignReference,
        Field(description="The live Search campaign to add the ad groups to."),
    ],
    ad_groups: Annotated[
        list[GoogleAdsNewAdGroup],
        Field(
            min_length=1,
            max_length=MAX_NEW_AD_GROUPS,
            description="New ad groups, each with its keywords, negative keywords, and ads.",
        ),
    ],
    status: Literal["PAUSED", "ENABLED"] = "PAUSED",
) -> dict[str, Any]:
    request = validated_request(
        GoogleAdsCreateAdGroupsRequest,
        {"campaign": campaign, "ad_groups": ad_groups, "status": status},
    )

    async def operation(entry: ResolvedContextEntry, _selected: Sequence[Any]) -> Any:
        client: GoogleAdsClient | None = None
        build = CampaignBuild(entry.external_id)
        pending: PendingIntegrationOperationDetail | None = None
        campaign_name = request.campaign.label

        async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
            nonlocal client, pending, campaign_name
            client = await google_ads_client(ctx, entry)
            # The card can change the campaign, bids, and names, so check them again as approved.
            facts = await _read_facts(client, entry, request)
            refusal = _refusal(request, facts)
            if refusal is not None:
                raise IntegrationValidationError(
                    refusal,
                    provider_key="google_ads",
                    failure_disposition=IntegrationFailureDisposition.NOT_DISPATCHED,
                )
            campaign_name = facts.name if facts else campaign_name
            _compile(build, request, range(len(request.ad_groups)))
            pending = _pending_detail(entry, request, build)
            return pending

        async def execute() -> IntegrationAuditOutcome[dict[str, Any]]:
            if client is None or pending is None:
                raise RuntimeError("Google Ads ad group creation preparation did not complete")
            try:
                built = await send_build(
                    client,
                    build,
                    login_customer_id=login_customer_id(entry),
                    family="ad_groups",
                    operation=_OPERATION,
                )
            except asyncio.CancelledError as exc:
                attach_interrupted_evidence(exc, pending, identity_keys=_IDENTITY)
                raise
            detail = terminal_operation_detail(pending, built.ledger, identity_keys=_IDENTITY)
            data = _result(entry, request, campaign_name, build, built)
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
            tool_name="google_ads_create_ad_groups",
            operation=_OPERATION,
            execute=execute,
            prepare_pending_operation=prepare_pending_operation,
        )

    results = await run_context_targets(
        ctx,
        binding=GOOGLE_ADS_WRITE_BINDING,
        references=[request.campaign],
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


async def _read_facts(
    client: GoogleAdsClient, entry: ResolvedContextEntry, request: GoogleAdsCreateAdGroupsRequest
) -> SearchCampaignFacts | None:
    return await read_search_campaign(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        campaign_id=request.campaign.campaign_id,
    )


def _campaign_problem(facts: SearchCampaignFacts | None) -> str | None:
    if facts is None:
        return _MISSING
    return None if facts.channel == "SEARCH" else _NOT_SEARCH


def _refusal(
    request: GoogleAdsCreateAdGroupsRequest, facts: SearchCampaignFacts | None
) -> str | None:
    """The reason this request can't go to Google, for the agent to put right."""
    problem = _campaign_problem(facts)
    if problem is not None or facts is None:
        return problem
    problems = [
        item for ad_group in request.ad_groups for item in ad_group_problems(ad_group, facts)
    ]
    return " ".join(problems) or None


def _compile(
    build: CampaignBuild, request: GoogleAdsCreateAdGroupsRequest, indexes: Sequence[int]
) -> None:
    for index in indexes:
        add_search_ad_group(
            build,
            request.ad_groups[index],
            index=index,
            campaign=_campaign_name(request.campaign),
            status=request.status,
        )


def _source(step: Any) -> AdGroupItem:
    if not isinstance(step.source, AdGroupItem):
        raise TypeError("Google Ads ad group builds record where each step came from")
    return step.source


def _pending_detail(
    entry: ResolvedContextEntry, request: GoogleAdsCreateAdGroupsRequest, build: CampaignBuild
) -> PendingIntegrationOperationDetail:
    # One group per ad group, so its name is stored once rather than on every keyword.
    items: dict[int, list[IntegrationOperationIntent]] = {}
    for position, step in enumerate(build.steps):
        source = _source(step)
        items.setdefault(source.ad_group, []).append(
            IntegrationOperationIntent(
                fields={
                    "step": str(position),
                    "kind": source.kind,
                    "item": step.label[:MAX_AUDIT_ITEM_CHARS],
                }
            )
        )
    return PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key=f"ad_group:{index}",
                action="create",
                entity_type="google_ads_ad_group",
                display_name=request.ad_groups[index].name,
                fields={"campaign": _campaign_name(request.campaign), "status": request.status},
                items=intents,
            )
            for index, intents in sorted(items.items())
        ],
    )


def _result(
    entry: ResolvedContextEntry,
    request: GoogleAdsCreateAdGroupsRequest,
    campaign_name: str,
    build: CampaignBuild,
    built: BuildResult,
) -> dict[str, Any]:
    counts: Counter[tuple[str, str]] = Counter()
    created_names: dict[int, str] = {}
    outcomes: dict[int, str] = {}
    problems: dict[str, dict[str, Any]] = {}
    for step, parent in zip(build.steps, built.ledger.parents, strict=True):
        source = _source(step)
        effect = parent.effects[0]
        counts[(source.kind, effect.outcome)] += 1
        if source.kind == "ad_group":
            outcomes[source.ad_group] = effect.outcome
            if effect.outcome == "applied" and effect.external_ref:
                created_names[source.ad_group] = effect.external_ref
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
        "campaign_name": campaign_name,
        "requested_status": request.status,
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
                "reference": _reference(request, ad_group, created_names.get(index)),
                "keywords": len(ad_group.keywords),
                "negative_keywords": len(ad_group.negative_keywords),
                "ads": len(ad_group.ads),
            }
            for index, ad_group in enumerate(request.ad_groups)
        ],
        "problems": list(problems.values()),
    }


def _reference(
    request: GoogleAdsCreateAdGroupsRequest,
    ad_group: GoogleAdsNewAdGroup,
    resource_name: str | None,
) -> dict[str, Any] | None:
    if resource_name is None:
        return None
    return GoogleAdsAdGroupReference(
        customer_id=request.campaign.customer_id,
        campaign_id=request.campaign.campaign_id,
        ad_group_id=resource_name.rsplit("/", 1)[1],
        label=ad_group.name[:500],
        status=request.status,
    ).model_dump(mode="json")


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Adds the account's facts, what the campaign allows, and Google's dry run."""
    request = GoogleAdsCreateAdGroupsRequest.model_validate(args)
    entry = writable_entry(deps.active_context, request.campaign.customer_id)
    accounts = approval_accounts([entry]) if entry is not None else []
    return {**args, "_accounts": accounts, "_checks": await _checks(deps, entry, request)}


async def _checks(
    deps: RuntimeDeps, entry: ResolvedContextEntry | None, request: GoogleAdsCreateAdGroupsRequest
) -> dict[str, Any]:
    """Reads the campaign and dry runs the ad groups it would accept."""
    try:
        if entry is None:
            raise LookupError("Google Ads account not selected")
        client = await google_ads_client_for_principal(
            deps.db, actor=deps.user, workspace=deps.workspace, entry=entry
        )
        facts = await _read_facts(client, entry, request)
        problems, request_problems = await _dry_run(client, entry, request, facts)
    except (IntegrationError, LookupError):
        return {"unavailable": True}
    return {
        "unavailable": False,
        "campaign": {
            "key": _campaign_name(request.campaign),
            "name": facts.name if facts else request.campaign.label,
            "strategy": facts.strategy if facts else None,
            "strategy_name": STRATEGY_NAMES.get(facts.strategy) if facts else None,
            "accepts_cpc_bid": facts.accepts_cpc_bid if facts else False,
            "accepts_target_cpa": facts.accepts_target_cpa if facts else False,
            "accepts_target_roas": facts.accepts_target_roas if facts else False,
            "problem": _campaign_problem(facts),
        },
        "existing_names": list(facts.ad_group_names) if facts else [],
        "problems": problems,
        "request_problems": request_problems,
    }


async def _dry_run(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    request: GoogleAdsCreateAdGroupsRequest,
    facts: SearchCampaignFacts | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Returns Google's rejections, each with the item it's about, and whole-request problems."""
    if facts is None or _campaign_problem(facts) is not None:
        return [], []
    build = CampaignBuild(entry.external_id)
    # The card already explains these ad groups' problems, so Google needn't repeat them.
    _compile(
        build,
        request,
        [
            index
            for index, ad_group in enumerate(request.ad_groups)
            if not ad_group_problems(ad_group, facts)
        ],
    )
    if not build.steps:
        return [], []
    problems: list[dict[str, Any]] = []
    request_problems: list[str] = []
    for problem in await dry_run_build(
        client, build, login_customer_id=login_customer_id(entry), operation=_OPERATION
    ):
        message = f"Google says: {problem.message}"
        if problem.step is None:
            request_problems.append(message)
        else:
            problems.append(
                {
                    **ad_group_item_fields(request.ad_groups, _source(problem.step)),
                    "message": message,
                }
            )
    return problems, request_problems


DEFINITION = RuntimeToolDefinition(
    name="google_ads_create_ad_groups",
    function=google_ads_create_ad_groups,
    description=(
        "Create up to 20 Google Ads ad groups in one live Search campaign, in one approval. Each "
        "has a name unique in the campaign, optional keywords (text, match type, optional click "
        "bid and final URL), negative keywords, up to 3 responsive search ads, and up to 20 new "
        "sitelinks and callouts in assets, as google_ads_create_campaign takes them. A default "
        "click bid or keyword click bid is only for campaigns using Manual CPC; a target CPA or "
        "target ROAS override is only for campaigns using that kind of target. Ad groups and ads "
        "are created paused unless status is ENABLED. Google creates everything or nothing. New "
        "ads go through Google's policy review before they can show."
    ),
    provider="google_ads",
    label="Create Google Ads Ad Groups",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=120,
    output_model=GoogleAdsCreateAdGroupsOutput,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    approval_display_args=_approval_display_args,
    approval_input_model=GoogleAdsCreateAdGroupsRequest,
    approval_review_fields=("campaign", "ad_groups"),
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Creating Google Ads Ad Groups",
        completed_label="Created Google Ads Ad Groups",
        failed_label="Couldn't Create Google Ads Ad Groups",
        approval_title="Create Ad Groups",
        approval_prompt="The agent wants to create these ad groups.",
        approve_label="Approve & Create",
        arg_fields=(
            ToolFieldPresentation(
                key="campaign",
                label="Campaign",
                format="entity",
                editable=True,
                entity_kind="google_ads_campaign",
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
