# apps/api/integrations/google_ads/tools/dismiss_recommendations.py

"""Approval-only Google Ads recommendation dismissal runtime tool."""

import asyncio
from collections.abc import Mapping, Sequence
from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from core.exceptions.integration import IntegrationError, IntegrationFailureDisposition
from integrations.google_ads.operations.mutation_outcomes import thaw_fields
from integrations.google_ads.recommendation_utils import (
    affected_campaign_label,
    affected_campaigns,
)
from integrations.google_ads.references import GoogleAdsRecommendationReference
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

from ..operations.dismiss_recommendations import (
    GoogleAdsRecommendationDismissOperation,
    dismiss_recommendations,
    recommendation_dismiss_failure_ledger,
)
from .schemas import GoogleAdsDismissRecommendationsOutput
from .utils import (
    GOOGLE_ADS_WRITE_BINDING,
    RESULTS_FIELD,
    google_ads_available,
    google_ads_client,
    login_customer_id,
)
from .utils.mutation_evidence import (
    audit_status,
    google_ads_account_target,
    terminal_operation_detail,
)
from .verifiers import verify_recommendations


async def google_ads_dismiss_recommendations(
    ctx: RunContext[RuntimeDeps],
    recommendations: Annotated[
        list[GoogleAdsRecommendationReference],
        Field(min_length=1, max_length=100, description="Scoped recommendations to dismiss."),
    ],
) -> dict[str, Any]:
    _validate_args(recommendations)

    async def operation(
        entry: ResolvedContextEntry,
        scoped_references: Sequence[GoogleAdsRecommendationReference],
    ) -> Any:
        selected = list(scoped_references)
        client = None
        live_rows: Mapping[str, Mapping[str, Any]] = {}
        provider_operations: list[GoogleAdsRecommendationDismissOperation] = []
        pending_detail: PendingIntegrationOperationDetail | None = None

        async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
            nonlocal client, live_rows, provider_operations, pending_detail
            client = await google_ads_client(ctx, entry)
            live_rows = await verify_recommendations(
                client,
                entry=entry,
                references=selected,
                allow_dismissed=True,
            )
            provider_operations = [
                (
                    reference.resource_name,
                    reference.recommendation_type,
                    live_rows[reference.resource_name].get("dismissed") is True,
                )
                for reference in selected
            ]
            pending_detail = _pending_operation_detail(entry, selected, live_rows=live_rows)
            return pending_detail

        async def execute() -> Any:
            if client is None or pending_detail is None:
                raise RuntimeError("Recommendation dismissal preparation did not complete")
            try:
                ledger = await dismiss_recommendations(
                    client,
                    customer_id=entry.external_id,
                    login_customer_id=login_customer_id(entry),
                    recommendations=provider_operations,
                )
            except asyncio.CancelledError as exc:
                disposition = getattr(
                    exc,
                    "failure_disposition",
                    IntegrationFailureDisposition.NOT_DISPATCHED,
                )
                exception_outcome = _exception_outcome(
                    selected,
                    live_rows,
                    pending_detail,
                    provider_operations,
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
                    selected,
                    live_rows,
                    pending_detail,
                    provider_operations,
                    exc,
                    disposition=disposition,
                )
            operation_detail = terminal_operation_detail(pending_detail, ledger)
            result = _dismiss_result(selected, live_rows, ledger)
            status = audit_status(operation_detail)
            return IntegrationAuditOutcome(
                result,
                status=status,
                external_ref=",".join(ledger.external_refs) or None,
                operation_detail=operation_detail,
                unverified_result=result if status is AuditStatus.UNVERIFIED else None,
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_ads_dismiss_recommendations",
            operation="dismiss_recommendations",
            execute=execute,
            prepare_pending_operation=prepare_pending_operation,
        )

    results = await run_context_targets(
        ctx,
        binding=GOOGLE_ADS_WRITE_BINDING,
        references=recommendations,
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


def _validate_args(recommendations: Sequence[GoogleAdsRecommendationReference]) -> None:
    if not recommendations:
        raise ModelRetry("Choose at least one Google Ads recommendation.")
    if len(recommendations) > 100:
        raise ModelRetry("Choose at most 100 Google Ads recommendations per call.")
    resource_names = [reference.resource_name for reference in recommendations]
    if len(set(resource_names)) != len(resource_names):
        raise ModelRetry("Choose each Google Ads recommendation only once.")


def _pending_operation_detail(
    entry: ResolvedContextEntry,
    references: Sequence[GoogleAdsRecommendationReference],
    *,
    live_rows: Mapping[str, Mapping[str, Any]],
) -> PendingIntegrationOperationDetail:
    return PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key="recommendations:dismiss",
                action="dismiss",
                entity_type="google_ads_recommendation",
                items=[
                    IntegrationOperationIntent(
                        fields={
                            "recommendation_resource_name": reference.resource_name,
                            "recommendation_type": reference.recommendation_type,
                            "recommendation_label": reference.label,
                            **(
                                {"campaign_label": campaign_label}
                                if (
                                    campaign_label := affected_campaign_label(
                                        live_rows[reference.resource_name]
                                    )
                                )
                                else {}
                            ),
                        }
                    )
                    for reference in references
                ],
            )
        ],
    )


