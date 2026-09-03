# apps/api/integrations/google_ads/tools/update_positive_keyword_status.py

"""Approval-only Google Ads positive-keyword status update tool."""

import asyncio
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import ModelRetry, RunContext, ToolReturn

from core.exceptions.integration import IntegrationError, IntegrationFailureDisposition
from integrations.google_ads.operations.mutation_outcomes import (
    GoogleAdsMutationLedger,
    thaw_fields,
)
from integrations.google_ads.operations.update_positive_keyword_status import (
    GoogleAdsPositiveKeywordStatus,
    GoogleAdsPositiveKeywordStatusChange,
    positive_keyword_status_failure_ledger,
    update_positive_keyword_status,
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
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.targeted import run_context_targets
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from .schemas import GoogleAdsUpdatePositiveKeywordStatusOutput
from .utils import (
    GOOGLE_ADS_WRITE_BINDING,
    MAX_POSITIVE_KEYWORD_STATUS_PUBLIC_RESULT_CHARS,
    RESULTS_FIELD,
    bounded_positive_keyword_status_result,
    display_positive_keyword_status_result,
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
from .verifiers import verify_positive_keywords

type RequestedKeywordStatus = Literal["ENABLED", "PAUSED"]
type KeywordStatusRequests = Mapping[tuple[str, str, str], RequestedKeywordStatus]


class GoogleAdsKeywordStatusSelection(BaseModel):
    """Operator-editable status paired positionally with a locked keyword reference."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: RequestedKeywordStatus


async def google_ads_update_keyword_status(
    ctx: RunContext[RuntimeDeps],
    keywords: Annotated[
        list[GoogleAdsKeywordReference],
        Field(min_length=1, max_length=500, description="Positive keywords to update."),
    ],
    statuses: Annotated[
        list[GoogleAdsKeywordStatusSelection],
        Field(
            min_length=1,
            max_length=500,
            description="Requested status for each keyword, in the same order.",
        ),
    ],
) -> ToolReturn[dict[str, Any]]:
    requested_statuses = _validate_updates(keywords, statuses)

    async def operation(
        entry: ResolvedContextEntry,
        references: Sequence[GoogleAdsKeywordReference],
    ) -> Any:
        client = None
        live_references: list[GoogleAdsKeywordReference] = []
        pending_detail: PendingIntegrationOperationDetail | None = None

        async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
            nonlocal client, live_references, pending_detail
            client = await google_ads_client(ctx, entry)
            live_references = await verify_positive_keywords(
                client,
                entry=entry,
                selected=references,
            )
            pending_detail = _pending_operation_detail(
                entry,
                live_references,
                requested_statuses,
            )
            return pending_detail

        async def execute() -> IntegrationAuditOutcome[GoogleAdsMutationLedger]:
            if client is None or pending_detail is None or not live_references:
                raise RuntimeError("Positive keyword status update preparation did not complete")
            changes = _changes(live_references, requested_statuses)
            try:
                ledger = await update_positive_keyword_status(
                    client,
                    customer_id=entry.external_id,
                    login_customer_id=login_customer_id(entry),
                    changes=changes,
                )
            except asyncio.CancelledError as exc:
                disposition = getattr(
                    exc,
                    "failure_disposition",
                    IntegrationFailureDisposition.NOT_DISPATCHED,
                )
                exception_outcome = _exception_outcome(
                    live_references,
                    requested_statuses,
                    pending_detail,
                    exc,
                    disposition=disposition,
                )
                exc.failure_disposition = disposition
                exc.operation_detail = exception_outcome.operation_detail
                raise
            except Exception as exc:
                disposition = getattr(exc, "failure_disposition", None)
                return _exception_outcome(
                    live_references,
                    requested_statuses,
                    pending_detail,
                    exc,
                    disposition=disposition or IntegrationFailureDisposition.AMBIGUOUS,
                )
            detail = terminal_operation_detail(pending_detail, ledger)
            terminal_status = audit_status(detail)
            return IntegrationAuditOutcome(
                ledger,
                status=terminal_status,
                external_ref=",".join(ledger.external_refs) or None,
                operation_detail=detail,
                unverified_result=(
                    _split_result(live_references, requested_statuses, ledger)
                    if terminal_status is AuditStatus.UNVERIFIED
                    else None
                ),
            )

        ledger = await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_ads_update_keyword_status",
            operation="update_positive_keyword_status",
            execute=execute,
            prepare_pending_operation=prepare_pending_operation,
        )
        return _split_result(live_references, requested_statuses, ledger)

    results = await run_context_targets(
        ctx,
        binding=GOOGLE_ADS_WRITE_BINDING,
        references=keywords,
        operation=operation,
    )
    return fan_out_tool_return(results)


def _validate_updates(
    keywords: Sequence[GoogleAdsKeywordReference],
    statuses: Sequence[GoogleAdsKeywordStatusSelection],
) -> dict[tuple[str, str, str], RequestedKeywordStatus]:
    identities = [keyword.identity() for keyword in keywords]
    if not keywords:
        raise ModelRetry("Choose at least one Google Ads keyword.")
    if len(keywords) > 500:
        raise ModelRetry("Choose at most 500 Google Ads keywords per call.")
    if len(identities) != len(set(identities)):
        raise ModelRetry("Choose each Google Ads keyword only once.")
    if len(statuses) != len(keywords):
        raise ModelRetry("Provide one requested status for each selected Google Ads keyword.")
    return {
        (keyword.customer_id, keyword.ad_group_id, keyword.criterion_id): selection.status
        for keyword, selection in zip(keywords, statuses, strict=True)
    }


def _validate_status_args(
    _ctx: RunContext[RuntimeDeps],
    keywords: Sequence[GoogleAdsKeywordReference],
    statuses: Sequence[GoogleAdsKeywordStatusSelection],
) -> None:
    """Reject inconsistent model output before an approval request is created."""

    _validate_updates(keywords, statuses)


def _changes(
    references: Sequence[GoogleAdsKeywordReference],
    statuses: KeywordStatusRequests,
) -> list[GoogleAdsPositiveKeywordStatusChange]:
    return [
        GoogleAdsPositiveKeywordStatusChange(
            ad_group_id=reference.ad_group_id,
            criterion_id=reference.criterion_id,
            previous_status=cast(GoogleAdsPositiveKeywordStatus, reference.status),
            requested_status=statuses[
                (reference.customer_id, reference.ad_group_id, reference.criterion_id)
            ],
        )
        for reference in references
    ]


def _pending_operation_detail(
    entry: ResolvedContextEntry,
    references: Sequence[GoogleAdsKeywordReference],
    statuses: KeywordStatusRequests,
) -> PendingIntegrationOperationDetail:
    return PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key="positive-keywords:update-status",
                action="update_status",
                entity_type="google_ads_keyword",
                items=[
                    IntegrationOperationIntent(
                        fields={
                            "campaign_id": reference.campaign_id,
                            "ad_group_id": reference.ad_group_id,
                            "criterion_id": reference.criterion_id,
                            "text": reference.text,
                            "match_type": reference.match_type,
                            "previous_status": reference.status,
                            "requested_status": statuses[
                                (
                                    reference.customer_id,
                                    reference.ad_group_id,
                                    reference.criterion_id,
                                )
                            ],
                        }
                    )
                    for reference in references
                ],
            )
        ],
    )


def _split_result(
    references: Sequence[GoogleAdsKeywordReference],
    statuses: KeywordStatusRequests,
    ledger: GoogleAdsMutationLedger,
) -> dict[str, Any]:
    rows = _result_rows(references, statuses, ledger)
    return {
        "model_result": bounded_positive_keyword_status_result(rows),
        "display_result": display_positive_keyword_status_result(rows),
    }


def _result_rows(
    references: Sequence[GoogleAdsKeywordReference],
    statuses: KeywordStatusRequests,
    ledger: GoogleAdsMutationLedger,
) -> list[dict[str, Any]]:
    if len(references) != len(ledger.parents):
        raise ValueError("Google Ads returned contradictory keyword status accounting")
    rows: list[dict[str, Any]] = []
    for reference, parent in zip(references, ledger.parents, strict=True):
        requested_status = statuses[
            (reference.customer_id, reference.ad_group_id, reference.criterion_id)
        ]
        expected_identity = {
            "ad_group_id": reference.ad_group_id,
            "criterion_id": reference.criterion_id,
        }
        if thaw_fields(parent.identity) != expected_identity:
            raise ValueError("Google Ads returned contradictory keyword status accounting")
        if parent.decision == "skipped":
            outcome = "already_set"
            external_ref = ledger.skipped_external_ref(parent)
            error_code = message = None
        else:
            effect = parent.effects[0]
            outcome = "updated" if effect.outcome == "applied" else effect.outcome
            external_ref = effect.external_ref
            error_code = effect.error_code
            message = effect.message
        current = (
            reference.model_copy(update={"status": requested_status})
            if outcome
            in {
                "updated",
                "already_set",
            }
            else reference
        )
        rows.append(
            {
                "keyword": current,
                "previous_status": reference.status,
                "requested_status": requested_status,
                "outcome": outcome,
                "external_ref": external_ref,
                "error_code": error_code,
                "message": message,
            }
        )
    return rows


def _exception_outcome(
    references: Sequence[GoogleAdsKeywordReference],
    statuses: KeywordStatusRequests,
    pending_detail: PendingIntegrationOperationDetail,
    exc: BaseException,
    *,
    disposition: IntegrationFailureDisposition,
) -> IntegrationAuditOutcome[GoogleAdsMutationLedger]:
    ambiguous = disposition is IntegrationFailureDisposition.AMBIGUOUS
    raw_message = exc.user_message if isinstance(exc, IntegrationError) else str(exc)
    ledger = positive_keyword_status_failure_ledger(
        _changes(references, statuses),
        outcome="unverified" if ambiguous else "failed",
        error_code=exc.__class__.__name__[:100],
        message=" ".join(raw_message.split())[:1000] or "Positive keyword status update failed",
    )
    detail = terminal_operation_detail(pending_detail, ledger)
    terminal_status = audit_status(detail)
    return IntegrationAuditOutcome(
        ledger,
        status=terminal_status,
        operation_detail=detail,
        unverified_result=(_split_result(references, statuses, ledger) if ambiguous else None),
    )


DEFINITION = RuntimeToolDefinition(
    name="google_ads_update_keyword_status",
    function=google_ads_update_keyword_status,
    description=(
        "Set operator-selected positive Google Ads keywords to enabled or paused. "
        "This tool does not recommend or choose keywords."
    ),
    provider="google_ads",
    label="Update Google Ads Keyword Status",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    args_validator=_validate_status_args,
    timeout=60,
    output_model=GoogleAdsUpdatePositiveKeywordStatusOutput,
    max_public_result_chars=MAX_POSITIVE_KEYWORD_STATUS_PUBLIC_RESULT_CHARS,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Updating Keyword Status",
        completed_label="Updated Keyword Status",
        failed_label="Couldn't Update Keyword Status",
        approval_title="Update Google Ads Keyword Status",
        approval_prompt="The agent wants to change these keyword statuses in Google Ads.",
        approve_label="Approve & Update",
        arg_fields=(
            ToolFieldPresentation(
                key="keywords",
                label="Keywords",
                format="entity_list",
                entity_kind="google_ads_keyword",
            ),
            ToolFieldPresentation(
                key="statuses",
                label="Keyword Statuses",
                format="records",
                editable=True,
                min_rows=1,
                columns=(
                    ToolFieldColumn(
                        key="status",
                        label="Status",
                        options=("ENABLED", "PAUSED"),
                        required=True,
                    ),
                ),
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
