# apps/api/integrations/meta_ads/tools/create_ads.py

"""Approval-only tool that creates new ads, or ads from existing posts, in existing ad sets."""

from collections.abc import Mapping
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
from services.audit_events import (
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    PendingIntegrationOperationDetail,
)
from services.integrations.approved_display_args import approved_display_args, proposed_args
from services.integrations.context.domain import ResolvedContextEntry

from ..creative_features import offered_catalogue
from ..operations.ad_rows import ad_row
from ..operations.create_ads import create_ads, upload_intent_group
from ..operations.plan_ads import duplicate_name, plan_ads
from ..operations.upload_media import media_upload_row
from ..references import (
    MetaAdsInstagramAccountReference,
    MetaAdsMediaReference,
    MetaAdsPageReference,
    MetaAdsPostReference,
)
from .schemas.ads import (
    ALL_BUTTONS,
    APP_BUTTONS,
    MAX_ADS,
    WEBSITE_BUTTONS,
    MetaAdsAdDesign,
    MetaAdsAdStatusChoice,
    MetaAdsAutomaticChangeKey,
    MetaAdsButton,
    MetaAdsCreateAdsOutput,
    MetaAdsCreateAdsRequest,
    MetaAdsLink,
    MetaAdsUrlTags,
    follow_shared,
    media_key,
)
from .utils.ad_preparation import (
    Prepared,
    check_designs,
    distinct_ad_sets,
    distinct_media,
    hydrate_references,
    prepare,
    required_currency,
    resolve_sources,
)
from .utils.bindings import META_ADS_WRITE_BINDING, RESULTS_FIELD
from .utils.client import meta_ads_available
from .utils.create_operation import run_create_tool, selected_account, validated
from .utils.mutation_evidence import (
    account_pin,
    meta_ads_account_target,
)

_OPERATION = "create_ads"
_AD_SETS_CHANGED = "The ads' ad sets changed after approval. Ask the agent to prepare them again."

type AdDesigns = Annotated[
    list[MetaAdsAdDesign],
    Field(
        min_length=1, max_length=MAX_ADS, description="Ad designs; each is created in its ad sets."
    ),
]


async def meta_ads_create_ads(
    ctx: RunContext[RuntimeDeps],
    ads: AdDesigns,
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
    status: Annotated[
        MetaAdsAdStatusChoice,
        Field(description="paused creates ads off; active lets them run once Meta approves them."),
    ] = "paused",
    automatic_changes: Annotated[
        list[MetaAdsAutomaticChangeKey] | None,
        Field(description="Meta automatic changes the operator asked to turn on; others stay off."),
    ] = None,
) -> dict[str, Any]:
    values = {
        "ads": ads,
        "page": page,
        "instagram_account": instagram_account,
        "link": link,
        "call_to_action": call_to_action,
        "url_tags": url_tags,
        "status": status,
        "automatic_changes": automatic_changes,
    }
    request = validated(MetaAdsCreateAdsRequest, {**values, "ads": _ads_as_reviewed(ctx, ads)})
    ad_sets = [sorted(ref.adset_id for ref in design.ad_sets) for design in request.ads]
    # References nested in `ads` aren't re-resolved when an approval is edited, so preparation
    # re-reads every one through this account and the workspace.
    return await run_create_tool(
        ctx,
        _account_entry(ctx.deps, request.account_id),
        tool_name="meta_ads_create_ads",
        operation=_OPERATION,
        # The card can't change ad sets; media is re-read in preparation instead.
        proposal_changed=lambda proposed: _proposed_ad_sets(proposed) != ad_sets,
        changed_message=_AD_SETS_CHANGED,
        prepare=lambda client, entry: prepare(
            ctx.deps, client, entry, request, approved_display_args(ctx)
        ),
        pending_detail=lambda entry, prepared: _pending_operation_detail(entry, request, prepared),
        run=lambda client, entry, prepared: create_ads(
            client,
            account_id=entry.external_id,
            scope_label=entry.display_name,
            planned=prepared.planned,
            intent_fields=prepared.intent_fields,
            sources=prepared.sources,
            media=prepared.media,
            page_id=request.page.page_id,
            instagram_user_id=request.instagram_user_id,
            promoted_objects=prepared.promoted_objects,
            checked=prepared.checked,
        ),
        result=lambda run, entry, prepared: {
            "account_id": entry.external_id,
            "ads": [ad_row(ad_run) for ad_run in run.ads],
            "uploads": [media_upload_row(upload) for upload in run.uploads],
            "automatic_changes": list(request.automatic_changes or ()),
            "created_off_for_ai": prepared.created_off_for_ai,
        },
    )