def _dismiss_result(
    references: Sequence[GoogleAdsRecommendationReference],
    live_rows: Mapping[str, Mapping[str, Any]],
    ledger,
) -> dict[str, Any]:
    parents_by_name = {
        thaw_fields(parent.identity)["recommendation_resource_name"]: parent
        for parent in ledger.parents
    }
    if set(parents_by_name) != {reference.resource_name for reference in references}:
        raise ValueError("Google Ads returned contradictory recommendation accounting")
    recommendations = []
    for reference in references:
        parent = parents_by_name[reference.resource_name]
        live = live_rows[reference.resource_name]
        if parent.decision == "skipped":
            outcome = "already_dismissed"
            external_ref = reference.resource_name
            message = None
            error_code = None
        else:
            if len(parent.effects) != 1:
                raise ValueError(
                    "Google Ads recommendation accounting requires one effect per intent"
                )
            effect = parent.effects[0]
            outcome = "dismissed" if effect.outcome == "applied" else effect.outcome
            external_ref = effect.external_ref
            message = effect.message
            error_code = effect.error_code
        recommendations.append(
            {
                "recommendation_resource_name": reference.resource_name,
                "recommendation_type": str(live["type"]),
                "recommendation_label": reference.label,
                "affected_campaigns": list(affected_campaigns(live)),
                "outcome": outcome,
                "external_ref": external_ref,
                "message": message,
                "error_code": error_code,
            }
        )
    return {"recommendations": recommendations}


def _exception_outcome(
    references: Sequence[GoogleAdsRecommendationReference],
    live_rows: Mapping[str, Mapping[str, Any]],
    pending_detail: PendingIntegrationOperationDetail,
    provider_operations: Sequence[GoogleAdsRecommendationDismissOperation],
    exc: BaseException,
    *,
    disposition: IntegrationFailureDisposition,
) -> IntegrationAuditOutcome[dict[str, Any]]:
    ambiguous = disposition is IntegrationFailureDisposition.AMBIGUOUS
    error_code = exc.__class__.__name__[:100]
    raw_message = exc.user_message if isinstance(exc, IntegrationError) else str(exc)
    message = " ".join(raw_message.split())[:1000] or "Google Ads recommendation dismissal failed"
    ledger = recommendation_dismiss_failure_ledger(
        provider_operations,
        outcome="unverified" if ambiguous else "failed",
        error_code=error_code,
        message=message,
    )
    operation_detail = terminal_operation_detail(pending_detail, ledger)
    result = _dismiss_result(references, live_rows, ledger)
    status = audit_status(operation_detail)
    return IntegrationAuditOutcome(
        result,
        status=status,
        operation_detail=operation_detail,
        unverified_result=result if ambiguous else None,
    )


DEFINITION = RuntimeToolDefinition(
    name="google_ads_dismiss_recommendations",
    function=google_ads_dismiss_recommendations,
    description=(
        "Dismiss selected live Google Ads recommendations after reviewing them with "
        "google_ads_run_report. Dismissal hides Google's proposal without applying its changes."
    ),
    provider="google_ads",
    label="Dismiss Google Ads Recommendations",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=60,
    output_model=GoogleAdsDismissRecommendationsOutput,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Dismissing Google Ads Recommendations",
        completed_label="Dismissed Google Ads Recommendations",
        failed_label="Couldn't Dismiss Google Ads Recommendations",
        approval_title="Dismiss Google Ads Recommendations",
        approval_prompt=(
            "The agent wants to hide recommendations proposed by Google Ads without "
            "applying their changes."
        ),
        approve_label="Approve & Dismiss",
        arg_fields=(
            ToolFieldPresentation(
                key="recommendations",
                label="Recommendations",
                format="entity_list",
                editable=True,
                entity_kind="google_ads_recommendation",
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
