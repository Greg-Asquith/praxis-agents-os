# apps/api/integrations/meta_ads/tools/copy_ads.py

"""Approval-only tool that copies existing ads, creative and all, into other ad sets."""

import asyncio
from collections.abc import Mapping, Sequence
from typing import Annotated, Any

from pydantic import Field, ValidationError
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
    AuditStatus,
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    PendingIntegrationOperationDetail,
)
from services.integrations.approved_display_args import approved_display_args, proposed_args
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.context.targeted import run_context_scope
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

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
from ..throttle import ensure_account_available
from .schemas.copies import MAX_COPIES, MetaAdsAdCopy, MetaAdsCopyAdsOutput, MetaAdsCopyAdsRequest
from .schemas.objects import MetaAdsObject
from .utils.ad_preparation import (
    existing_ads,
    hydrate_references,
    over_capacity,
    required_currency,
)
from .utils.bindings import META_ADS_WRITE_BINDING, RESULTS_FIELD
from .utils.client import meta_ads_available, meta_ads_client, meta_ads_client_for_principal
from .utils.mutation_evidence import (
    account_pin,
    attach_interrupted_evidence,
    audit_status,
    meta_ads_account_target,
    terminal_operation_detail,
)
from .utils.validation import validation_retry

_ACCOUNT_CHANGED = "The approved ad account is no longer selected. Ask for approval again."
_COPIES_CHANGED = (
    "The ads or ad sets changed after approval. Ask the agent to prepare the copies again."
)

type AdCopies = Annotated[
    list[MetaAdsAdCopy],
    Field(
        min_length=1,
        max_length=MAX_COPIES,
        description="Each item copies one existing ad into one other ad set.",
    ),
]


async def meta_ads_copy_ads(ctx: RunContext[RuntimeDeps], copies: AdCopies) -> dict[str, Any]:
    request = _request({"copies": copies})
    entry = _account_entry(ctx.deps, request.account_id)
    reviewed = approved_display_args(ctx)

    async def operation(selected: ResolvedContextEntry) -> Any:
        client: MetaAdsClient | None = None
        planned: list[PlannedCopy] = []
        pending_detail: PendingIntegrationOperationDetail | None = None

        async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
            nonlocal client, planned, pending_detail
            if reviewed.get("_account") != account_pin(selected):
                raise ModelRetry(_ACCOUNT_CHANGED)
            # The card edits names and statuses only; sources and targets stay as proposed.
            if _proposed_keys(proposed_args(ctx)) != [item.key for item in request.copies]:
                raise ModelRetry(_COPIES_CHANGED)
            ensure_account_available(selected.external_id, operation=OPERATION)
            client = await meta_ads_client(ctx, selected)
            planned = await _prepare(client, selected, request)
            pending_detail = _pending_operation_detail(selected, planned)
            return pending_detail

        async def execute() -> IntegrationAuditOutcome[dict[str, Any]]:
            if client is None or pending_detail is None:
                raise RuntimeError("Meta Ads ad copy preparation did not complete")
            try:
                run = await copy_ads(
                    client,
                    account_id=selected.external_id,
                    planned=planned,
                    intent_fields={plan.index: intent_fields(plan) for plan in planned},
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
                "copies": [copy_row(copy_run) for copy_run in run.copies],
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
            tool_name="meta_ads_copy_ads",
            operation=OPERATION,
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


def _request(values: Mapping[str, Any]) -> MetaAdsCopyAdsRequest:
    try:
        return MetaAdsCopyAdsRequest.model_validate(values)
    except ValidationError as exc:
        raise validation_retry(exc) from None


def _account_entry(deps: RuntimeDeps, account_id: str) -> ResolvedContextEntry:
    active = deps.active_context
    entries = active.compatible_entries(META_ADS_WRITE_BINDING) if active else ()
    matching = [entry for entry in entries if entry.external_id == account_id]
    if len(matching) != 1:
        raise ModelRetry(
            "The ads and ad sets must belong to one Meta ad account selected in Active "
            "Context. Ask the user to select it."
        )
    return matching[0]


def _proposed_keys(values: Mapping[str, Any]) -> list[str]:
    """Reads only the source ad and target ad set IDs from the proposal."""
    copies = values.get("copies")
    return [
        f"{_mapping(item.get('ad')).get('ad_id')}:{_mapping(item.get('ad_set')).get('adset_id')}"
        for item in (copies if isinstance(copies, list) else ())
        if isinstance(item, Mapping)
    ]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


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
    request = _request(values)
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
        "meta_ads_create_ads instead. Find ads and ad sets with meta_ads_list_objects. Each "
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
            ToolFieldPresentation(key="copies", label="Copies", editable=True, format="structured"),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