def _ads_as_reviewed(ctx: RunContext[RuntimeDeps], ads: list[MetaAdsAdDesign]) -> list[Any]:
    """Returns the ads as the card showed them: unedited ones follow the shared settings they copy."""
    # Card edits start from `follow_shared`, so only ads left as proposed still hold copies.
    proposed = proposed_args(ctx)
    try:
        unedited = validated(MetaAdsCreateAdsRequest, proposed).ads == ads
    except ModelRetry:
        return ads
    return follow_shared(proposed) if unedited else ads


def _account_entry(deps: RuntimeDeps, account_id: str) -> ResolvedContextEntry:
    return selected_account(
        deps,
        account_id,
        "The Page, ad sets, and media must belong to one Meta ad account selected in "
        "Active Context. Ask the user to select it.",
    )


def _proposed_ad_sets(values: Mapping[str, Any]) -> list[list[str]]:
    """Reads only the ad set IDs from the proposal; the card may have fixed the rest of it."""
    ads = values.get("ads")
    return [
        sorted(
            str(reference.get("adset_id"))
            for reference in design.get("ad_sets") or ()
            if isinstance(reference, Mapping)
        )
        for design in (ads if isinstance(ads, list) else ())
        if isinstance(design, Mapping)
    ]


async def _validate_args(ctx: RunContext[RuntimeDeps], **values: Any) -> None:
    """Rejects what Meta or this tool won't accept before approval, so the agent can fix it."""
    request = validated(MetaAdsCreateAdsRequest, values)
    _account_entry(ctx.deps, request.account_id)
    ad_sets = distinct_ad_sets(request)
    check_designs(request, ad_sets)
    for item in distinct_media(request).values():
        if (
            isinstance(item, MetaAdsMediaReference)
            and item.media_type == "video"
            and item.media_status != "ready"
        ):
            raise ModelRetry(
                f"The video {item.label} isn't ready. List the account's videos and use it "
                "once its media_status is ready."
            )
    try:
        await resolve_sources(ctx.deps, request)
    except IntegrationError as exc:
        raise ModelRetry(exc.user_message) from None
    planned = plan_ads(request, {key: ref.label for key, ref in ad_sets.items()})
    if name := duplicate_name(planned, {}):
        raise ModelRetry(f"Two ads would be called {name} in one ad set. Rename one.")


