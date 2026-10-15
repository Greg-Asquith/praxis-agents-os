# apps/api/integrations/meta_ads/tools/copy_ads.py

"""Approval-only tool that copies existing ads, creative and all, into other ad sets."""

from collections.abc import Mapping, Sequence
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

from ..client import MetaAdsClient
from ..creative_features import change_labels, has_ai_generated
from ..operations.copy_ads import (
    COPY_GROUP,
    OPERATION,
    SOURCE_FIELDS,
    PlannedCopy,
    SourceAd,
    copy_ads,
    copy_row,
    intent_fields,
    source_ad,
)
from ..operations.create_objects import read_created
from ..operations.list_objects import read_objects_by_id
from ..operations.plan_ads import ad_set_problem
from .schemas.copies import MAX_COPIES, MetaAdsAdCopy, MetaAdsCopyAdsOutput, MetaAdsCopyAdsRequest
from .schemas.objects import MetaAdsObject
from .utils.ad_preparation import (
    existing_ads,
    hydrate_references,
    over_capacity,
    required_currency,
)
from .utils.bindings import META_ADS_WRITE_BINDING, RESULTS_FIELD
from .utils.client import meta_ads_available, meta_ads_client_for_principal
from .utils.create_operation import run_create_tool, selected_account, validated
from .utils.mutation_evidence import (
    account_pin,
    meta_ads_account_target,
)

_SOURCE_ADDED = "A copy of an ad that wasn't proposed was added. Ask the agent to prepare it again."

type AdCopies = Annotated[
    list[MetaAdsAdCopy],
    Field(
        min_length=1,
        max_length=MAX_COPIES,
        description="Each item copies one existing ad into one other ad set.",
    ),
]


async def meta_ads_copy_ads(ctx: RunContext[RuntimeDeps], copies: AdCopies) -> dict[str, Any]:
    request = validated(MetaAdsCopyAdsRequest, {"copies": copies})
    return await run_create_tool(
        ctx,
        _account_entry(ctx.deps, request.account_id),
        tool_name="meta_ads_copy_ads",
        operation=OPERATION,
        # The card can change targets, and drop or add copies, but only of proposed ads.
        check_edits=lambda proposed: _check_sources_proposed(proposed, request),
        prepare=lambda client, entry: _prepare(client, entry, request),
        pending_detail=_pending_operation_detail,
        run=lambda client, entry, planned: copy_ads(
            client,
            account_id=entry.external_id,
            planned=planned,
            intent_fields={plan.index: intent_fields(plan) for plan in planned},
        ),
        result=lambda run, entry, _planned: {
            "account_id": entry.external_id,
            "copies": [copy_row(copy_run) for copy_run in run.copies],
        },
    )


def _account_entry(deps: RuntimeDeps, account_id: str) -> ResolvedContextEntry:
    return selected_account(
        deps,
        account_id,
        "The ads and ad sets must belong to one Meta ad account selected in Active "
        "Context. Ask the user to select it.",
    )


def _check_sources_proposed(proposed: Mapping[str, Any], request: MetaAdsCopyAdsRequest) -> None:
    """Refuses a copy whose source ad the agent didn't propose; targets are re-read live."""
    copies = proposed.get("copies")
    proposed_ads = {
        str(item["ad"].get("ad_id"))
        for item in (copies if isinstance(copies, list) else ())
        if isinstance(item, Mapping) and isinstance(item.get("ad"), Mapping)
    }
    if {item.ad.ad_id for item in request.copies} - proposed_ads:
        raise ModelRetry(_SOURCE_ADDED)


async def _prepare(
    client: MetaAdsClient, entry: ResolvedContextEntry, request: MetaAdsCopyAdsRequest
) -> list[PlannedCopy]:
    """Re-reads the source ads and target ad sets, then plans and checks every copy."""
    sources = await _read_sources(client, entry, request)
    targets = await _live_ad_sets(client, entry, request)
    planned = [
        _plan(index, item, sources[item.ad.ad_id], targets[item.ad_set.adset_id])
        for index, item in enumerate(request.copies)
    ]
    await _check_capacity(client, entry, planned)
    return planned


async def _read_sources(
    client: MetaAdsClient, entry: ResolvedContextEntry, request: MetaAdsCopyAdsRequest
) -> dict[str, SourceAd]:
    ids = sorted({item.ad.ad_id for item in request.copies})
    rows = await read_created(
        client,
        account_id=entry.external_id,
        edge="ads",
        object_ids=ids,
        fields=SOURCE_FIELDS,
        operation=OPERATION,
    )
    if set(ids) - set(rows):
        raise ModelRetry("Some ads to copy are no longer in this ad account. Choose them again.")
    sources = {ad_id: source_ad(row) for ad_id, row in rows.items()}
    if unnamed := [ad_id for ad_id, source in sources.items() if not source.name.strip()]:
        raise ModelRetry(f"Ad {unnamed[0]} has no name, so its copy couldn't be found again.")
    return sources


async def _live_ad_sets(
    client: MetaAdsClient, entry: ResolvedContextEntry, request: MetaAdsCopyAdsRequest
) -> dict[str, MetaAdsObject]:
    ids = sorted({item.ad_set.adset_id for item in request.copies})
    live = await read_objects_by_id(
        client,
        account_id=entry.external_id,
        object_type="adset",
        object_ids=ids,
        currency=required_currency(entry),
    )
    if set(ids) - set(live):
        raise ModelRetry("Some ad sets are no longer in this ad account. Choose them again.")
    for ad_set in live.values():
        if problem := ad_set_problem(ad_set):
            raise ModelRetry(f"{ad_set.name or ad_set.id}: {problem}")
    return live


