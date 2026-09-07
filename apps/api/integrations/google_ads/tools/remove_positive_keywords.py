# apps/api/integrations/google_ads/tools/remove_positive_keywords.py

"""Approval-only Google Ads keyword removal tool."""

import asyncio
import json
from collections.abc import Mapping, Sequence
from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext, ToolReturn

from core.exceptions.integration import IntegrationError, IntegrationFailureDisposition
from integrations.google_ads.operations.mutation_outcomes import (
    GoogleAdsMutationLedger,
    thaw_fields,
)
from integrations.google_ads.references import GoogleAdsKeywordReference
from integrations.google_ads.references.keyword import positive_keyword_state
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
from services.integrations.context.results import (
    IntegrationContextResult,
    serialize_fan_out_results,
)
from services.integrations.context.targeted import run_context_targets
from services.integrations.entity_references import resolve_runtime_references
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.remove_positive_keywords import (
    positive_keyword_removal_failure_ledger,
    remove_positive_keywords,
)
from .schemas.positive_keyword_removals import GoogleAdsRemovePositiveKeywordsOutput
from .utils import (
    GOOGLE_ADS_WRITE_BINDING,
    RESULTS_FIELD,
    fan_out_tool_return,
    google_ads_available,
    google_ads_client,
    login_customer_id,
)
from .utils.mutation_evidence import (
    audit_status,
    google_ads_account_target,
    terminal_operation_detail,
)
from .utils.positive_keyword_removal_results import (
    MAX_POSITIVE_KEYWORD_REMOVAL_PUBLIC_RESULT_CHARS,
    bounded_positive_keyword_removal_result,
    display_positive_keyword_removal_result,
)
from .verifiers import verify_positive_keywords


async def google_ads_remove_keywords(
    ctx: RunContext[RuntimeDeps],
    keywords: Annotated[
        list[GoogleAdsKeywordReference],
        Field(min_length=1, max_length=500, description="Positive keywords to permanently remove."),
    ],
) -> ToolReturn[dict[str, Any]]:
    _validate_selection(keywords)
    _preflight_call(ctx.deps, keywords)

    async def operation(
        entry: ResolvedContextEntry,
        references: Sequence[GoogleAdsKeywordReference],
    ) -> Any:
        client = None
        verified: list[GoogleAdsKeywordReference] = []
        pending_detail: PendingIntegrationOperationDetail | None = None

        async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
            nonlocal client, verified, pending_detail
            client = await google_ads_client(ctx, entry)
            verified = await verify_positive_keywords(client, entry=entry, selected=references)
            for original, current in zip(references, verified, strict=True):
                if positive_keyword_state(original) != positive_keyword_state(current):
                    raise ModelRetry("A selected keyword changed after approval. Choose it again.")
            _validate_selection(verified)
            pending_detail = _pending_operation_detail(entry, verified)
            return pending_detail

        async def execute() -> IntegrationAuditOutcome[GoogleAdsMutationLedger]:
            if client is None or pending_detail is None or not verified:
                raise RuntimeError("Keyword removal preparation did not complete")
            try:
                ledger = await remove_positive_keywords(
                    client,
                    customer_id=entry.external_id,
                    login_customer_id=login_customer_id(entry),
                    keyword_ids=[
                        (reference.ad_group_id, reference.criterion_id) for reference in verified
                    ],
                )
            except asyncio.CancelledError as exc:
                disposition = getattr(
                    exc,
                    "failure_disposition",
                    IntegrationFailureDisposition.NOT_DISPATCHED,
                )
                exception_outcome = _exception_outcome(
                    verified,
                    pending_detail,
                    exc,
                    disposition=disposition,
                )
                exc.failure_disposition = disposition
                exc.operation_detail = exception_outcome.operation_detail
                raise
            except Exception as exc:
                disposition = getattr(exc, "failure_disposition", None)
                if disposition is None:
                    disposition = IntegrationFailureDisposition.AMBIGUOUS
                return _exception_outcome(
                    verified,
                    pending_detail,
                    exc,
                    disposition=disposition,
                )
            detail = terminal_operation_detail(pending_detail, ledger)
            status = audit_status(detail)
            return IntegrationAuditOutcome(
                ledger,
                status=status,
                external_ref=",".join(ledger.external_refs) or None,
                operation_detail=detail,
                unverified_result=(
                    _split_result(verified, ledger) if status is AuditStatus.UNVERIFIED else None
                ),
            )

        ledger = await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_ads_remove_keywords",
            operation="remove_positive_keywords",
            execute=execute,
            prepare_pending_operation=prepare_pending_operation,
        )
        return _split_result(verified, ledger)

    results = await run_context_targets(
        ctx,
        binding=GOOGLE_ADS_WRITE_BINDING,
        references=keywords,
        operation=operation,
    )
    return fan_out_tool_return(results)


