# apps/api/integrations/meta_ads/tools/create_ads.py

"""Approval-only tool that creates image, video, and carousel ads in existing ad sets."""

import asyncio
from collections.abc import Mapping, Sequence
from typing import Annotated, Any

from pydantic import Field, ValidationError
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
    AuditStatus,
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    PendingIntegrationOperationDetail,
)
from services.integrations.approved_display_args import approved_display_args, proposed_args
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.context.targeted import run_context_scope
from services.integrations.entity_references import resolve_runtime_references
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..client import MetaAdsClient
from ..creative_features import offered_catalogue
from ..entity_resolvers.utils import MAX_EXACT_REFERENCES
from ..operations.ad_rows import ad_row
from ..operations.create_ads import create_ads
from ..operations.plan_ads import duplicate_name, plan_ads
from ..operations.upload_media import media_upload_row
from ..references import (
    MetaAdsInstagramAccountReference,
    MetaAdsMediaReference,
    MetaAdsPageReference,
)
from ..throttle import ensure_account_available
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
    prepare,
    required_currency,
    resolve_sources,
)
from .utils.bindings import META_ADS_WRITE_BINDING, RESULTS_FIELD
from .utils.client import meta_ads_available, meta_ads_client
from .utils.mutation_evidence import (
    account_pin,
    attach_interrupted_evidence,
    audit_status,
    meta_ads_account_target,
    terminal_operation_detail,
)
from .utils.validation import validation_retry

