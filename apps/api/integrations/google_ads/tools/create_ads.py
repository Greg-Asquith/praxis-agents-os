# apps/api/integrations/google_ads/tools/create_ads.py

"""Approval-only tool that creates responsive search ads in existing Google Ads ad groups."""

import asyncio
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Literal

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
from ..operations.build import BuildResult, CampaignBuild, dry_run_build, send_build
from ..operations.list_ad_groups import list_ad_groups
from ..operations.responsive_search_ads import AdReview, ad_group_ad_body, read_ad_reviews
from ..references import GoogleAdsAdGroupReference
from .schemas.ads import (
    MAX_NEW_ADS,
    GoogleAdsCreateAdsOutput,
    GoogleAdsCreateAdsRequest,
    GoogleAdsNewAd,
)
from .utils.accounts import approval_accounts, writable_entry
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

_OPERATION = "create_ads"
_IDENTITY = ("step",)
_MISSING = "This ad group or its campaign is removed, or no longer exists in Google Ads."
_NOT_SEARCH = "Responsive search ads only go in Search campaigns."

type _Pair = tuple[int, GoogleAdsAdGroupReference]


def _ad_group_name(reference: GoogleAdsAdGroupReference) -> str:
    return f"customers/{reference.customer_id}/adGroups/{reference.ad_group_id}"


async def google_ads_create_ads(
    ctx: RunContext[RuntimeDeps],
    ads: Annotated[
        list[GoogleAdsNewAd],
        Field(
            min_length=1,
            max_length=MAX_NEW_ADS,
            description=(
                "Responsive search ads, each with its copy, links, and the ad groups to create "
                "it in. Every ad group must be in the same account."
            ),
        ),
    ],
    status: Literal["PAUSED", "ENABLED"] = "PAUSED",
) -> dict[str, Any]:
    request = validated_request(GoogleAdsCreateAdsRequest, {"ads": ads, "status": status})
    checks = approved_display_args(ctx).get("_checks")
    shown = checks.get("ad_groups") if isinstance(checks, Mapping) else None
    ad_groups: Mapping[str, Any] = shown if isinstance(shown, Mapping) else {}
    references = {
        _ad_group_name(reference): reference for ad in request.ads for reference in ad.ad_groups
    }

    async def operation(entry: ResolvedContextEntry, _selected: Sequence[Any]) -> Any:
        client: GoogleAdsClient | None = None
        build = CampaignBuild(entry.external_id)
        pairs: list[_Pair] = []
        pending: PendingIntegrationOperationDetail | None = None

        async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
            nonlocal client, pairs, pending
            client = await google_ads_client(ctx, entry)
            pairs = _compile(build, request, ad_groups)
            pending = _pending_detail(entry, request, pairs, ad_groups)
            return pending

        async def execute() -> IntegrationAuditOutcome[dict[str, Any]]:
            if client is None or pending is None or not pairs:
                raise RuntimeError("Google Ads ad creation preparation did not complete")
            try:
                built = await send_build(
                    client,
                    build,
                    login_customer_id=login_customer_id(entry),
                    family="ads",
                    operation=_OPERATION,
                )
            except asyncio.CancelledError as exc:
                attach_interrupted_evidence(exc, pending, identity_keys=_IDENTITY)
                raise
            detail = terminal_operation_detail(pending, built.ledger, identity_keys=_IDENTITY)
            reviews = await _reviews(client, entry, built)
            data = _result(entry, request, pairs, ad_groups, built, reviews)
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
            tool_name="google_ads_create_ads",
            operation=_OPERATION,
            execute=execute,
            prepare_pending_operation=prepare_pending_operation,
        )

    results = await run_context_targets(
        ctx,
        binding=GOOGLE_ADS_WRITE_BINDING,
        references=list(references.values()),
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


def _compile(
    build: CampaignBuild, request: GoogleAdsCreateAdsRequest, ad_groups: Mapping[str, Any]
) -> list[_Pair]:
    """Adds one `AdGroupAd` per ad and ad group, in request order, and returns the pairs."""
    pairs: list[_Pair] = []
    for index, ad in enumerate(request.ads):
        for reference in ad.ad_groups:
            name = _ad_group_name(reference)
            build.create(
                "adGroupAd",
                ad_group_ad_body(ad, ad_group=name, status=request.status),
                label=f"{_shown_name(reference, ad_groups)} · Ad {index + 1}",
            )
            pairs.append((index, reference))
    return pairs


def _shown_name(reference: GoogleAdsAdGroupReference, ad_groups: Mapping[str, Any]) -> str:
    check = ad_groups.get(_ad_group_name(reference))
    name = check.get("name") if isinstance(check, Mapping) else None
    return str(name or reference.label)


def _pending_detail(
    entry: ResolvedContextEntry,
    request: GoogleAdsCreateAdsRequest,
    pairs: Sequence[_Pair],
    ad_groups: Mapping[str, Any],
) -> PendingIntegrationOperationDetail:
    # Every step is an `AdGroupAd`, so the build sends them in the order they were added.
    items = [
        IntegrationOperationIntent(
            fields={
                "step": str(step),
                "ad": str(index + 1),
                "ad_group": _ad_group_name(reference),
                "ad_group_name": _shown_name(reference, ad_groups),
                "headline": request.ads[index].headlines[0].text,
                "status": request.status,
            }
        )
        for step, (index, reference) in enumerate(pairs)
    ]
    return PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key="ad:create", action="create", entity_type="google_ads_ad", items=items
            )
        ],
    )


