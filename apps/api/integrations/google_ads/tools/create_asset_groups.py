# apps/api/integrations/google_ads/tools/create_asset_groups.py

"""Approval-only tool that adds complete asset groups to a live Performance Max campaign."""

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
from ..operations.build import BuildResult, BuildStep, CampaignBuild, dry_run_build, send_build
from ..operations.performance_max import (
    AssetGroupItem,
    PerformanceMaxCampaignFacts,
    add_asset_group,
    read_performance_max_campaign,
)
from ..references import GoogleAdsAssetGroupReference, GoogleAdsCampaignReference
from .schemas.ad_groups import MAX_RESULT_PROBLEMS
from .schemas.performance_max import (
    MAX_NEW_ASSET_GROUPS,
    GoogleAdsCreateAssetGroupsOutput,
    GoogleAdsCreateAssetGroupsRequest,
    GoogleAdsNewAssetGroup,
    asset_group_problems,
)
from .utils.accounts import approval_accounts, writable_entry
from .utils.ad_group_builds import MAX_AUDIT_ITEM_CHARS
from .utils.bindings import GOOGLE_ADS_WRITE_BINDING, RESULTS_FIELD
from .utils.client import google_ads_available, google_ads_client, google_ads_client_for_principal
from .utils.mutation_evidence import (
    attach_interrupted_evidence,
    audit_status,
    google_ads_account_target,
    terminal_operation_detail,
)
from .utils.performance_max_builds import (
    MEDIA_FROM_ANOTHER_ACCOUNT,
    asset_group_answer,
    dry_run_ready,
    group_media,
    read_images,
    read_signal_audiences,
    signals,
    unknown_audiences,
)
from .utils.requests import validated_request
from .utils.routing import login_customer_id

_OPERATION = "create_asset_groups"
_IDENTITY = ("step",)
_KINDS = (
    "asset_group",
    "listing_filter",
    "text_asset",
    "asset_group_link",
    "search_theme",
    "audience_signal",
)
# Google's limit on asset groups in one campaign.
_MAX_CAMPAIGN_ASSET_GROUPS = 100
_MISSING = "This campaign is removed, or no longer exists in Google Ads."
_NOT_PERFORMANCE_MAX = "New asset groups only go in Performance Max campaigns."
_NO_BRAND_GUIDELINES = (
    "This campaign keeps its business name and logos on each asset group, which this tool "
    "can't add. Turn on brand guidelines for the campaign in Google Ads, then try again."
)


def _campaign_name(reference: GoogleAdsCampaignReference) -> str:
    return f"customers/{reference.customer_id}/campaigns/{reference.campaign_id}"


async def google_ads_create_asset_groups(
    ctx: RunContext[RuntimeDeps],
    campaign: Annotated[
        GoogleAdsCampaignReference,
        Field(description="The live Performance Max campaign to add the asset groups to."),
    ],
    asset_groups: Annotated[
        list[GoogleAdsNewAssetGroup],
        Field(
            min_length=1,
            max_length=MAX_NEW_ASSET_GROUPS,
            description="New asset groups, each with its text, images, themes, and signals.",
        ),
    ],
    status: Literal["PAUSED", "ENABLED"] = "PAUSED",
) -> dict[str, Any]:
    request = validated_request(
        GoogleAdsCreateAssetGroupsRequest,
        {"campaign": campaign, "asset_groups": asset_groups, "status": status},
    )

    async def operation(entry: ResolvedContextEntry, _selected: Sequence[Any]) -> Any:
        client: GoogleAdsClient | None = None
        build = CampaignBuild(entry.external_id)
        pending: PendingIntegrationOperationDetail | None = None
        campaign_name = request.campaign.label

        async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
            nonlocal client, pending, campaign_name
            client = await google_ads_client(ctx, entry)
            # The card can change the campaign, names, and assets, so check them again as approved.
            facts = await _read_facts(client, entry, request)
            refusal = " ".join(_problems(request, facts))
            if refusal:
                raise IntegrationValidationError(
                    refusal,
                    provider_key="google_ads",
                    failure_disposition=IntegrationFailureDisposition.NOT_DISPATCHED,
                )
            if facts is None:
                raise RuntimeError("Google Ads campaign facts were checked above")
            campaign_name = facts.name
            _compile(build, request, facts, range(len(request.asset_groups)))
            pending = _pending_detail(entry, request, build)
            return pending

        async def execute() -> IntegrationAuditOutcome[dict[str, Any]]:
            if client is None or pending is None:
                raise RuntimeError("Google Ads asset group creation preparation did not complete")
            try:
                built = await send_build(
                    client,
                    build,
                    login_customer_id=login_customer_id(entry),
                    family="asset_groups",
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
            tool_name="google_ads_create_asset_groups",
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
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    request: GoogleAdsCreateAssetGroupsRequest,
) -> PerformanceMaxCampaignFacts | None:
    return await read_performance_max_campaign(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        campaign_id=request.campaign.campaign_id,
    )