_OPERATION = "create_ads"
_ACCOUNT_CHANGED = "The approved ad account is no longer selected. Ask for approval again."
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
    request = _request({**values, "ads": _ads_as_reviewed(ctx, ads)})
    entry = _account_entry(ctx.deps, request.account_id)
    reviewed = approved_display_args(ctx)
    # References nested in `ads` aren't re-resolved when an approval is edited, so preparation
    # re-reads every one through this account and the workspace.

    async def operation(selected: ResolvedContextEntry) -> Any:
        client: MetaAdsClient | None = None
        prepared: Prepared | None = None
        pending_detail: PendingIntegrationOperationDetail | None = None

        async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
            nonlocal client, prepared, pending_detail
            if reviewed.get("_account") != account_pin(selected):
                raise ModelRetry(_ACCOUNT_CHANGED)
            # The card can't change ad sets; media is re-read in preparation instead.
            ad_sets = [sorted(ref.adset_id for ref in design.ad_sets) for design in request.ads]
            if _proposed_ad_sets(proposed_args(ctx)) != ad_sets:
                raise ModelRetry(_AD_SETS_CHANGED)
            ensure_account_available(selected.external_id, operation=_OPERATION)
            client = await meta_ads_client(ctx, selected)
            prepared = await prepare(ctx.deps, client, selected, request, reviewed)
            pending_detail = _pending_operation_detail(selected, request, prepared)
            return pending_detail

        async def execute() -> IntegrationAuditOutcome[dict[str, Any]]:
            if client is None or prepared is None or pending_detail is None:
                raise RuntimeError("Meta Ads ad creation preparation did not complete")
            try:
                run = await create_ads(
                    client,
                    account_id=selected.external_id,
                    scope_label=selected.display_name,
                    planned=prepared.planned,
                    intent_fields=prepared.intent_fields,
                    sources=prepared.sources,
                    media=prepared.media,
                    page_id=request.page.page_id,
                    instagram_user_id=request.instagram_user_id,
                    promoted_objects=prepared.promoted_objects,
                    checked=prepared.checked,
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
                "ads": [ad_row(ad_run) for ad_run in run.ads],
                "uploads": [media_upload_row(upload) for upload in run.uploads],
                "automatic_changes": list(request.automatic_changes or ()),
                "created_off_for_ai": prepared.created_off_for_ai,
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
            tool_name="meta_ads_create_ads",
            operation=_OPERATION,
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


def _request(values: Mapping[str, Any]) -> MetaAdsCreateAdsRequest:
    """Builds the whole request, so cross-field rules run on what the model or approver sent."""
    try:
        return MetaAdsCreateAdsRequest.model_validate(values)
    except ValidationError as exc:
        raise validation_retry(exc) from None


def _ads_as_reviewed(ctx: RunContext[RuntimeDeps], ads: list[MetaAdsAdDesign]) -> list[Any]:
    """Returns the ads as the card showed them: unedited ones follow the shared settings they copy."""
    # Card edits start from `follow_shared`, so only ads left as proposed still hold copies.
    proposed = proposed_args(ctx)
    try:
        unedited = _request(proposed).ads == ads
    except ModelRetry:
        return ads
    return follow_shared(proposed) if unedited else ads


def _account_entry(deps: RuntimeDeps, account_id: str) -> ResolvedContextEntry:
    active = deps.active_context
    entries = active.compatible_entries(META_ADS_WRITE_BINDING) if active else ()
    matching = [entry for entry in entries if entry.external_id == account_id]
    if len(matching) != 1:
        raise ModelRetry(
            "The Page, ad sets, and media must belong to one Meta ad account selected in "
            "Active Context. Ask the user to select it."
        )
    return matching[0]


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
    request = _request(values)
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
        groups.append(
            IntegrationOperationIntentGroup(
                key="media:upload",
                action="upload_media",
                entity_type="meta_ads_media",
                items=[
                    IntegrationOperationIntent(
                        fields={
                            "key": f"file:{source.file.id}",
                            "file_id": str(source.file.id),
                            "revision_id": str(source.revision.id),
                            "content_hash": source.revision.content_hash,
                            "content_type": source.revision.content_type,
                            "size_bytes": source.revision.size_bytes,
                            "media_type": source.media_type,
                        }
                    )
                    for source in prepared.sources
                ],
            )
        )
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
    """Hydrates the Page, accounts, ad sets, and media, and pins the account and Files."""
    request = MetaAdsCreateAdsRequest.model_validate(args)
    entry = _account_entry(deps, request.account_id)
    # Ads follow the shared settings they copy, so a later shared edit reaches them.
    display: dict[str, Any] = {**args, "ads": follow_shared(args)}
    display["page"] = (await _hydrate(deps, "meta_ads_page", "page", [request.page]))[0]
    if request.instagram_account is not None:
        display["instagram_account"] = (
            await _hydrate(
                deps, "meta_ads_instagram_account", "instagram_account", [request.instagram_account]
            )
        )[0]
    ad_sets = list(distinct_ad_sets(request).values())
    hydrated_sets = await _hydrate(deps, "meta_ads_ad_set", "ads", ad_sets)
    library = [
        item for item in distinct_media(request).values() if isinstance(item, MetaAdsMediaReference)
    ]
    hydrated_media = await _hydrate(deps, "meta_ads_media", "ads", library) if library else []
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
        "_files": [source.approval_details() for source in sources],
        "_automatic_change_catalogue": offered_catalogue(),
        "_buttons": {"website": list(WEBSITE_BUTTONS), "app": list(APP_BUTTONS)},
    }


async def _hydrate(
    deps: RuntimeDeps, entity_kind: str, field_key: str, references: Sequence[Any]
) -> list[dict[str, Any]]:
    # A resolver takes at most 50 references at once; one call can use more media than that.
    hydrated: list[dict[str, Any]] = []
    for start in range(0, len(references), MAX_EXACT_REFERENCES):
        hydrated.extend(
            await resolve_runtime_references(
                deps,
                entity_kind=entity_kind,
                field_key=field_key,
                values=[
                    reference.model_dump(mode="json")
                    for reference in references[start : start + MAX_EXACT_REFERENCES]
                ],
            )
        )
    return hydrated


DEFINITION = RuntimeToolDefinition(
    name="meta_ads_create_ads",
    function=meta_ads_create_ads,
    description=(
        "Create up to 50 image, video, or carousel ads in existing ad sets of one Meta ad "
        "account, in one approval. Each item in ads is one design, created once in each of "
        "its ad_sets (at most 10 ad sets in all), named after the design and the ad set when "
        "it goes in several. Order: upload videos with meta_ads_upload_media and wait until "
        "they're ready; list the Pages, Instagram accounts, and media with "
        "meta_ads_list_assets; then create the ads. Workspace image Files can be passed as "
        "media directly and are uploaded with the ads. vertical_media adds a 9:16 version "
        "for Stories and Reels. page, instagram_account, link, call_to_action, url_tags, and "
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