def _validate_selection(keywords: Sequence[GoogleAdsKeywordReference]) -> None:
    if not keywords:
        raise ModelRetry("Choose at least one Google Ads keyword.")
    if len(keywords) > 500:
        raise ModelRetry("Choose at most 500 Google Ads keywords per call.")
    identities = [keyword.identity() for keyword in keywords]
    if len(set(identities)) != len(identities):
        raise ModelRetry("Choose each Google Ads keyword only once.")
    if (
        len(json.dumps([item.model_dump(mode="json") for item in keywords], ensure_ascii=True))
        > 300_000
    ):
        raise ModelRetry(
            "The keyword removal evidence is too large. Split the request into smaller groups."
        )


def _preflight_call(deps: RuntimeDeps, keywords: Sequence[GoogleAdsKeywordReference]) -> None:
    grouped: dict[str, list[GoogleAdsKeywordReference]] = {}
    for keyword in keywords:
        grouped.setdefault(keyword.customer_id, []).append(keyword)
    entries = [
        entry
        for entry in (
            deps.active_context.compatible_entries(GOOGLE_ADS_WRITE_BINDING)
            if deps.active_context
            else ()
        )
        if entry.external_id in grouped
    ]
    if len(entries) != len(grouped) or len({entry.external_id for entry in entries}) != len(
        entries
    ):
        raise ModelRetry("Choose the keywords again from the active Google Ads accounts.")
    results = []
    for entry in entries:
        selected = grouped[entry.external_id]
        pending = _pending_operation_detail(entry, selected)
        ledger = positive_keyword_removal_failure_ledger(
            [(item.ad_group_id, item.criterion_id) for item in selected],
            outcome="unverified",
            error_code="\x00" * 100,
            message="\x00" * 500,
        )
        terminal_operation_detail(pending, ledger)
        data = display_positive_keyword_removal_result(_result(selected, ledger))
        # Reserve provider resource names and outcome labels for every selected row.
        results.append(
            IntegrationContextResult(
                entry=entry,
                status="success",
                data=data,
                error_code="\x00" * 128,
                error_message="\x00" * 1000,
            )
        )
    size = len(json.dumps({"results": serialize_fan_out_results(results)}, ensure_ascii=False))
    if size + len(keywords) * 250 > MAX_POSITIVE_KEYWORD_REMOVAL_PUBLIC_RESULT_CHARS:
        raise ModelRetry(
            "The keyword removal results are too large. Split the request into smaller groups."
        )


def _pending_operation_detail(
    entry: ResolvedContextEntry,
    keywords: Sequence[GoogleAdsKeywordReference],
) -> PendingIntegrationOperationDetail:
    return PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key="positive-keywords:remove",
                action="remove",
                entity_type="google_ads_keyword",
                items=[
                    IntegrationOperationIntent(fields=_keyword_intent_fields(keyword))
                    for keyword in keywords
                ],
            )
        ],
    )


def _keyword_intent_fields(reference: GoogleAdsKeywordReference) -> dict[str, Any]:
    return {
        "ad_group_id": reference.ad_group_id,
        "criterion_id": reference.criterion_id,
        "before": reference.model_dump(mode="json"),
        "requested": "REMOVED",
    }