def _plan(index: int, item: MetaAdsAdCopy, source: SourceAd, target: MetaAdsObject) -> PlannedCopy:
    if source.adset_id == target.id:
        raise ModelRetry(f"{source.name} is already in {target.name or target.id}.")
    # Meta asks for ads with AI-generated changes to be previewed before they run.
    paused_for_ai = has_ai_generated(source.changes)
    return PlannedCopy(
        index=index,
        key=item.key,
        source=source,
        adset_id=target.id,
        adset_name=target.name,
        name=item.name or source.name,
        status="paused" if paused_for_ai else item.status,
        paused_for_ai=paused_for_ai,
    )


async def _check_capacity(
    client: MetaAdsClient, entry: ResolvedContextEntry, planned: Sequence[PlannedCopy]
) -> None:
    """Keeps each ad set within Meta's 50 ads, and the names a copy has unique in it.

    A copy keeps its source's name until it is renamed, and a lost reply is found by
    that name, so both names must be free in the target ad set.
    """
    counts, names = await existing_ads(client, entry, sorted({plan.adset_id for plan in planned}))
    for plan in planned:
        counts[plan.adset_id] += 1
    over_capacity(counts, {plan.adset_id: plan.adset_name or plan.adset_id for plan in planned})
    for plan in planned:
        taken = names[plan.adset_id]
        wanted = {plan.source.name.casefold(), plan.name.casefold()}
        if clash := sorted(taken & wanted):
            raise ModelRetry(
                f"An ad called {clash[0]} is already in {plan.adset_name or plan.adset_id}, "
                "or another copy there uses it. Give the copy a different name, or choose "
                "another ad set."
            )
        taken.update(wanted)


def _pending_operation_detail(
    entry: ResolvedContextEntry, planned: Sequence[PlannedCopy]
) -> PendingIntegrationOperationDetail:
    return PendingIntegrationOperationDetail(
        target=meta_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key=COPY_GROUP,
                action="copy_ad",
                entity_type="meta_ads_ad",
                items=[IntegrationOperationIntent(fields=intent_fields(plan)) for plan in planned],
            )
        ],
    )


async def _validate_args(ctx: RunContext[RuntimeDeps], **values: Any) -> None:
    request = validated(MetaAdsCopyAdsRequest, values)
    _account_entry(ctx.deps, request.account_id)


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Reads each source ad's creative and hydrates the ad sets, and pins the account."""
    request = MetaAdsCopyAdsRequest.model_validate(args)
    entry = _account_entry(deps, request.account_id)
    ad_sets = list({item.ad_set.adset_id: item.ad_set for item in request.copies}.values())
    hydrated_sets = await hydrate_references(deps, "meta_ads_ad_set", "copies", ad_sets)
    client = await meta_ads_client_for_principal(
        deps.db, actor=deps.user, workspace=deps.workspace, entry=entry
    )
    rows = await read_created(
        client,
        account_id=entry.external_id,
        edge="ads",
        object_ids=sorted({item.ad.ad_id for item in request.copies}),
        fields=SOURCE_FIELDS,
        operation=OPERATION,
    )
    return {
        **args,
        "_account": account_pin(entry),
        "_account_name": entry.display_name[:500],
        "_currency": required_currency(entry),
        "_ad_sets": {item["adset_id"]: item for item in hydrated_sets},
        "_sources": {ad_id: _source_display(source_ad(row)) for ad_id, row in rows.items()},
    }


def _source_display(source: SourceAd) -> dict[str, Any]:
    media_type = source.media_key.split(":", 1)[0] if source.media_key else None
    return {
        "name": source.name,
        "adset_id": source.adset_id,
        "format": source.format,
        "excerpt": source.excerpt,
        "media": {"key": source.media_key, "media_type": media_type} if source.media_key else None,
        "automatic_changes": change_labels(source.changes),
        "ai_generated": has_ai_generated(source.changes),
    }


DEFINITION = RuntimeToolDefinition(
    name="meta_ads_copy_ads",
    function=meta_ads_copy_ads,
    description=(
        "Copy up to 50 existing ads into other ad sets of the same Meta ad account, in one "
        "approval, for example to roll a winning ad out to more audiences (at most 10 target "
        "ad sets). A copy keeps its source ad's creative exactly: media, text, link, button, "
        "and automatic changes. To change any of those, create new ads with "
        "meta_ads_create_ads instead. The operator can change each copy's target ad set, name, "
        "and status on the approval card, drop copies, and add copies of the same ads. Find ads and ad sets with meta_ads_list_objects. Each "
        "copy keeps the source's name unless name is set, and must have a name not already "
        "used in its ad set. Copies are paused unless status is active; active copies run and "
        "spend once Meta approves them. A source with an AI-generated change on is always "
        "copied paused. Each result reports Meta's review status; turn paused copies on with "
        "meta_ads_update_status once approved."
    ),
    provider="meta_ads",
    label="Copy Meta Ads",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=300,
    args_validator=_validate_args,
    output_model=MetaAdsCopyAdsOutput,
    integration_binding=META_ADS_WRITE_BINDING,
    availability_check=meta_ads_available,
    approval_display_args=_approval_display_args,
    approval_input_model=MetaAdsCopyAdsRequest,
    presentation=ToolPresentation(
        icon="meta_ads",
        running_label="Copying Meta Ads",
        completed_label="Copied Meta Ads",
        failed_label="Couldn't Copy Meta Ads",
        approval_title="Copy Meta Ads",
        approval_prompt="The agent wants to copy these ads in {_account_name}.",
        approve_label="Approve & Copy",
        arg_fields=(
            ToolFieldPresentation(
                key="copies",
                label="Copies",
                editable=True,
                format="structured",
                entity_kinds=("meta_ads_ad_set",),
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
