# apps/api/integrations/google_ads/tools/apply_recommendations.py

"""Approval-only Google Ads recommendation apply runtime tool."""

import asyncio
from collections.abc import Mapping, Sequence
from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from core.exceptions.integration import IntegrationError, IntegrationFailureDisposition
from integrations.google_ads.operations.mutation_outcomes import thaw_fields
from apps.api.integrations.google_ads.tools.utils.recommendation_utils import (
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

from ..operations.apply_recommendations import (
    GoogleAdsRecommendationApplyOperation,
    apply_recommendations,
    recommendation_failure_ledger,
)
from .schemas import (
    GoogleAdsApplyRecommendationsOutput,
    GoogleAdsRecommendationApplyParameters,
)
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

_PARAMETER_TYPES_BY_RECOMMENDATION: dict[str, frozenset[str]] = {
    "campaignBudget": frozenset(
        {"CAMPAIGN_BUDGET", "FORECASTING_CAMPAIGN_BUDGET", "MARGINAL_ROI_CAMPAIGN_BUDGET"}
    ),
    "keyword": frozenset({"KEYWORD"}),
    "targetCpaOptIn": frozenset({"TARGET_CPA_OPT_IN"}),
    "targetRoasOptIn": frozenset({"TARGET_ROAS_OPT_IN"}),
    "moveUnusedBudget": frozenset({"MOVE_UNUSED_BUDGET"}),
    "useBroadMatchKeyword": frozenset({"USE_BROAD_MATCH_KEYWORD"}),
    "raiseTargetCpaBidTooLow": frozenset({"RAISE_TARGET_CPA_BID_TOO_LOW"}),
    "forecastingSetTargetRoas": frozenset({"FORECASTING_SET_TARGET_ROAS"}),
    "raiseTargetCpa": frozenset({"RAISE_TARGET_CPA"}),
    "lowerTargetRoas": frozenset({"LOWER_TARGET_ROAS"}),
    "forecastingSetTargetCpa": frozenset({"FORECASTING_SET_TARGET_CPA"}),
    "setTargetCpa": frozenset({"SET_TARGET_CPA"}),
    "setTargetRoas": frozenset({"SET_TARGET_ROAS"}),
}


async def google_ads_apply_recommendations(
    ctx: RunContext[RuntimeDeps],
    recommendations: Annotated[
        list[GoogleAdsRecommendationReference],
        Field(min_length=1, max_length=50, description="Scoped recommendations to apply."),
    ],
    parameters: Annotated[
        list[GoogleAdsRecommendationApplyParameters] | None,
        Field(
            default=None,
            max_length=50,
            description=(
                "Optional v24 customization rows keyed by recommendation resource name. "
                "Omit this field to apply Google's proposed values."
            ),
        ),
    ] = None,
) -> dict[str, Any]:
    _validate_args(recommendations, parameters or ())
    parameters_by_name = {
        parameter.recommendation_resource_name: parameter for parameter in parameters or ()
    }

    async def operation(
        entry: ResolvedContextEntry,
        scoped_references: Sequence[GoogleAdsRecommendationReference],
    ) -> Any:
        selected = list(scoped_references)
        client = None
        live_rows: Mapping[str, Mapping[str, Any]] = {}
        provider_operations: list[GoogleAdsRecommendationApplyOperation] = []
        pending_detail: PendingIntegrationOperationDetail | None = None

        async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
            nonlocal client, live_rows, provider_operations, pending_detail
            client = await google_ads_client(ctx, entry)
            live_rows = await verify_recommendations(
                client,
                entry=entry,
                references=selected,
            )
            provider_parameters = _provider_parameters(selected, parameters_by_name, live_rows)
            provider_operations = [
                (
                    reference.resource_name,
                    reference.recommendation_type,
                    provider_parameters.get(reference.resource_name),
                )
                for reference in selected
            ]
            pending_detail = _pending_operation_detail(
                entry,
                selected,
                parameters_by_name,
                live_rows=live_rows,
            )
            return pending_detail

        async def execute() -> Any:
            if client is None or pending_detail is None:
                raise RuntimeError("Recommendation apply preparation did not complete")
            try:
                ledger = await apply_recommendations(
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
                    parameters_by_name,
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
                    parameters_by_name,
                    live_rows,
                    pending_detail,
                    provider_operations,
                    exc,
                    disposition=disposition,
                )
            operation_detail = terminal_operation_detail(pending_detail, ledger)
            result = _apply_result(selected, parameters_by_name, live_rows, ledger)
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
            tool_name="google_ads_apply_recommendations",
            operation="apply_recommendations",
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


def _validate_args(
    recommendations: Sequence[GoogleAdsRecommendationReference],
    parameters: Sequence[GoogleAdsRecommendationApplyParameters],
) -> None:
    if not recommendations:
        raise ModelRetry("Choose at least one Google Ads recommendation.")
    if len(recommendations) > 50:
        raise ModelRetry("Choose at most 50 Google Ads recommendations per call.")
    resource_names = [reference.resource_name for reference in recommendations]
    if len(set(resource_names)) != len(resource_names):
        raise ModelRetry("Choose each Google Ads recommendation only once.")
    parameter_names = [parameter.recommendation_resource_name for parameter in parameters]
    if len(set(parameter_names)) != len(parameter_names):
        raise ModelRetry("Add at most one parameter row for each Google Ads recommendation.")
    if set(parameter_names) - set(resource_names):
        raise ModelRetry(
            "Each parameter row must name one of the selected Google Ads recommendations."
        )


def _provider_parameters(
    references: Sequence[GoogleAdsRecommendationReference],
    parameters_by_name: Mapping[str, GoogleAdsRecommendationApplyParameters],
    live_rows: Mapping[str, Mapping[str, Any]],
) -> dict[str, tuple[str, dict[str, Any]]]:
    references_by_name = {reference.resource_name: reference for reference in references}
    provider_parameters: dict[str, tuple[str, dict[str, Any]]] = {}
    for resource_name, parameter in parameters_by_name.items():
        live_type = str(live_rows[resource_name].get("type", ""))
        allowed_types = _PARAMETER_TYPES_BY_RECOMMENDATION[parameter.parameter_type]
        if live_type not in allowed_types:
            reference = references_by_name[resource_name]
            raise ModelRetry(
                f"The parameters for {reference.label} do not match its live Google Ads type. "
                "Run the recommendation report again before retrying."
            )
        provider_parameters[resource_name] = _serialize_parameter(parameter)
    return provider_parameters


def _serialize_parameter(
    parameter: GoogleAdsRecommendationApplyParameters,
) -> tuple[str, dict[str, Any]]:
    values = parameter.model_dump(exclude_none=True)
    parameter_type = str(values.pop("parameter_type"))
    values.pop("recommendation_resource_name")
    field_names = {
        "new_budget_amount_micros": "newBudgetAmountMicros",
        "ad_group": "adGroup",
        "match_type": "matchType",
        "cpc_bid_micros": "cpcBidMicros",
        "target_cpa_micros": "targetCpaMicros",
        "new_campaign_budget_amount_micros": "newCampaignBudgetAmountMicros",
        "target_roas": "targetRoas",
        "budget_micros_to_move": "budgetMicrosToMove",
        "target_multiplier": "targetMultiplier",
        "campaign_budget_amount_micros": "campaignBudgetAmountMicros",
        "target_cpa_multiplier": "targetCpaMultiplier",
        "target_roas_multiplier": "targetRoasMultiplier",
    }
    micros_fields = {
        "new_budget_amount_micros",
        "cpc_bid_micros",
        "target_cpa_micros",
        "new_campaign_budget_amount_micros",
        "budget_micros_to_move",
        "campaign_budget_amount_micros",
    }
    payload = {
        field_names[key]: str(value) if key in micros_fields else value
        for key, value in values.items()
    }
    return parameter_type, payload


def _pending_operation_detail(
    entry: ResolvedContextEntry,
    references: Sequence[GoogleAdsRecommendationReference],
    parameters_by_name: Mapping[str, GoogleAdsRecommendationApplyParameters],
    *,
    live_rows: Mapping[str, Mapping[str, Any]],
) -> PendingIntegrationOperationDetail:
    return PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key="recommendations:apply",
                action="apply",
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
                            "parameters": (
                                parameters_by_name[reference.resource_name].model_dump(
                                    mode="json",
                                    exclude={"recommendation_resource_name"},
                                    exclude_none=True,
                                )
                                if reference.resource_name in parameters_by_name
                                else None
                            ),
                        }
                    )
                    for reference in references
                ],
            )
        ],
    )


