# apps/api/integrations/google_ads/tools/update_positive_keywords.py

"""Approval-only Google Ads positive-keyword patch tool."""

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import Field, ValidationError
from pydantic_ai import ModelRetry, RunContext, ToolReturn

from core.exceptions.integration import IntegrationError, IntegrationFailureDisposition
from integrations.google_ads.operations.list_ad_groups import list_ad_groups
from integrations.google_ads.operations.mutation_outcomes import (
    GoogleAdsMutationLedger,
    thaw_fields,
)
from integrations.google_ads.operations.update_positive_keywords import (
    GoogleAdsPositiveKeywordUpdate,
    positive_keyword_update_failure_ledger,
    positive_keyword_update_preflight_ledger,
    update_positive_keywords,
    validate_positive_keyword_url_update,
)
from integrations.google_ads.positive_keyword_fields import (
    POSITIVE_KEYWORD_FIELD_BY_PATCH,
    POSITIVE_KEYWORD_FIELD_BY_PROVIDER,
    POSITIVE_KEYWORD_FIELDS,
)
from integrations.google_ads.references import GoogleAdsKeywordReference
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_EXTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_EXTERNAL_WRITE,
    TOOL_POLICY_APPROVAL,
    RuntimeToolDefinition,
    ToolFieldColumn,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.audit_events import (
    AuditStatus,
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    PendingIntegrationOperationDetail,
)
from services.audit_events.integration_operation_detail import (
    MAX_INTEGRATION_OPERATION_DETAIL_BYTES,
)
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import (
    IntegrationContextResult,
    serialize_fan_out_results,
)
from services.integrations.context.targeted import run_context_targets
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from .schemas import GoogleAdsPositiveKeywordPatch, GoogleAdsUpdatePositiveKeywordsOutput
from .schemas.positive_keywords import money_bid_to_micros
from .utils import (
    GOOGLE_ADS_WRITE_BINDING,
    MAX_POSITIVE_KEYWORD_UPDATE_PUBLIC_RESULT_CHARS,
    RESULTS_FIELD,
    bounded_positive_keyword_update_result,
    display_positive_keyword_update_result,
    fan_out_tool_return,
    google_ads_available,
    google_ads_client,
    login_customer_id,
)
from .utils.money import micros_to_money
from .utils.mutation_evidence import (
    audit_status,
    google_ads_account_target,
    terminal_operation_detail,
)
from .utils.positive_keyword_update_results import positive_keyword_update_result_upper_bound
from .verifiers import verify_positive_keywords

_PATCH_FIELDS = tuple(field.patch_name for field in POSITIVE_KEYWORD_FIELDS)
_PATCH_TO_PROVIDER = {field.patch_name: field.provider_name for field in POSITIVE_KEYWORD_FIELDS}
_PROVIDER_TO_JSON = {field.provider_name: field.json_name for field in POSITIVE_KEYWORD_FIELDS}
_BID_FIELDS = {"bid_modifier", "cpc_bid"}
_MAX_PATCH_EVIDENCE_CHARS = 300_000


@dataclass(frozen=True, slots=True)
class _BidContext:
    campaign_id: str
    strategy: str
    channel: str
    ad_group_type: str
    custom_bid_dimension: str