def _result(
    verified: Sequence[GoogleAdsKeywordReference],
    ledger: GoogleAdsMutationLedger,
) -> dict[str, Any]:
    if len(verified) != len(ledger.parents):
        raise ValueError("Google Ads returned contradictory keyword removal accounting")
    keywords: list[dict[str, Any]] = []
    for reference, parent in zip(verified, ledger.parents, strict=True):
        if thaw_fields(parent.identity) != {
            "ad_group_id": reference.ad_group_id,
            "criterion_id": reference.criterion_id,
        }:
            raise ValueError("Google Ads returned contradictory keyword removal accounting")
        if len(parent.effects) != 1:
            raise ValueError("Google Ads keyword removal requires one effect per intent")
        effect = parent.effects[0]
        outcome = "removed" if effect.outcome == "applied" else effect.outcome
        keywords.append(
            {
                "reference": reference,
                "previous_status": reference.status,
                "resulting_status": (
                    "REMOVED"
                    if outcome == "removed"
                    else reference.status
                    if outcome == "failed"
                    else None
                ),
                "outcome": outcome,
                "external_ref": effect.external_ref,
                "error_code": effect.error_code,
                "message": effect.message,
            }
        )
    return {"keywords": keywords}


def _split_result(
    verified: Sequence[GoogleAdsKeywordReference],
    ledger: GoogleAdsMutationLedger,
) -> dict[str, Any]:
    full_result = _result(verified, ledger)
    return {
        "model_result": bounded_positive_keyword_removal_result(full_result),
        "display_result": display_positive_keyword_removal_result(full_result),
    }


def _exception_outcome(
    verified: Sequence[GoogleAdsKeywordReference],
    pending_detail: PendingIntegrationOperationDetail,
    exc: BaseException,
    *,
    disposition: IntegrationFailureDisposition,
) -> IntegrationAuditOutcome[GoogleAdsMutationLedger]:
    ambiguous = disposition is IntegrationFailureDisposition.AMBIGUOUS
    error_code = exc.__class__.__name__[:100]
    raw_message = exc.user_message if isinstance(exc, IntegrationError) else str(exc)
    message = " ".join(raw_message.split())[:1000] or "Keyword removal failed"
    ledger = positive_keyword_removal_failure_ledger(
        [(reference.ad_group_id, reference.criterion_id) for reference in verified],
        outcome="unverified" if ambiguous else "failed",
        error_code=error_code,
        message=message,
    )
    detail = terminal_operation_detail(pending_detail, ledger)
    status = audit_status(detail)
    return IntegrationAuditOutcome(
        ledger,
        status=status,
        operation_detail=detail,
        unverified_result=_split_result(verified, ledger) if ambiguous else None,
    )


def _validate_args(
    _ctx: RunContext[RuntimeDeps], keywords: Sequence[GoogleAdsKeywordReference]
) -> None:
    _validate_selection(keywords)


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Hydrates verified keyword state shown for approval."""
    selected_keywords = []
    for keyword in args.get("keywords", []):
        if not isinstance(keyword, Mapping):
            raise TypeError("Google Ads keyword approval arguments are invalid")
        selected_keywords.append(dict(keyword))
    if not selected_keywords:
        raise RuntimeError("Google Ads keyword approval requires at least one keyword")
    keywords = await resolve_runtime_references(
        deps,
        entity_kind="google_ads_keyword",
        field_key="keywords",
        values=selected_keywords,
    )
    _validate_selection([GoogleAdsKeywordReference.model_validate(item) for item in keywords])
    return {**args, "keywords": keywords}


DEFINITION = RuntimeToolDefinition(
    name="google_ads_remove_keywords",
    function=google_ads_remove_keywords,
    description=(
        "Permanently remove operator-selected positive Google Ads keywords. "
        "Removed keywords cannot be re-enabled. This tool does not choose keywords."
    ),
    provider="google_ads",
    label="Remove Google Ads Keywords",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    args_validator=_validate_args,
    timeout=60,
    output_model=GoogleAdsRemovePositiveKeywordsOutput,
    max_public_result_chars=MAX_POSITIVE_KEYWORD_REMOVAL_PUBLIC_RESULT_CHARS,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    approval_display_args=_approval_display_args,
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Removing Keywords",
        completed_label="Removed Keywords",
        failed_label="Couldn't Remove Keywords",
        approval_title="Permanently Remove Google Ads Keywords",
        approval_prompt=(
            "The agent wants to permanently remove these positive keywords from "
            "Google Ads. This action cannot be undone."
        ),
        approve_label="Approve & Remove",
        arg_fields=(
            ToolFieldPresentation(
                key="keywords",
                label="Keywords",
                format="entity_list",
                editable=True,
                entity_kind="google_ads_keyword",
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