def _campaign_problem(
    facts: PerformanceMaxCampaignFacts | None, request: GoogleAdsCreateAssetGroupsRequest
) -> str | None:
    if facts is None:
        return _MISSING
    if facts.channel != "PERFORMANCE_MAX":
        return _NOT_PERFORMANCE_MAX
    if not facts.brand_guidelines:
        return _NO_BRAND_GUIDELINES
    room = _MAX_CAMPAIGN_ASSET_GROUPS - len(facts.asset_group_names)
    if len(request.asset_groups) > room:
        return (
            f"A campaign holds at most {_MAX_CAMPAIGN_ASSET_GROUPS} asset groups, and this one "
            f"has room for {max(room, 0)} more."
        )
    return None


def _problems(
    request: GoogleAdsCreateAssetGroupsRequest, facts: PerformanceMaxCampaignFacts | None
) -> list[str]:
    """Why Google would refuse the asset groups: what the card also shows."""
    problem = _campaign_problem(facts, request)
    if problem is not None or facts is None:
        return [problem or _MISSING]
    problems = []
    existing = {name.casefold() for name in facts.asset_group_names}
    retail = facts.merchant_id is not None
    for group in request.asset_groups:
        if group.name.casefold() in existing:
            problems.append(f"{group.name}: the campaign already has an asset group by this name.")
        problems.extend(asset_group_problems(group, retail=retail))
    customer_id = request.campaign.customer_id
    if any(reference.customer_id != customer_id for reference in group_media(request.asset_groups)):
        problems.append(MEDIA_FROM_ANOTHER_ACCOUNT)
    return problems


def _compile(
    build: CampaignBuild,
    request: GoogleAdsCreateAssetGroupsRequest,
    facts: PerformanceMaxCampaignFacts,
    indexes: Sequence[int],
) -> None:
    for index in indexes:
        add_asset_group(
            build,
            request.asset_groups[index],
            index=index,
            campaign=_campaign_name(request.campaign),
            status=request.status,
            retail=facts.merchant_id is not None,
        )


def _source(step: BuildStep) -> AssetGroupItem:
    if not isinstance(step.source, AssetGroupItem):
        raise TypeError("Google Ads asset group builds record where each step came from")
    return step.source


def _pending_detail(
    entry: ResolvedContextEntry, request: GoogleAdsCreateAssetGroupsRequest, build: CampaignBuild
) -> PendingIntegrationOperationDetail:
    # One group per asset group, so its name is stored once rather than on every asset.
    items: dict[int, list[IntegrationOperationIntent]] = {}
    for position, step in enumerate(build.steps):
        source = _source(step)
        items.setdefault(source.asset_group, []).append(
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
                key=f"asset_group:{index}",
                action="create",
                entity_type="google_ads_asset_group",
                display_name=request.asset_groups[index].name,
                fields={"campaign": _campaign_name(request.campaign), "status": request.status},
                items=intents,
            )
            for index, intents in sorted(items.items())
        ],
    )


def _result(
    entry: ResolvedContextEntry,
    request: GoogleAdsCreateAssetGroupsRequest,
    campaign_name: str,
    build: CampaignBuild,
    built: BuildResult,
) -> dict[str, Any]:
    counts: Counter[tuple[str, str]] = Counter()
    created: dict[int, str] = {}
    outcomes: dict[int, str] = {}
    problems: dict[str, dict[str, Any]] = {}
    for step, parent in zip(build.steps, built.ledger.parents, strict=True):
        source = _source(step)
        effect = parent.effects[0]
        counts[(source.kind, effect.outcome)] += 1
        if source.kind == "asset_group":
            outcomes[source.asset_group] = effect.outcome
            if effect.outcome == "applied" and effect.external_ref:
                created[source.asset_group] = effect.external_ref
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
        "asset_groups": [
            {
                "name": group.name,
                "outcome": "created"
                if outcomes.get(index) == "applied"
                else outcomes.get(index, "unverified"),
                "reference": _reference(request, group, created.get(index)),
                "headlines": len(group.headlines),
                "long_headlines": len(group.long_headlines),
                "descriptions": len(group.descriptions),
                "images": len(group.images),
                "videos": len(group.videos),
                "search_themes": len(group.search_themes),
                "audience_signals": len(group.audience_signals),
            }
            for index, group in enumerate(request.asset_groups)
        ],
        "problems": list(problems.values()),
    }