async def google_ads_update_keywords(
    ctx: RunContext[RuntimeDeps],
    keywords: Annotated[
        list[GoogleAdsKeywordReference],
        Field(min_length=1, max_length=500, description="Positive keywords to update."),
    ],
    patches: Annotated[
        list[GoogleAdsPositiveKeywordPatch],
        Field(min_length=1, max_length=500, description="One ordered patch per keyword."),
    ],
) -> ToolReturn[dict[str, Any]]:
    requested_patches = _validate_updates(keywords, patches)
    result_budgets = _preflight_call(ctx.deps, keywords, requested_patches)

    async def operation(
        entry: ResolvedContextEntry,
        references: Sequence[GoogleAdsKeywordReference],
    ) -> Any:
        client = None
        live_references: list[GoogleAdsKeywordReference] = []
        changes: list[GoogleAdsPositiveKeywordUpdate] = []
        pending_detail: PendingIntegrationOperationDetail | None = None

        async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
            nonlocal client, live_references, changes, pending_detail
            client = await google_ads_client(ctx, entry)
            live_references = await verify_positive_keywords(
                client, entry=entry, selected=references
            )
            changes = _changes(live_references, requested_patches)
            _validate_url_dependencies(live_references, changes)
            await _validate_bid_compatibility(client, entry, live_references, requested_patches)
            pending_detail = _pending_operation_detail(entry, live_references, changes)
            _validate_pre_dispatch_bounds(
                entry,
                live_references,
                changes,
                pending_detail,
                public_result_chars=result_budgets[entry.external_id],
            )
            return pending_detail

        async def execute() -> IntegrationAuditOutcome[GoogleAdsMutationLedger]:
            if client is None or pending_detail is None or not changes:
                raise RuntimeError("Positive keyword update preparation did not complete")
            try:
                ledger = await update_positive_keywords(
                    client,
                    customer_id=entry.external_id,
                    login_customer_id=login_customer_id(entry),
                    changes=changes,
                )
            except asyncio.CancelledError as exc:
                disposition = getattr(
                    exc, "failure_disposition", IntegrationFailureDisposition.NOT_DISPATCHED
                )
                outcome = _exception_outcome(
                    entry, live_references, changes, pending_detail, exc, disposition=disposition
                )
                exc.failure_disposition = disposition
                exc.operation_detail = outcome.operation_detail
                raise
            except Exception as exc:
                return _exception_outcome(
                    entry,
                    live_references,
                    changes,
                    pending_detail,
                    exc,
                    disposition=getattr(exc, "failure_disposition", None)
                    or IntegrationFailureDisposition.AMBIGUOUS,
                )
            detail = terminal_operation_detail(
                pending_detail,
                ledger,
                identity_keys=("ad_group_id", "criterion_id"),
            )
            status = audit_status(detail)
            return IntegrationAuditOutcome(
                ledger,
                status=status,
                external_ref=",".join(ledger.external_refs) or None,
                operation_detail=detail,
                unverified_result=(
                    _split_result(entry, live_references, changes, ledger)
                    if status is AuditStatus.UNVERIFIED
                    else None
                ),
            )

        ledger = await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_ads_update_keywords",
            operation="update_positive_keywords",
            execute=execute,
            prepare_pending_operation=prepare_pending_operation,
        )
        return _split_result(entry, live_references, changes, ledger)

    results = await run_context_targets(
        ctx,
        binding=GOOGLE_ADS_WRITE_BINDING,
        references=keywords,
        operation=operation,
    )
    return fan_out_tool_return(results)


def _preflight_call(
    deps: RuntimeDeps,
    keywords: Sequence[GoogleAdsKeywordReference],
    patches: Mapping[tuple[str, str, str], GoogleAdsPositiveKeywordPatch],
) -> dict[str, int]:
    """Reserves every account envelope and row budget before the first mutation."""
    grouped: dict[str, list[GoogleAdsKeywordReference]] = {}
    for keyword in keywords:
        grouped.setdefault(keyword.customer_id, []).append(keyword)
    compatible = (
        deps.active_context.compatible_entries(GOOGLE_ADS_WRITE_BINDING)
        if deps.active_context
        else ()
    )
    entries = [entry for entry in compatible if entry.external_id in grouped]
    if len(entries) != len(grouped) or len({entry.external_id for entry in entries}) != len(
        entries
    ):
        raise ModelRetry("Choose the keywords again from the active Google Ads accounts.")
    envelopes = serialize_fan_out_results(
        [
            IntegrationContextResult(
                entry=entry, status="success", error_code="\x00" * 128, error_message="\x00" * 1000
            )
            for entry in entries
        ]
    )
    envelope_chars = len(
        json.dumps({"results": envelopes}, ensure_ascii=False, separators=(",", ":"))
    )
    available = MAX_POSITIVE_KEYWORD_UPDATE_PUBLIC_RESULT_CHARS - envelope_chars
    budgets = {
        entry.external_id: available * len(grouped[entry.external_id]) // len(keywords)
        for entry in entries
    }
    for entry in entries:
        references = grouped[entry.external_id]
        changes = _changes(references, patches)
        pending = _pending_operation_detail(entry, references, changes)
        _validate_pre_dispatch_bounds(
            entry, references, changes, pending, public_result_chars=budgets[entry.external_id]
        )
    return budgets


