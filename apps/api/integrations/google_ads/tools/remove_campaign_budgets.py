# apps/api/integrations/google_ads/tools/remove_campaign_budgets.py

"""Approval-only Google Ads campaign budget removal tool."""

import asyncio
from collections.abc import Mapping, Sequence
from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext, ToolReturn

from core.exceptions.integration import IntegrationError, IntegrationFailureDisposition
from integrations.google_ads.operations.mutation_outcomes import (
    GoogleAdsMutationLedger,
    thaw_fields,
)
from integrations.google_ads.references import GoogleAdsCampaignBudgetReference
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
from services.integrations.context.results import split_fan_out_tool_return
from services.integrations.context.targeted import run_context_targets
from services.integrations.entity_references import resolve_runtime_references
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.remove_campaign_budgets import (
    campaign_budget_removal_failure_ledger,
    remove_campaign_budgets,
)
from .schemas import GoogleAdsRemoveCampaignBudgetsOutput
from .utils import (
    GOOGLE_ADS_WRITE_BINDING,
    MAX_CAMPAIGN_BUDGET_REMOVAL_PUBLIC_RESULT_CHARS,
    RESULTS_FIELD,
    bounded_campaign_budget_removal_result,
    campaign_label_audit_evidence,
    display_campaign_budget_removal_result,
    google_ads_available,
    google_ads_client,
    login_customer_id,
)
from .utils.mutation_evidence import (
    audit_status,
    google_ads_account_target,
    terminal_operation_detail,
)
from .verifiers import campaign_budget_reference_from_row, verify_campaign_budgets


async def google_ads_remove_campaign_budgets(
    ctx: RunContext[RuntimeDeps],
    budgets: Annotated[
        list[GoogleAdsCampaignBudgetReference],
        Field(min_length=1, max_length=50, description="Unused campaign budgets to remove."),
    ],
) -> ToolReturn[dict[str, Any]]:
    _validate_selection(budgets)

    async def operation(
        entry: ResolvedContextEntry,
        references: Sequence[GoogleAdsCampaignBudgetReference],
    ) -> Any:
        client = None
        verified: list[GoogleAdsCampaignBudgetReference] = []
        pending_detail: PendingIntegrationOperationDetail | None = None

        async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
            nonlocal client, verified, pending_detail
            client = await google_ads_client(ctx, entry)
            rows = await verify_campaign_budgets(
                client,
                entry=entry,
                budget_ids=[reference.budget_id for reference in references],
            )
            verified = [
                campaign_budget_reference_from_row(entry, reference, rows[reference.budget_id])
                for reference in references
            ]
            _require_unused_budgets(verified)
            pending_detail = _pending_operation_detail(entry, verified)
            return pending_detail

        async def execute() -> IntegrationAuditOutcome[GoogleAdsMutationLedger]:
            if client is None or pending_detail is None or not verified:
                raise RuntimeError("Campaign budget removal preparation did not complete")
            try:
                ledger = await remove_campaign_budgets(
                    client,
                    customer_id=entry.external_id,
                    login_customer_id=login_customer_id(entry),
                    budget_ids=[reference.budget_id for reference in verified],
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
            tool_name="google_ads_remove_campaign_budgets",
            operation="remove_campaign_budgets",
            execute=execute,
            prepare_pending_operation=prepare_pending_operation,
        )
        return _split_result(verified, ledger)

    results = await run_context_targets(
        ctx,
        binding=GOOGLE_ADS_WRITE_BINDING,
        references=budgets,
        operation=operation,
    )
    return split_fan_out_tool_return(results)


def _validate_selection(budgets: Sequence[GoogleAdsCampaignBudgetReference]) -> None:
    if not budgets:
        raise ModelRetry("Choose at least one Google Ads campaign budget.")
    if len(budgets) > 50:
        raise ModelRetry("Choose at most 50 Google Ads campaign budgets per call.")
    identities = [budget.identity() for budget in budgets]
    if len(set(identities)) != len(identities):
        raise ModelRetry("Choose each Google Ads campaign budget only once.")


def _require_unused_budgets(budgets: Sequence[GoogleAdsCampaignBudgetReference]) -> None:
    incomplete = [budget for budget in budgets if not budget.status]
    if incomplete:
        raise ModelRetry(
            "A selected Google Ads campaign budget has no live status. "
            "Refresh the connection and retry."
        )
    linked = [budget for budget in budgets if budget.reference_count != 0 or budget.campaign_labels]
    if not linked:
        return
    names = ", ".join(repr(budget.label) for budget in linked[:3])
    suffix = "" if len(linked) <= 3 else f" and {len(linked) - 3} more"
    raise ModelRetry(
        f"Campaign budgets {names}{suffix} are linked to campaigns and cannot be removed. "
        "Assign those campaigns to another budget, then retry."
    )