def _reference(
    request: GoogleAdsCreateAssetGroupsRequest,
    group: GoogleAdsNewAssetGroup,
    resource_name: str | None,
) -> dict[str, Any] | None:
    if resource_name is None:
        return None
    return GoogleAdsAssetGroupReference(
        customer_id=request.campaign.customer_id,
        campaign_id=request.campaign.campaign_id,
        asset_group_id=resource_name.rsplit("/", 1)[1],
        label=group.name[:500],
        status=request.status,
    ).model_dump(mode="json")


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Adds the account's facts, the campaign, its media and audiences, and Google's dry run."""
    request = GoogleAdsCreateAssetGroupsRequest.model_validate(args)
    entry = writable_entry(deps.active_context, request.campaign.customer_id)
    accounts = approval_accounts([entry]) if entry is not None else []
    return {**args, "_accounts": accounts, "_checks": await _checks(deps, entry, request)}


async def _checks(
    deps: RuntimeDeps,
    entry: ResolvedContextEntry | None,
    request: GoogleAdsCreateAssetGroupsRequest,
) -> dict[str, Any]:
    """Reads the campaign, images, and audiences, then dry runs what the card can't fault."""
    try:
        if entry is None:
            raise LookupError("Google Ads account not selected")
        client = await google_ads_client_for_principal(
            deps.db, actor=deps.user, workspace=deps.workspace, entry=entry
        )
        facts = await _read_facts(client, entry, request)
        groups = request.asset_groups
        image_ids = sorted({image.asset.asset_id for group in groups for image in group.images})
        known: dict[str, Any] = {
            "images": await read_images(
                client,
                customer_id=entry.external_id,
                login_customer_id=login_customer_id(entry),
                asset_ids=image_ids,
            ),
            "audiences": await read_signal_audiences(
                client,
                customer_id=entry.external_id,
                login_customer_id=login_customer_id(entry),
                audiences=signals(groups),
            ),
        }
        problems, request_problems = await _dry_run(client, entry, request, facts, known)
    except (IntegrationError, LookupError):
        return {"unavailable": True}
    return {
        "unavailable": False,
        "campaign": {
            "key": _campaign_name(request.campaign),
            "name": facts.name if facts else request.campaign.label,
            "retail": facts is not None and facts.merchant_id is not None,
            "problem": _campaign_problem(facts, request),
        },
        "existing_names": list(facts.asset_group_names) if facts else [],
        "images": known["images"],
        "unknown_images": [asset_id for asset_id in image_ids if asset_id not in known["images"]],
        "audiences": known["audiences"],
        "unknown_audiences": unknown_audiences(groups, known["audiences"]),
        "problems": problems,
        "request_problems": request_problems,
    }


async def _dry_run(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    request: GoogleAdsCreateAssetGroupsRequest,
    facts: PerformanceMaxCampaignFacts | None,
    known: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Returns Google's rejections by asset group, and whole-request problems."""
    # Google's answer would only repeat a problem the card already shows.
    if facts is None or _problems(request, facts):
        return [], []
    build = CampaignBuild(entry.external_id)
    _compile(
        build,
        request,
        facts,
        [index for index, group in enumerate(request.asset_groups) if dry_run_ready(group, known)],
    )
    if not build.steps:
        return [], []
    problems: list[dict[str, Any]] = []
    request_problems: list[str] = []
    for problem in await dry_run_build(
        client,
        build,
        login_customer_id=login_customer_id(entry),
        operation=_OPERATION,
        partial_failure=False,
    ):
        message = f"Google says: {problem.message}"
        if problem.step is None:
            request_problems.append(message)
        else:
            problems.append(
                asset_group_answer(request.asset_groups, _source(problem.step), message)
            )
    return problems, request_problems


DEFINITION = RuntimeToolDefinition(
    name="google_ads_create_asset_groups",
    function=google_ads_create_asset_groups,
    description=(
        "Add up to 5 asset groups to one live Performance Max campaign, in one approval. Each "
        "takes what google_ads_create_campaign's asset_groups take: a name unique in the "
        "campaign, final_url, 3 to 15 headlines (30 characters), 1 to 5 long_headlines (90), 2 "
        "to 5 descriptions (90, one of them 60 or fewer), images [{asset, field_type}] with at "
        "least one MARKETING_IMAGE and one SQUARE_MARKETING_IMAGE, optional YouTube videos, up "
        "to 25 search_themes, and up to 20 audience_signals [{kind, key, name}] (user_list, "
        "user_interest, or custom_audience from google_ads_search_targeting), which guide Google "
        "without limiting reach. Images and videos come from google_ads_upload_media; use a "
        "field_type its fits lists. In a campaign with a Merchant Center feed, an asset group "
        "may link no assets, and Google makes them from the feed. The campaign's business name "
        "and logos cover every asset group. Asset groups are created paused unless status is "
        "ENABLED. Google creates everything or nothing, and reviews new assets for policy."
    ),
    provider="google_ads",
    label="Create Google Ads Asset Groups",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=120,
    output_model=GoogleAdsCreateAssetGroupsOutput,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    approval_display_args=_approval_display_args,
    approval_input_model=GoogleAdsCreateAssetGroupsRequest,
    approval_review_fields=("campaign", "asset_groups"),
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Adding Google Ads Asset Groups",
        completed_label="Added Google Ads Asset Groups",
        failed_label="Couldn't Add Google Ads Asset Groups",
        approval_title="Add Asset Groups",
        approval_prompt="The agent wants to add these asset groups.",
        approve_label="Add Asset Groups",
        arg_fields=(
            ToolFieldPresentation(
                key="campaign",
                label="Campaign",
                format="entity",
                editable=True,
                entity_kind="google_ads_campaign",
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