def _validate_updates(
    keywords: Sequence[GoogleAdsKeywordReference],
    patches: Sequence[GoogleAdsPositiveKeywordPatch],
) -> dict[tuple[str, str, str], GoogleAdsPositiveKeywordPatch]:
    if not keywords:
        raise ModelRetry("Choose at least one Google Ads keyword.")
    if len(keywords) > 500:
        raise ModelRetry("Choose at most 500 Google Ads keywords per call.")
    identities = [keyword.identity() for keyword in keywords]
    if len(identities) != len(set(identities)):
        raise ModelRetry("Choose each Google Ads keyword only once.")
    if len(patches) != len(keywords):
        raise ModelRetry("Provide one ordered patch for each selected Google Ads keyword.")
    evidence_chars = sum(
        len(json.dumps(patch.model_dump(mode="json", exclude_unset=True), separators=(",", ":")))
        for patch in patches
    )
    if evidence_chars > _MAX_PATCH_EVIDENCE_CHARS:
        raise ModelRetry(
            "The keyword changes are too large to retain exact approval evidence. "
            "Split the request into smaller groups."
        )
    return {
        (keyword.customer_id, keyword.ad_group_id, keyword.criterion_id): patch
        for keyword, patch in zip(keywords, patches, strict=True)
    }


def _validate_patch_args(
    _ctx: RunContext[RuntimeDeps],
    keywords: Sequence[GoogleAdsKeywordReference],
    patches: Sequence[GoogleAdsPositiveKeywordPatch],
) -> None:
    _validate_updates(keywords, patches)


def _changes(
    references: Sequence[GoogleAdsKeywordReference],
    patches: Mapping[tuple[str, str, str], GoogleAdsPositiveKeywordPatch],
) -> list[GoogleAdsPositiveKeywordUpdate]:
    changes: list[GoogleAdsPositiveKeywordUpdate] = []
    for reference in references:
        patch = patches[(reference.customer_id, reference.ad_group_id, reference.criterion_id)]
        previous = _provider_state(reference)
        requested_fields = tuple(
            _PATCH_TO_PROVIDER[field] for field in _PATCH_FIELDS if field in patch.model_fields_set
        )
        patch_values = patch.model_dump(exclude_unset=True)
        requested = {
            _PATCH_TO_PROVIDER[field]: _provider_value(field, patch_values[field])
            for field in _PATCH_FIELDS
            if field in patch.model_fields_set
        }
        changes.append(
            GoogleAdsPositiveKeywordUpdate(
                ad_group_id=reference.ad_group_id,
                criterion_id=reference.criterion_id,
                previous=previous,
                requested=requested,
                requested_fields=requested_fields,
            )
        )
    return changes


def _provider_value(field: str, value: Any) -> Any:
    if POSITIVE_KEYWORD_FIELD_BY_PATCH[field].value_family == "money":
        return (
            money_bid_to_micros(value, label=field.replace("_", " ").upper())
            if value is not None
            else None
        )
    if field == "url_custom_parameters":
        return [{"key": key, "value": item} for key, item in sorted(value.items())]
    return value


