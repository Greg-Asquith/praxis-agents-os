# apps/api/integrations/meta_ads/tools/launch_campaign.py

"""Approval-only tool that builds a campaign, its ad sets, and their ads in one go."""

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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
from services.audit_events import PendingIntegrationOperationDetail
from services.integrations.approved_display_args import approved_display_args
from services.integrations.context.domain import ResolvedContextEntry
from utils.metadata import metadata_str

from ..client import MetaAdsClient
from ..creative_features import offered_catalogue
from ..operations.ad_rows import ad_row
from ..operations.create_ad_set import AdSetAccount, AdSetTerms, reaches_eu, read_ad_set_account
from ..operations.create_campaign import read_campaign_account
from ..operations.launch_campaign import (
    OPERATION,
    TURN_ON_CAMPAIGN_KEY,
    LaunchPlan,
    LaunchRun,
    launch_campaign,
    launch_intent_groups,
    launch_problems,
    plan_launch,
    turn_on_key,
)
from ..operations.upload_media import media_upload_row
from ..references import (
    MetaAdsInstagramAccountReference,
    MetaAdsMediaReference,
    MetaAdsPageReference,
    MetaAdsPostReference,
)
from ..throttle import ensure_headroom
from .create_ad_set import ad_set_row, ad_set_terms, check_ad_set_assets, with_live_audiences
from .create_campaign import campaign_row, prepare_campaign
from .schemas.ads import (
    ALL_BUTTONS,
    APP_BUTTONS,
    MAX_AD_SETS,
    MAX_ADS,
    WEBSITE_BUTTONS,
    MetaAdsAutomaticChangeKey,
    MetaAdsButton,
    MetaAdsLink,
    MetaAdsUrlTags,
    follow_shared,
    media_key,
)
from .schemas.campaigns import MetaAdsCreateCampaignRequest
from .schemas.launch import (
    MetaAdsLaunchAd,
    MetaAdsLaunchAdSet,
    MetaAdsLaunchCampaignOutput,
    MetaAdsLaunchCampaignRequest,
)
from .utils.ad_preparation import (
    ads_as_reviewed,
    distinct_media,
    hydrate_references,
    read_ad_inputs,
    require_ready_videos,
    resolve_sources,
)
from .utils.bindings import META_ADS_WRITE_BINDING, RESULTS_FIELD
from .utils.client import meta_ads_available, meta_ads_client_for_principal
from .utils.create_operation import run_create_tool, selected_account, validated
from .utils.mutation_evidence import account_pin, meta_ads_account_target
from .utils.schedule import account_schedule

# A full launch uses about 130 of the roughly 300 calls a new account gets an hour.
_USAGE_LIMIT = 75.0
# Leaves a minute of the 300-second timeout to read the build back and turn it on.
_BUILD_SECONDS = 240.0
_MAX_LISTED_PROBLEMS = 5
_NEXT_STEPS = {
    "live": "Live: ads start once Meta approves them.",
    "paused": "Built, paused. Ask the agent to turn on the campaign when you're ready.",
    "partial": ("Partly built, and nothing is on. Ask the agent to finish it with the step tools."),
    "stopped": "Meta Ads didn't confirm part of the build, so it stopped. Check Ads Manager.",
}