def _pending_operation_detail(
    entry: ResolvedContextEntry,
    budgets: Sequence[GoogleAdsCampaignBudgetReference],
) -> PendingIntegrationOperationDetail:
    return PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key="campaign-budgets:remove",
                action="remove",
                entity_type="google_ads_campaign_budget",
                items=[
                    IntegrationOperationIntent(fields=_budget_intent_fields(budget))
                    for budget in budgets
                ],
            )
        ],
    )


def _budget_intent_fields(reference: GoogleAdsCampaignBudgetReference) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "budget_id": reference.budget_id,
        "budget_name": reference.label,
        "budget_status": reference.status,
        "period": reference.period,
        "delivery_method": reference.delivery_method,
        "explicitly_shared": reference.explicitly_shared,
        "reference_count": reference.reference_count,
        "currency_code": reference.currency_code,
        **campaign_label_audit_evidence(
            reference.campaign_labels,
            total_count=reference.reference_count,
        ),
    }
    if reference.amount_micros is not None:
        fields["amount_micros"] = str(reference.amount_micros)
    if reference.total_amount_micros is not None:
        fields["total_amount_micros"] = str(reference.total_amount_micros)
    return fields


def _result(
    verified: Sequence[GoogleAdsCampaignBudgetReference],
    ledger: GoogleAdsMutationLedger,
) -> dict[str, Any]:
    if len(verified) != len(ledger.parents):
        raise ValueError("Google Ads returned contradictory campaign budget removal accounting")
    budgets: list[dict[str, Any]] = []
    for reference, parent in zip(verified, ledger.parents, strict=True):
        if thaw_fields(parent.identity) != {"budget_id": reference.budget_id}:
            raise ValueError("Google Ads returned contradictory campaign budget removal accounting")
        if len(parent.effects) != 1:
            raise ValueError("Google Ads campaign budget removal requires one effect per intent")
        effect = parent.effects[0]
        outcome = "removed" if effect.outcome == "applied" else effect.outcome
        budgets.append(
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
    return {"budgets": budgets}


def _split_result(
    verified: Sequence[GoogleAdsCampaignBudgetReference],
    ledger: GoogleAdsMutationLedger,
) -> dict[str, Any]:
    full_result = _result(verified, ledger)
    return {
        "model_result": bounded_campaign_budget_removal_result(full_result),
        "display_result": display_campaign_budget_removal_result(full_result),
    }


def _exception_outcome(
    verified: Sequence[GoogleAdsCampaignBudgetReference],
    pending_detail: PendingIntegrationOperationDetail,
    exc: BaseException,
    *,
    disposition: IntegrationFailureDisposition,
) -> IntegrationAuditOutcome[GoogleAdsMutationLedger]:
    ambiguous = disposition is IntegrationFailureDisposition.AMBIGUOUS
    error_code = exc.__class__.__name__[:100]
    raw_message = exc.user_message if isinstance(exc, IntegrationError) else str(exc)
    message = " ".join(raw_message.split())[:1000] or "Campaign budget removal failed"
    ledger = campaign_budget_removal_failure_ledger(
        [reference.budget_id for reference in verified],
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


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Hydrate live campaign budget state shown for approval."""
    selected_budgets = []
    for budget in args.get("budgets", []):
        if not isinstance(budget, Mapping):
            raise TypeError("Google Ads campaign budget approval arguments are invalid")
        selected_budgets.append(dict(budget))
    if not selected_budgets:
        raise RuntimeError("Google Ads campaign budget approval requires at least one budget")
    budgets = await resolve_runtime_references(
        deps,
        entity_kind="google_ads_campaign_budget",
        field_key="budgets",
        values=selected_budgets,
    )
    return {**args, "budgets": budgets}


DEFINITION = RuntimeToolDefinition(
    name="google_ads_remove_campaign_budgets",
    function=google_ads_remove_campaign_budgets,
    description=(
        "Permanently remove operator-selected Google Ads campaign budgets that have no "
        "linked campaigns. This tool does not recommend or choose a budget."
    ),
    provider="google_ads",
    label="Remove Google Ads Campaign Budgets",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=60,
    output_model=GoogleAdsRemoveCampaignBudgetsOutput,
    max_public_result_chars=MAX_CAMPAIGN_BUDGET_REMOVAL_PUBLIC_RESULT_CHARS,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    approval_display_args=_approval_display_args,
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Removing Campaign Budgets",
        completed_label="Removed Campaign Budgets",
        failed_label="Couldn't Remove Campaign Budgets",
        approval_title="Permanently Remove Google Ads Campaign Budgets",
        approval_prompt=(
            "The agent wants to permanently remove these unused campaign budgets from "
            "Google Ads. This action cannot be undone."
        ),
        approve_label="Approve & Remove",
        arg_fields=(
            ToolFieldPresentation(
                key="budgets",
                label="Unused Campaign Budgets",
                format="entity_list",
                editable=True,
                entity_kind="google_ads_campaign_budget",
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