def _provider_state(reference: GoogleAdsKeywordReference) -> dict[str, Any]:
    return {
        "status": reference.status,
        "bid_modifier": reference.bid_modifier,
        "cpc_bid_micros": reference.cpc_bid_micros,
        "final_urls": list(reference.final_urls),
        "final_mobile_urls": list(reference.final_mobile_urls),
        "final_url_suffix": reference.final_url_suffix,
        "tracking_url_template": reference.tracking_url_template,
        "url_custom_parameters": [
            item.model_dump(mode="json")
            for item in sorted(reference.url_custom_parameters, key=lambda value: value.key)
        ],
    }


def _after_state(change: GoogleAdsPositiveKeywordUpdate) -> dict[str, Any]:
    return {**change.previous, **change.requested}


def _validate_url_dependencies(
    references: Sequence[GoogleAdsKeywordReference],
    changes: Sequence[GoogleAdsPositiveKeywordUpdate],
) -> None:
    for reference, change in zip(references, changes, strict=True):
        try:
            validate_positive_keyword_url_update(change)
        except ValueError as exc:
            raise ModelRetry(f'Keyword "{reference.text}": {exc}') from exc


async def _validate_bid_compatibility(
    client: Any,
    entry: ResolvedContextEntry,
    references: Sequence[GoogleAdsKeywordReference],
    patches: Mapping[tuple[str, str, str], GoogleAdsPositiveKeywordPatch],
) -> None:
    relevant = [
        reference
        for reference in references
        if any(
            field
            in patches[
                (reference.customer_id, reference.ad_group_id, reference.criterion_id)
            ].model_fields_set
            and getattr(
                patches[(reference.customer_id, reference.ad_group_id, reference.criterion_id)],
                field,
            )
            is not None
            for field in _BID_FIELDS
        )
    ]
    if not relevant:
        return
    contexts: dict[str, _BidContext] = {}
    ids = sorted({reference.ad_group_id for reference in relevant})
    for start in range(0, len(ids), 100):
        batch = ids[start : start + 100]
        rows = await list_ad_groups(
            client,
            customer_id=entry.external_id,
            login_customer_id=login_customer_id(entry),
            ad_group_ids=batch,
            limit=len(batch),
            exclude_removed=True,
        )
        for row in rows:
            campaign = row.get("campaign")
            ad_group = row.get("adGroup")
            if not isinstance(campaign, Mapping) or not isinstance(ad_group, Mapping):
                continue
            ad_group_id = str(ad_group.get("id", ""))
            contexts[ad_group_id] = _BidContext(
                campaign_id=str(campaign.get("id", "")),
                strategy=str(campaign.get("biddingStrategyType", "")),
                channel=str(campaign.get("advertisingChannelType", "")),
                ad_group_type=str(ad_group.get("type", "")),
                custom_bid_dimension=str(ad_group.get("displayCustomBidDimension", "")),
            )
    for reference in relevant:
        context = contexts.get(reference.ad_group_id)
        if context is None:
            raise ModelRetry(
                "A selected Google Ads ad group changed or is unavailable. "
                "Choose the keywords again."
            )
        if context.campaign_id != reference.campaign_id:
            raise ModelRetry(
                "A selected Google Ads ad group changed campaigns. Choose the keywords again."
            )
        patch = patches[(reference.customer_id, reference.ad_group_id, reference.criterion_id)]
        for field in _BID_FIELDS.intersection(patch.model_fields_set):
            if getattr(patch, field) is not None and not _bid_is_compatible(field, context):
                raise ModelRetry(
                    f'Keyword "{reference.text}" cannot use {field.replace("_", " ")} '
                    "with its live "
                    f"{context.strategy or 'unknown'} bidding strategy, "
                    f"{context.channel or 'unknown'} channel, "
                    f"{context.ad_group_type or 'unknown'} ad-group type, and "
                    f"{context.custom_bid_dimension or 'unknown'} custom bid dimension. "
                    "Clear that bid or choose a compatible keyword."
                )