async def _reviews(
    client: GoogleAdsClient, entry: ResolvedContextEntry, built: BuildResult
) -> dict[str, AdReview]:
    """Reads the created ads back; a failed read leaves their status unknown, not failed."""
    names = [effect.external_ref for effect in _effects(built) if effect.external_ref]
    if not names:
        return {}
    try:
        return await read_ad_reviews(
            client,
            customer_id=entry.external_id,
            login_customer_id=login_customer_id(entry),
            resource_names=names,
        )
    except IntegrationError:
        return {}


def _effects(built: BuildResult) -> list[Any]:
    return [parent.effects[0] for parent in built.ledger.parents]


def _result(
    entry: ResolvedContextEntry,
    request: GoogleAdsCreateAdsRequest,
    pairs: Sequence[_Pair],
    ad_groups: Mapping[str, Any],
    built: BuildResult,
    reviews: Mapping[str, AdReview],
) -> dict[str, Any]:
    rows = []
    for (index, reference), effect in zip(pairs, _effects(built), strict=True):
        created = effect.external_ref if effect.outcome == "applied" else None
        review = reviews.get(created) if created else None
        check = ad_groups.get(_ad_group_name(reference))
        rows.append(
            {
                "ad": index + 1,
                "ad_group": _ad_group_name(reference),
                "ad_group_name": _shown_name(reference, ad_groups),
                "campaign_name": check.get("campaign_name") if isinstance(check, Mapping) else None,
                "headline": request.ads[index].headlines[0].text,
                "resource_name": created,
                "outcome": "created" if effect.outcome == "applied" else effect.outcome,
                "status": review.status if review else None,
                "review_status": review.review_status if review else None,
                "approval_status": review.approval_status if review else None,
                "error_code": effect.error_code,
                "message": effect.message,
            }
        )
    return {"account_id": entry.external_id, "requested_status": request.status, "ads": rows}


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Adds the account's facts, each ad group's campaign and problem, and Google's dry run."""
    request = GoogleAdsCreateAdsRequest.model_validate(args)
    entry = writable_entry(deps.active_context, request.ads[0].ad_groups[0].customer_id)
    accounts = approval_accounts([entry]) if entry is not None else []
    return {**args, "_accounts": accounts, "_checks": await _checks(deps, entry, request)}


async def _checks(
    deps: RuntimeDeps, entry: ResolvedContextEntry | None, request: GoogleAdsCreateAdsRequest
) -> dict[str, Any]:
    """Reads the ad groups and dry runs the ads that target usable ones."""
    try:
        if entry is None:
            raise LookupError("Google Ads account not selected")
        client = await google_ads_client_for_principal(
            deps.db, actor=deps.user, workspace=deps.workspace, entry=entry
        )
        ad_groups = await _read_ad_groups(client, entry, request)
        ads, problems = await _dry_run(client, entry, request, ad_groups)
    except (IntegrationError, LookupError):
        return {"unavailable": True}
    return {"unavailable": False, "ad_groups": ad_groups, "ads": ads, "problems": problems}