async def meta_ads_launch_campaign(
    ctx: RunContext[RuntimeDeps],
    campaign: Annotated[
        MetaAdsCreateCampaignRequest,
        Field(description="The new campaign, as meta_ads_create_campaign takes it; leave status."),
    ],
    ad_sets: Annotated[
        list[MetaAdsLaunchAdSet],
        Field(
            min_length=1,
            max_length=MAX_AD_SETS,
            description="New ad sets, as meta_ads_create_ad_set takes them, each with a key.",
        ),
    ],
    ads: Annotated[
        list[MetaAdsLaunchAd],
        Field(
            min_length=1,
            max_length=MAX_ADS,
            description="Ad designs, as meta_ads_create_ads takes them, placed by ad_set_keys.",
        ),
    ],
    page: Annotated[MetaAdsPageReference, Field(description="Facebook Page the ads run as.")],
    instagram_account: Annotated[
        MetaAdsInstagramAccountReference | None,
        Field(description="Instagram account the ads run as; omit to use the Page."),
    ] = None,
    link: Annotated[MetaAdsLink | None, Field(description="Link for every ad.")] = None,
    call_to_action: Annotated[
        MetaAdsButton | None, Field(description="Button for every ad; defaults to LEARN_MORE.")
    ] = None,
    url_tags: Annotated[MetaAdsUrlTags | None, Field(description="URL tags for every ad.")] = None,
    automatic_changes: Annotated[
        list[MetaAdsAutomaticChangeKey] | None,
        Field(description="Meta automatic changes the operator asked to turn on; others stay off."),
    ] = None,
    go_live: Annotated[
        bool,
        Field(description="true only when the operator asked to launch; false builds it paused."),
    ] = False,
) -> dict[str, Any]:
    started = time.monotonic()
    values = {
        "campaign": campaign,
        "ad_sets": ad_sets,
        "ads": ads_as_reviewed(ctx, MetaAdsLaunchCampaignRequest, ads),
        "page": page,
        "instagram_account": instagram_account,
        "link": link,
        "call_to_action": call_to_action,
        "url_tags": url_tags,
        "automatic_changes": automatic_changes,
        "go_live": go_live,
    }
    request = validated(MetaAdsLaunchCampaignRequest, values)
    return await run_create_tool(
        ctx,
        _account_entry(ctx.deps, request.account_id),
        tool_name="meta_ads_launch_campaign",
        operation=OPERATION,
        prepare=lambda client, entry: _prepare(
            ctx.deps, client, entry, request, approved_display_args(ctx)
        ),
        pending_detail=lambda entry, prepared: PendingIntegrationOperationDetail(
            target=meta_ads_account_target(entry), intent_groups=launch_intent_groups(prepared.plan)
        ),
        run=lambda client, entry, prepared: launch_campaign(
            client,
            account_id=entry.external_id,
            currency=prepared.currency,
            scope_label=entry.display_name,
            plan=prepared.plan,
            deadline=started + _BUILD_SECONDS,
        ),
        result=lambda run, entry, prepared: _result(run, prepared, entry),
    )


@dataclass(frozen=True, slots=True)
class _Prepared:
    request: MetaAdsLaunchCampaignRequest
    plan: LaunchPlan
    currency: str


def _account_entry(deps: RuntimeDeps, account_id: str) -> ResolvedContextEntry:
    return selected_account(
        deps,
        account_id,
        "The Page, assets, and media must belong to one Meta ad account selected in Active "
        "Context. Ask the user to select it.",
    )


async def _prepare(
    deps: RuntimeDeps,
    client: MetaAdsClient,
    entry: ResolvedContextEntry,
    request: MetaAdsLaunchCampaignRequest,
    reviewed: Mapping[str, Any],
) -> _Prepared:
    """Re-reads everything the launch uses and checks every rule, then dry-runs the campaign.

    Only the campaign can be dry-run here: Meta checks an ad set against a real campaign,
    and an ad against a real ad set, so the build checks those once their parent exists.
    """
    ensure_headroom(entry.external_id, operation=OPERATION, limit=_USAGE_LIMIT)
    request = request.model_copy(
        update={"ad_sets": await with_live_audiences(client, entry, request.ad_sets)}
    )
    _raise_problems(launch_problems(request))
    stores = await check_ad_set_assets(client, entry, request.ad_sets)
    accounts = await _ad_set_accounts(client, entry, request.ad_sets)
    terms: dict[str, AdSetTerms] = {}
    for ad_set, account, store in zip(request.ad_sets, accounts, stores, strict=True):
        try:
            terms[ad_set.key] = ad_set_terms(ad_set, account, store)
        except ModelRetry as exc:
            raise ModelRetry(f"{ad_set.name}: {exc.message}") from None
    media, sources = await read_ad_inputs(deps, client, entry, request, reviewed)
    campaign, currency = await prepare_campaign(client, entry, request.campaign)
    plan = plan_launch(
        request, campaign=campaign, currency=currency, terms=terms, sources=sources, media=media
    )
    return _Prepared(request, plan, currency)