def _bid_is_compatible(field: str, context: _BidContext) -> bool:
    if field == "cpc_bid":
        return context.strategy == "MANUAL_CPC" and (
            (context.channel == "SEARCH" and context.ad_group_type == "SEARCH_STANDARD")
            or (
                context.channel == "DISPLAY"
                and context.ad_group_type == "DISPLAY_STANDARD"
                and context.custom_bid_dimension == "KEYWORD"
            )
        )
    if field == "bid_modifier":
        return (
            context.channel == "DISPLAY"
            and context.ad_group_type == "DISPLAY_STANDARD"
            and context.custom_bid_dimension != "KEYWORD"
        )
    return False


def _pending_operation_detail(
    entry: ResolvedContextEntry,
    references: Sequence[GoogleAdsKeywordReference],
    changes: Sequence[GoogleAdsPositiveKeywordUpdate],
) -> PendingIntegrationOperationDetail:
    try:
        return _build_pending_operation_detail(entry, references, changes)
    except ValidationError as exc:
        raise ModelRetry(
            "The keyword changes are too large to retain exact audit evidence. "
            "Split the request into smaller groups."
        ) from exc


def _build_pending_operation_detail(
    entry: ResolvedContextEntry,
    references: Sequence[GoogleAdsKeywordReference],
    changes: Sequence[GoogleAdsPositiveKeywordUpdate],
) -> PendingIntegrationOperationDetail:
    detail = PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key="positive-keywords:update",
                action="update",
                entity_type="google_ads_keyword",
                items=[
                    IntegrationOperationIntent(
                        fields={
                            "campaign_id": reference.campaign_id,
                            "ad_group_id": reference.ad_group_id,
                            "criterion_id": reference.criterion_id,
                            "text": reference.text,
                            "match_type": reference.match_type,
                            "before": _display_state(change.previous),
                            "after": _display_state(_after_state(change)),
                            "requested_fields": [
                                _provider_to_patch(field) for field in change.requested_fields
                            ],
                            "update_mask": ",".join(
                                _PROVIDER_TO_JSON[field] for field in change.requested_fields
                            ),
                        }
                    )
                    for reference, change in zip(references, changes, strict=True)
                ],
            )
        ],
    )
    serialized_size = len(
        json.dumps(
            detail.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
        ).encode()
    )
    if serialized_size > MAX_INTEGRATION_OPERATION_DETAIL_BYTES - 100_000:
        raise ModelRetry(
            "The keyword changes are too large to retain exact audit evidence. "
            "Split the request into smaller groups."
        )
    return detail


def _validate_pre_dispatch_bounds(
    entry: ResolvedContextEntry,
    references: Sequence[GoogleAdsKeywordReference],
    changes: Sequence[GoogleAdsPositiveKeywordUpdate],
    pending_detail: PendingIntegrationOperationDetail,
    *,
    public_result_chars: int = MAX_POSITIVE_KEYWORD_UPDATE_PUBLIC_RESULT_CHARS,
) -> None:
    """Proves every permitted terminal audit and transcript outcome fits."""
    try:
        variants = []
        for outcome in ("applied", "failed", "unverified"):
            ledger = positive_keyword_update_preflight_ledger(
                changes,
                customer_id=entry.external_id,
                outcome=outcome,
            )
            terminal_operation_detail(
                pending_detail,
                ledger,
                identity_keys=("ad_group_id", "criterion_id"),
            )
            variants.append(_result_rows(references, changes, ledger))
        if (
            positive_keyword_update_result_upper_bound(
                variants, currency_code=_currency_code(entry)
            )
            > public_result_chars
        ):
            raise ValueError("Positive keyword transcript result would exceed its reserved budget")
    except (ValidationError, ValueError) as exc:
        raise ModelRetry(
            "The keyword changes are too large to retain complete audit and result evidence. "
            "Split the request into smaller groups."
        ) from exc


def _provider_to_patch(field: str) -> str:
    return POSITIVE_KEYWORD_FIELD_BY_PROVIDER[field].patch_name