def _pending_operation_detail(
    entry: ResolvedContextEntry, request: MetaAdsCreateAdsRequest, prepared: Prepared
) -> PendingIntegrationOperationDetail:
    groups: list[IntegrationOperationIntentGroup] = []
    if prepared.sources:
        groups.append(upload_intent_group(prepared.sources))
    groups.append(
        IntegrationOperationIntentGroup(
            key="ads:create",
            action="create_ad",
            entity_type="meta_ads_ad",
            fields={
                "page_id": request.page.page_id,
                "instagram_user_id": request.instagram_user_id,
                "created_off_for_ai": prepared.created_off_for_ai,
            },
            items=[
                IntegrationOperationIntent(fields=prepared.intent_fields[ad.index])
                for ad in prepared.planned
            ],
        )
    )
    return PendingIntegrationOperationDetail(
        target=meta_ads_account_target(entry), intent_groups=groups
    )


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Hydrates the Page, accounts, ad sets, media, and posts, and pins the account and Files."""
    request = MetaAdsCreateAdsRequest.model_validate(args)
    entry = _account_entry(deps, request.account_id)
    # Ads follow the shared settings they copy, so a later shared edit reaches them.
    display: dict[str, Any] = {**args, "ads": follow_shared(args)}
    display["page"] = (await hydrate_references(deps, "meta_ads_page", "page", [request.page]))[0]
    if request.instagram_account is not None:
        display["instagram_account"] = (
            await hydrate_references(
                deps, "meta_ads_instagram_account", "instagram_account", [request.instagram_account]
            )
        )[0]
    ad_sets = list(distinct_ad_sets(request).values())
    hydrated_sets = await hydrate_references(deps, "meta_ads_ad_set", "ads", ad_sets)
    library = [
        item for item in distinct_media(request).values() if isinstance(item, MetaAdsMediaReference)
    ]
    hydrated_media = (
        await hydrate_references(deps, "meta_ads_media", "ads", library) if library else []
    )
    posts = list({d.post.key: d.post for d in request.ads if d.post is not None}.values())
    hydrated_posts = await hydrate_references(deps, "meta_ads_post", "ads", posts) if posts else []
    sources = await resolve_sources(deps, request)
    return {
        **display,
        "_account": account_pin(entry),
        "_account_name": entry.display_name[:500],
        "_currency": required_currency(entry),
        "_ad_sets": {item["adset_id"]: item for item in hydrated_sets},
        "_media": {
            ":".join(media_key(MetaAdsMediaReference.model_validate(item))): item
            for item in hydrated_media
        },
        # Meta's own excerpt and picture for each post, never the agent's copy.
        "_posts": {MetaAdsPostReference.model_validate(item).key: item for item in hydrated_posts},
        "_files": [source.approval_details() for source in sources],
        "_automatic_change_catalogue": offered_catalogue(),
        "_buttons": {"website": list(WEBSITE_BUTTONS), "app": list(APP_BUTTONS)},
    }


DEFINITION = RuntimeToolDefinition(
    name="meta_ads_create_ads",
    function=meta_ads_create_ads,
    description=(
        "Create up to 50 image, video, carousel, or existing post ads in existing ad sets of "
        "one Meta ad account, in one approval. Each item in ads is one design, created once in "
        "each of its ad_sets (at most 10 ad sets in all), named after the design and the ad "
        "set when it goes in several. Order: upload videos with meta_ads_upload_media and "
        "wait until they're ready; list the Pages, Instagram accounts, and media with "
        "meta_ads_list_assets; then create the ads. Workspace image Files can be passed as "
        "media directly and are uploaded with the ads. vertical_media adds a 9:16 version "
        "for Stories and Reels. Use format existing_post when the operator wants to promote a "
        "post that is already published, such as one that did well organically: pass post "
        'from meta_ads_list_assets(kinds=["posts"]) with only name, ad_sets, and status. '
        "The post runs unchanged, with its own text and media, as the Page or Instagram "
        "account that published it; an Instagram post can also take link and call_to_action. "
        "page, instagram_account, link, call_to_action, url_tags, and "
        "status apply to every ad unless an ad sets its own. Ads are created paused unless "
        "status is active; active ads run and spend once Meta approves them. Every Meta "
        "automatic change, such as rewritten text, music, or AI-generated images, is sent "
        "off; list in automatic_changes only those the operator explicitly asked for. Write "
        "ad text only from the operator's brief and approved brand material, never make "
        "claims the operator hasn't confirmed, and for special ad categories don't mention "
        "protected characteristics. To build many ads, read them from a spreadsheet File the "
        "operator provides. Meta checks every ad before any is created. Each result reports "
        "Meta's review status; check it later with meta_ads_list_objects and turn ads on "
        "with meta_ads_update_status once approved."
    ),
    provider="meta_ads",
    label="Create Meta Ads",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=300,
    args_validator=_validate_args,
    output_model=MetaAdsCreateAdsOutput,
    integration_binding=META_ADS_WRITE_BINDING,
    availability_check=meta_ads_available,
    approval_display_args=_approval_display_args,
    # Edited ads are checked whole, and again by the tool before anything is sent.
    approval_input_model=MetaAdsCreateAdsRequest,
    presentation=ToolPresentation(
        icon="meta_ads",
        running_label="Creating Meta Ads",
        completed_label="Created Meta Ads",
        failed_label="Couldn't Create Meta Ads",
        approval_title="Create Meta Ads",
        approval_prompt="The agent wants to create these ads in {_account_name}.",
        approve_label="Approve & Create",
        arg_fields=(
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
                key="link", label="Website Link", editable=True, secondary=True, width="third"
            ),
            ToolFieldPresentation(
                key="call_to_action",
                label="CTA Button",
                editable=True,
                options=ALL_BUTTONS,
                secondary=True,
                width="third",
            ),
            ToolFieldPresentation(
                key="status",
                label="Status",
                editable=True,
                options=("paused", "active"),
                width="third",
            ),
            ToolFieldPresentation(key="url_tags", label="URL Tags", editable=True, secondary=True),
            ToolFieldPresentation(
                key="automatic_changes",
                label="Automatic Changes",
                editable=True,
                format="structured",
                secondary=True,
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