async def _ad_set_accounts(
    client: MetaAdsClient, entry: ResolvedContextEntry, ad_sets: Sequence[MetaAdsLaunchAdSet]
) -> list[AdSetAccount]:
    """Reads the account's minimum and EU defaults once per kind of goal minimum."""
    read: dict[tuple[str, bool], AdSetAccount] = {}
    for ad_set in ad_sets:
        key = (ad_set.goal, ad_set.pay_per_click)
        if key not in read:
            read[key] = await read_ad_set_account(
                client, account_id=entry.external_id, request=ad_set
            )
    return [read[(ad_set.goal, ad_set.pay_per_click)] for ad_set in ad_sets]


def _raise_problems(problems: Sequence[str]) -> None:
    if problems:
        raise ModelRetry(" ".join(problems[:_MAX_LISTED_PROBLEMS]))


def _result(run: LaunchRun, prepared: _Prepared, entry: ResolvedContextEntry) -> dict[str, Any]:
    """Builds the result tree: every object's outcome, created references, and next steps."""
    request, currency = prepared.request, prepared.currency
    ad_sets = [
        {
            **ad_set_row(
                ad_set_run,
                name=settings.name,
                campaign_id=ad_set_run.fields.get("campaign_id"),
                goal=settings.goal,
                eu=item.plan.eu,
                entry=entry,
                currency=currency,
            ),
            "key": item.key,
            "turned_on": _turned_on(run, turn_on_key(item.key)),
        }
        for settings, item, ad_set_run in zip(
            request.ad_sets, run.plan.ad_sets, run.ad_sets, strict=True
        )
    ]
    return {
        "account_id": entry.external_id,
        "currency": currency,
        "state": run.state,
        "message": run.stop_message or run.held or _NEXT_STEPS[run.state],
        "go_live": request.go_live,
        "campaign": campaign_row(run.campaign, request.campaign, entry, currency),
        "campaign_turned_on": _turned_on(run, TURN_ON_CAMPAIGN_KEY),
        "ad_sets": ad_sets,
        "ads": [
            {
                **ad_row(ad_run),
                "adset_id": ad_run.fields.get("adset_id"),
                "ad_set_key": ad_run.fields["ad_set_key"],
            }
            for ad_run in run.ads
        ],
        "uploads": [media_upload_row(upload) for upload in run.uploads],
        "automatic_changes": list(request.automatic_changes or ()),
        "created_off_for_ai": run.plan.created_off_for_ai,
    }


def _turned_on(run: LaunchRun, key: str) -> str | None:
    if not run.plan.go_live:
        return None
    parent = run.turned_on.get(key)
    if parent is None or parent.outcome in ("failed", "skipped"):
        return "not_turned_on"
    return "turned_on" if parent.outcome == "applied" else "unverified"