def _apply_result(
    references: Sequence[GoogleAdsRecommendationReference],
    parameters_by_name: Mapping[str, GoogleAdsRecommendationApplyParameters],
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
        if len(parent.effects) != 1:
            raise ValueError("Google Ads recommendation accounting requires one effect per intent")
        effect = parent.effects[0]
        live = live_rows[reference.resource_name]
        recommendations.append(
            {
                "recommendation_resource_name": reference.resource_name,
                "recommendation_type": str(live["type"]),
                "recommendation_label": reference.label,
                "affected_campaigns": list(affected_campaigns(live)),
                "requested_parameters": (
                    parameters_by_name[reference.resource_name].model_dump(mode="json")
                    if reference.resource_name in parameters_by_name
                    else None
                ),
                "impact": _impact(live.get("impact")),
                "outcome": effect.outcome,
                "external_ref": effect.external_ref,
                "message": effect.message,
                "error_code": effect.error_code,
            }
        )
    return {"recommendations": recommendations}


def _exception_outcome(
    references: Sequence[GoogleAdsRecommendationReference],
    parameters_by_name: Mapping[str, GoogleAdsRecommendationApplyParameters],
    live_rows: Mapping[str, Mapping[str, Any]],
    pending_detail: PendingIntegrationOperationDetail,
    provider_operations: Sequence[GoogleAdsRecommendationApplyOperation],
    exc: BaseException,
    *,
    disposition: IntegrationFailureDisposition,
) -> IntegrationAuditOutcome[dict[str, Any]]:
    ambiguous = disposition is IntegrationFailureDisposition.AMBIGUOUS
    error_code = exc.__class__.__name__[:100]
    raw_message = exc.user_message if isinstance(exc, IntegrationError) else str(exc)
    message = " ".join(raw_message.split())[:1000] or "Google Ads recommendation apply failed"
    ledger = recommendation_failure_ledger(
        provider_operations,
        outcome="unverified" if ambiguous else "failed",
        error_code=error_code,
        message=message,
    )
    operation_detail = terminal_operation_detail(pending_detail, ledger)
    result = _apply_result(references, parameters_by_name, live_rows, ledger)
    status = audit_status(operation_detail)
    return IntegrationAuditOutcome(
        result,
        status=status,
        operation_detail=operation_detail,
        unverified_result=result if ambiguous else None,
    )


def _impact(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    impact = {}
    for provider_key, public_key in (
        ("baseMetrics", "base_metrics"),
        ("potentialMetrics", "potential_metrics"),
    ):
        metrics = value.get(provider_key)
        if not isinstance(metrics, Mapping):
            continue
        impact[public_key] = {
            public_name: metrics[provider_name]
            for provider_name, public_name in (
                ("impressions", "impressions"),
                ("clicks", "clicks"),
                ("costMicros", "cost_micros"),
                ("conversions", "conversions"),
                ("conversionsValue", "conversions_value"),
                ("videoViews", "video_views"),
            )
            if provider_name in metrics
        }
    return impact or None


DEFINITION = RuntimeToolDefinition(
    name="google_ads_apply_recommendations",
    function=google_ads_apply_recommendations,
    description=(
        "Apply selected live Google Ads recommendations after reviewing them with "
        "google_ads_run_report. Optional typed parameters customize supported budget, "
        "keyword, CPA, or ROAS proposals; omit parameters to apply Google's proposed values."
    ),
    provider="google_ads",
    label="Apply Google Ads Recommendations",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=60,
    output_model=GoogleAdsApplyRecommendationsOutput,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Applying Google Ads Recommendations",
        completed_label="Applied Google Ads Recommendations",
        failed_label="Couldn't Apply Google Ads Recommendations",
        approval_title="Apply Google Ads Recommendations",
        approval_prompt="The agent wants to apply recommendations proposed by Google Ads.",
        approve_label="Approve & Apply",
        arg_fields=(
            ToolFieldPresentation(
                key="recommendations",
                label="Recommendations",
                format="entity_list",
                editable=True,
                entity_kind="google_ads_recommendation",
            ),
            ToolFieldPresentation(
                key="parameters",
                label="Custom parameters",
                format="list",
                editable=True,
                secondary=True,
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