async def _read_ad_groups(
    client: GoogleAdsClient, entry: ResolvedContextEntry, request: GoogleAdsCreateAdsRequest
) -> dict[str, dict[str, Any]]:
    references = {
        _ad_group_name(reference): reference for ad in request.ads for reference in ad.ad_groups
    }
    rows = await list_ad_groups(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        ad_group_ids=[reference.ad_group_id for reference in references.values()],
        limit=len(references),
    )
    live: dict[str, dict[str, Any]] = {}
    for row in rows:
        ad_group = row.get("adGroup")
        campaign = row.get("campaign")
        if not isinstance(ad_group, Mapping) or not isinstance(campaign, Mapping):
            continue
        name = f"customers/{entry.external_id}/adGroups/{ad_group.get('id')}"
        if name not in references:
            continue
        problem = None if campaign.get("advertisingChannelType") == "SEARCH" else _NOT_SEARCH
        live[name] = {
            "name": str(ad_group.get("name") or references[name].label),
            "status": ad_group.get("status"),
            "campaign_name": campaign.get("name"),
            "problem": problem,
        }
    return {
        name: live.get(name)
        or {"name": reference.label, "status": None, "campaign_name": None, "problem": _MISSING}
        for name, reference in references.items()
    }


async def _dry_run(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    request: GoogleAdsCreateAdsRequest,
    ad_groups: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Returns, per ad, the copy checked and Google's rejections; and whole-request problems."""
    usable = request.model_copy(
        update={
            "ads": [
                ad.model_copy(
                    update={
                        "ad_groups": [
                            reference
                            for reference in ad.ad_groups
                            if ad_groups[_ad_group_name(reference)]["problem"] is None
                        ]
                    }
                )
                for ad in request.ads
            ]
        }
    )
    ads: list[dict[str, Any]] = [
        {"ad": ad.model_dump(mode="json", exclude={"ad_groups"}), "problems": []}
        for ad in request.ads
    ]
    build = CampaignBuild(entry.external_id)
    pairs = _compile(build, usable, ad_groups)
    if not pairs:
        return ads, []
    # Steps are matched by identity: two ads with the same copy in one ad group compare equal.
    positions = {id(step): position for position, step in enumerate(build.steps)}
    request_problems: list[str] = []
    for problem in await dry_run_build(
        client, build, login_customer_id=login_customer_id(entry), operation=_OPERATION
    ):
        if problem.step is None:
            request_problems.append(f"Google says: {problem.message}")
            continue
        index, reference = pairs[positions[id(problem.step)]]
        ads[index]["problems"].append(
            {"ad_group": _ad_group_name(reference), "message": f"Google says: {problem.message}"}
        )
    return ads, request_problems


DEFINITION = RuntimeToolDefinition(
    name="google_ads_create_ads",
    function=google_ads_create_ads,
    description=(
        "Create up to 50 Google Ads responsive search ads in existing Search ad groups in one "
        "account, in one approval. Each ad has 3 to 15 headlines (30 characters each), 2 to 4 "
        "descriptions (90 characters each), a final URL, an optional mobile final URL, "
        "optional display paths (15 characters each), optional pins, and 1 to 10 ad groups; "
        "each ad group gets its own copy of the ad. Ads are created paused unless status is "
        "ENABLED. Google creates every ad or none of them. New ads go through Google's "
        "policy review before they can show; the result reports each ad's review state."
    ),
    provider="google_ads",
    label="Create Google Ads",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=120,
    output_model=GoogleAdsCreateAdsOutput,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    approval_display_args=_approval_display_args,
    approval_input_model=GoogleAdsCreateAdsRequest,
    approval_review_fields=("ads",),
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Creating Google Ads",
        completed_label="Created Google Ads",
        failed_label="Couldn't Create Google Ads",
        approval_title="Create Search Ads",
        approval_prompt="The agent wants to create these responsive search ads.",
        approve_label="Approve & Create",
        arg_fields=(
            ToolFieldPresentation(
                key="ads",
                label="Ads",
                editable=True,
                format="structured",
                entity_kinds=("google_ads_ad_group",),
            ),
            ToolFieldPresentation(
                key="status", label="Status", editable=True, options=("PAUSED", "ENABLED")
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