async def _validate_args(ctx: RunContext[RuntimeDeps], **values: Any) -> None:
    """Checks the whole build against itself before approval; preparation checks it live."""
    request = validated(MetaAdsLaunchCampaignRequest, values)
    entry = _account_entry(ctx.deps, request.account_id)
    _raise_problems(launch_problems(request))
    timezone_name = metadata_str(entry.permissions_metadata.get("timezone_name"))
    for item in (request.campaign, *request.ad_sets):
        if item.start_date or item.end_date:
            account_schedule(item.start_date, item.end_date, timezone_name)
    require_ready_videos(request)
    try:
        await resolve_sources(ctx.deps, request)
    except IntegrationError as exc:
        raise ModelRetry(exc.user_message) from None


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Reads the account's currency, time zone, minimums, and EU defaults, and hydrates assets."""
    request = MetaAdsLaunchCampaignRequest.model_validate(args)
    entry = _account_entry(deps, request.account_id)
    client = await meta_ads_client_for_principal(
        deps.db, actor=deps.user, workspace=deps.workspace, entry=entry
    )
    campaign_account = await read_campaign_account(client, account_id=entry.external_id)
    accounts = await _ad_set_accounts(client, entry, request.ad_sets)
    display: dict[str, Any] = {
        **args,
        # Ads follow the shared settings they copy, so a later shared edit reaches them.
        "ads": follow_shared(args),
        "ad_sets": await _hydrated_ad_sets(deps, request, args["ad_sets"]),
        "page": (await hydrate_references(deps, "meta_ads_page", "page", [request.page]))[0],
    }
    if request.instagram_account is not None:
        display["instagram_account"] = (
            await hydrate_references(
                deps, "meta_ads_instagram_account", "instagram_account", [request.instagram_account]
            )
        )[0]
    sources = await resolve_sources(deps, request)
    return {
        **display,
        "_account": account_pin(entry),
        "_account_name": entry.display_name[:500],
        "_currency": campaign_account.currency,
        "_timezone": campaign_account.timezone_name,
        "_minimum": campaign_account.minimum,
        "_minimum_spend_limit": campaign_account.minimum_spend_limit,
        # Per ad set key: the goal's daily minimum, and whether Meta needs EU names.
        "_ad_set_accounts": {
            ad_set.key: {
                "minimum": account.minimum,
                "minimum_goal": ad_set.goal,
                "eu": {
                    "applies": reaches_eu(ad_set),
                    "default_payer": account.dsa_payor,
                    "default_beneficiary": account.dsa_beneficiary,
                },
            }
            for ad_set, account in zip(request.ad_sets, accounts, strict=True)
        },
        **await _hydrated_media(deps, request),
        "_files": [source.approval_details() for source in sources],
        "_automatic_change_catalogue": offered_catalogue(),
        "_buttons": {"website": list(WEBSITE_BUTTONS), "app": list(APP_BUTTONS)},
    }


async def _hydrated_ad_sets(
    deps: RuntimeDeps, request: MetaAdsLaunchCampaignRequest, raw: list[Any]
) -> list[Any]:
    """Replaces each ad set's Page, pixel, and app with Meta's own, read once per asset."""
    ad_sets = [dict(item) for item in raw]
    for key, kind, id_field in (
        ("page", "meta_ads_page", "page_id"),
        ("pixel", "meta_ads_pixel", "pixel_id"),
        ("app", "meta_ads_application", "application_id"),
    ):
        references = {
            getattr(reference, id_field): reference
            for item in request.ad_sets
            if (reference := getattr(item, key)) is not None
        }
        if not references:
            continue
        hydrated = await hydrate_references(deps, kind, "ad_sets", list(references.values()))
        found = {item[id_field]: item for item in hydrated}
        for display, item in zip(ad_sets, request.ad_sets, strict=True):
            if (reference := getattr(item, key)) is not None:
                display[key] = found.get(getattr(reference, id_field), display[key])
    return ad_sets


async def _hydrated_media(
    deps: RuntimeDeps, request: MetaAdsLaunchCampaignRequest
) -> dict[str, Any]:
    """Hydrates library media and posts, so the card shows Meta's own pictures and text."""
    library = [
        item for item in distinct_media(request).values() if isinstance(item, MetaAdsMediaReference)
    ]
    media = await hydrate_references(deps, "meta_ads_media", "ads", library) if library else []
    posts = list({ad.post.key: ad.post for ad in request.ads if ad.post is not None}.values())
    hydrated_posts = await hydrate_references(deps, "meta_ads_post", "ads", posts) if posts else []
    return {
        "_media": {
            ":".join(media_key(MetaAdsMediaReference.model_validate(item))): item for item in media
        },
        "_posts": {MetaAdsPostReference.model_validate(item).key: item for item in hydrated_posts},
    }