def _display_state(state: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": state["status"],
        "bid_modifier": state["bid_modifier"],
        "cpc_bid": micros_to_money(state["cpc_bid_micros"])
        if state["cpc_bid_micros"] is not None
        else None,
        "final_urls": state["final_urls"],
        "final_mobile_urls": state["final_mobile_urls"],
        "final_url_suffix": state["final_url_suffix"],
        "tracking_url_template": state["tracking_url_template"],
        "url_custom_parameters": state["url_custom_parameters"],
    }


def _split_result(
    entry: ResolvedContextEntry,
    references: Sequence[GoogleAdsKeywordReference],
    changes: Sequence[GoogleAdsPositiveKeywordUpdate],
    ledger: GoogleAdsMutationLedger,
) -> dict[str, Any]:
    rows = _result_rows(references, changes, ledger)
    currency_code = _currency_code(entry)
    return {
        "model_result": bounded_positive_keyword_update_result(rows, currency_code=currency_code),
        "display_result": display_positive_keyword_update_result(rows, currency_code=currency_code),
    }


def _result_rows(
    references: Sequence[GoogleAdsKeywordReference],
    changes: Sequence[GoogleAdsPositiveKeywordUpdate],
    ledger: GoogleAdsMutationLedger,
) -> list[dict[str, Any]]:
    if len(references) != len(changes) or len(references) != len(ledger.parents):
        raise ValueError("Google Ads returned contradictory keyword update accounting")
    rows: list[dict[str, Any]] = []
    for reference, change, parent in zip(references, changes, ledger.parents, strict=True):
        identity = {"ad_group_id": reference.ad_group_id, "criterion_id": reference.criterion_id}
        if thaw_fields(parent.identity) != identity:
            raise ValueError("Google Ads returned contradictory keyword update accounting")
        if parent.decision == "skipped":
            outcome = "already_set"
            external_ref = ledger.skipped_external_ref(parent)
            error_code = message = None
        else:
            effect = parent.effects[0]
            outcome = "updated" if effect.outcome == "applied" else effect.outcome
            external_ref, error_code, message = (
                effect.external_ref,
                effect.error_code,
                effect.message,
            )
        after = _after_state(change)
        current = (
            GoogleAdsKeywordReference.model_validate(
                {**reference.model_dump(mode="python"), **after}
            )
            if outcome in {"updated", "already_set"}
            else reference
        )
        rows.append(
            {
                "keyword": current,
                "before": _display_state(change.previous),
                "requested": _display_state(after),
                "requested_fields": [
                    _provider_to_patch(field) for field in change.requested_fields
                ],
                "update_mask": ",".join(
                    _PROVIDER_TO_JSON[field] for field in change.requested_fields
                ),
                "outcome": outcome,
                "external_ref": external_ref,
                "error_code": error_code,
                "message": message,
            }
        )
    return rows


def _exception_outcome(
    entry: ResolvedContextEntry,
    references: Sequence[GoogleAdsKeywordReference],
    changes: Sequence[GoogleAdsPositiveKeywordUpdate],
    pending_detail: PendingIntegrationOperationDetail,
    exc: BaseException,
    *,
    disposition: IntegrationFailureDisposition,
) -> IntegrationAuditOutcome[GoogleAdsMutationLedger]:
    ambiguous = disposition is IntegrationFailureDisposition.AMBIGUOUS
    raw_message = exc.user_message if isinstance(exc, IntegrationError) else str(exc)
    ledger = positive_keyword_update_failure_ledger(
        changes,
        outcome="unverified" if ambiguous else "failed",
        error_code=exc.__class__.__name__[:100],
        message=" ".join(raw_message.split())[:1000] or "Positive keyword update failed",
    )
    detail = terminal_operation_detail(
        pending_detail,
        ledger,
        identity_keys=("ad_group_id", "criterion_id"),
    )
    return IntegrationAuditOutcome(
        ledger,
        status=audit_status(detail),
        operation_detail=detail,
        unverified_result=(
            _split_result(entry, references, changes, ledger) if ambiguous else None
        ),
    )