DEFINITION = RuntimeToolDefinition(
    name="meta_ads_launch_campaign",
    function=meta_ads_launch_campaign,
    description=(
        "Build a new campaign with up to 10 ad sets and 50 ads in one Meta ad account, in one "
        "approval. Use this for a new campaign in one go; use meta_ads_create_campaign, "
        "meta_ads_create_ad_set, and meta_ads_create_ads to fix or extend one. campaign takes "
        "meta_ads_create_campaign's arguments, each ad set meta_ads_create_ad_set's arguments "
        "without campaign plus a short key such as uk_prospecting, and each ad "
        "meta_ads_create_ads's design with ad_set_keys in place of ad_sets; every ad set needs "
        "at least one ad. Follow the same order and rules as those tools: list Pages, pixels, "
        "and media with meta_ads_list_assets, find places and interests with "
        "meta_ads_search_targeting, upload videos with meta_ads_upload_media and wait until "
        "they're ready, and propose the build in plain words first. Workspace image Files can "
        "be passed as media directly. Leave status off the campaign and every ad. Everything "
        "is created paused. Set go_live true only when the operator asked to launch: once "
        "everything is built and confirmed, the ad sets and then the campaign are turned on, "
        "and the ads run and spend once Meta approves them. If anything fails, nothing is "
        "turned on and the result says what was built; finish it with the step tools, and "
        "turn it on with meta_ads_update_status. Every Meta automatic change is sent off; list "
        "in automatic_changes only those the operator explicitly asked for. Write ad text only "
        "from the operator's brief and approved brand material, never make claims the "
        "operator hasn't confirmed, and for special ad categories don't mention protected "
        "characteristics."
    ),
    provider="meta_ads",
    label="Launch Meta Campaign",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=300,
    args_validator=_validate_args,
    output_model=MetaAdsLaunchCampaignOutput,
    integration_binding=META_ADS_WRITE_BINDING,
    availability_check=meta_ads_available,
    approval_display_args=_approval_display_args,
    # Edits are checked whole, and again by the tool before anything is sent.
    approval_input_model=MetaAdsLaunchCampaignRequest,
    presentation=ToolPresentation(
        icon="meta_ads",
        running_label="Launching Meta Campaign",
        completed_label="Launched Meta Campaign",
        failed_label="Couldn't Launch Meta Campaign",
        approval_title="Launch Meta Campaign",
        approval_prompt="The agent wants to build this campaign in {_account_name}.",
        approve_label="Approve & Build",
        arg_fields=(
            ToolFieldPresentation(
                key="campaign", label="Campaign", editable=True, format="structured"
            ),
            ToolFieldPresentation(
                key="ad_sets",
                label="Ad Sets",
                editable=True,
                format="structured",
                entity_kinds=(
                    "meta_ads_audience",
                    "meta_ads_targeting_location",
                    "meta_ads_targeting_interest",
                ),
            ),
            ToolFieldPresentation(
                key="ads",
                label="Ads",
                editable=True,
                format="structured",
                entity_kinds=("meta_ads_media", "file"),
            ),
            ToolFieldPresentation(
                key="page",
                label="Facebook Page",
                editable=True,
                format="entity",
                entity_kind="meta_ads_page",
                width="half",
            ),
            ToolFieldPresentation(
                key="instagram_account",
                label="Instagram Account",
                editable=True,
                format="entity",
                entity_kind="meta_ads_instagram_account",
                secondary=True,
                width="half",
                show_empty=True,
            ),
            ToolFieldPresentation(
                key="link", label="Website Link", editable=True, secondary=True, width="half"
            ),
            ToolFieldPresentation(
                key="call_to_action",
                label="CTA Button",
                editable=True,
                options=ALL_BUTTONS,
                secondary=True,
                width="half",
            ),
            ToolFieldPresentation(key="url_tags", label="URL Tags", editable=True, secondary=True),
            ToolFieldPresentation(
                key="automatic_changes",
                label="Automatic Changes",
                editable=True,
                format="structured",
                secondary=True,
            ),
            # Structured, so only the card's own Go Live control edits it.
            ToolFieldPresentation(
                key="go_live", label="Go Live", editable=True, format="structured"
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