def _currency_code(entry: ResolvedContextEntry) -> str:
    currency_code = str(entry.permissions_metadata.get("currency_code", "")).strip()
    if not currency_code:
        raise ValueError("Google Ads positive keyword result requires an account currency")
    return currency_code


def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Adds trusted account context and render scalar clears as editable blanks."""
    raw_patches = args.get("patches")
    if not isinstance(raw_patches, list):
        return args
    display_patches = [
        {
            key: ""
            if value is None
            and key not in {"final_urls", "final_mobile_urls", "url_custom_parameters"}
            else value
            for key, value in patch.items()
        }
        if isinstance(patch, Mapping)
        else patch
        for patch in raw_patches
    ]
    selected = args.get("keywords")
    customer_ids = {
        str(value.get("customer_id"))
        for value in selected
        if isinstance(selected, list) and isinstance(value, Mapping)
    }
    entries = (
        deps.active_context.compatible_entries(GOOGLE_ADS_WRITE_BINDING)
        if deps.active_context
        else ()
    )
    accounts = [
        {
            "customer_id": entry.external_id,
            "label": entry.display_name,
            "currency_code": str(entry.permissions_metadata["currency_code"]).strip(),
        }
        for entry in entries
        if entry.external_id in customer_ids
        and entry.write_allowed
        and isinstance(entry.permissions_metadata.get("currency_code"), str)
        and str(entry.permissions_metadata["currency_code"]).strip()
    ]
    if customer_ids and {account["customer_id"] for account in accounts} != customer_ids:
        raise RuntimeError("Google Ads positive keyword approval requires account currencies")
    return {**args, "patches": display_patches, "_account_currencies": accounts}


DEFINITION = RuntimeToolDefinition(
    name="google_ads_update_keywords",
    function=google_ads_update_keywords,
    description=(
        "Patch operator-selected mutable fields on existing positive Google Ads keywords. "
        "Keyword text and match type are immutable: to change match type, pause the old keyword, "
        "confirm that update, then create the replacement in a separate approval. "
        "If creation fails, "
        "the old keyword remains paused."
    ),
    provider="google_ads",
    label="Update Google Ads Keywords",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    args_validator=_validate_patch_args,
    approval_display_args=_approval_display_args,
    timeout=60,
    output_model=GoogleAdsUpdatePositiveKeywordsOutput,
    max_public_result_chars=MAX_POSITIVE_KEYWORD_UPDATE_PUBLIC_RESULT_CHARS,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Updating Keywords",
        completed_label="Updated Keywords",
        failed_label="Couldn't Update Keywords",
        approval_title="Update Google Ads Keywords",
        approval_prompt="The agent wants to change these keyword settings in Google Ads.",
        approve_label="Approve & Update",
        arg_fields=(
            ToolFieldPresentation(
                key="keywords",
                label="Keywords",
                format="entity_list",
                entity_kind="google_ads_keyword",
            ),
            ToolFieldPresentation(
                key="patches",
                label="Keyword Changes",
                format="records",
                editable=True,
                min_rows=1,
                columns=(
                    ToolFieldColumn(key="status", label="Status", options=("ENABLED", "PAUSED")),
                    ToolFieldColumn(
                        key="bid_modifier",
                        label="Bid adjustment",
                        format="number",
                        secondary=True,
                    ),
                    ToolFieldColumn(key="cpc_bid", label="CPC bid", secondary=True),
                    ToolFieldColumn(
                        key="final_urls", label="Final URLs", format="list", secondary=True
                    ),
                    ToolFieldColumn(
                        key="final_mobile_urls",
                        label="Mobile URLs",
                        format="list",
                        secondary=True,
                    ),
                    ToolFieldColumn(
                        key="final_url_suffix", label="Final URL suffix", secondary=True
                    ),
                    ToolFieldColumn(
                        key="tracking_url_template", label="Tracking template", secondary=True
                    ),
                    ToolFieldColumn(
                        key="url_custom_parameters",
                        label="URL parameters",
                        format="keyvalue",
                        secondary=True,
                        max_entries=8,
                    ),
                ),
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
