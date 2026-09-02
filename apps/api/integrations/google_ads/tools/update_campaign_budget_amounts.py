# apps/api/integrations/google_ads/tools/update_campaign_budget_amounts.py

"""Approval-only Google Ads campaign budget amount update tool."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, cast

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext, ToolReturn

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
from services.integrations.context.targeted import run_context_targets
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.update_campaign_budget_amounts import (
    GoogleAdsCampaignBudgetAmountChange,
    GoogleAdsCampaignBudgetPeriod,
    update_campaign_budget_amounts,
)
from .schemas import (
    GoogleAdsCampaignBudgetAmountUpdate,
    GoogleAdsUpdateCampaignBudgetAmountsOutput,
)
from .utils import (
    GOOGLE_ADS_WRITE_BINDING,
    MAX_CAMPAIGN_BUDGET_AMOUNT_PUBLIC_RESULT_CHARS,
    RESULTS_FIELD,
    bounded_campaign_budget_amount_result,
    campaign_label_audit_evidence,
    display_campaign_budget_amount_result,
    fan_out_tool_return,
    google_ads_available,
    google_ads_client,
    login_customer_id,
)
from .utils.money import micros_to_money, money_to_micros
from .utils.mutation_evidence import (
    audit_status,
    google_ads_account_target,
    terminal_operation_detail,
)
from .verifiers import campaign_budget_reference_from_row, verify_campaign_budgets


@dataclass(frozen=True, slots=True)
class _VerifiedBudget:
    reference: GoogleAdsCampaignBudgetReference
    previous_amount_micros: int
    requested_amount_micros: int

    @property
    def change(self) -> GoogleAdsCampaignBudgetAmountChange:
        return GoogleAdsCampaignBudgetAmountChange(
            budget_id=self.reference.budget_id,
            period=cast(GoogleAdsCampaignBudgetPeriod, self.reference.period),
            previous_amount_micros=self.previous_amount_micros,
            requested_amount_micros=self.requested_amount_micros,
        )


async def google_ads_update_campaign_budget_amounts(
    ctx: RunContext[RuntimeDeps],
    updates: Annotated[
        list[GoogleAdsCampaignBudgetAmountUpdate],
        Field(min_length=1, max_length=100, description="Campaign budget amount changes."),
    ],
) -> ToolReturn[dict[str, Any]]:
    requested_micros = _validate_updates(updates)

    async def operation(
        entry: ResolvedContextEntry,
        references: Sequence[GoogleAdsCampaignBudgetReference],
    ) -> Any:
        client = None
        verified: list[_VerifiedBudget] = []
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
                _verified_budget(
                    entry,
                    reference,
                    rows[reference.budget_id],
                    requested_micros[(reference.customer_id, reference.budget_id)],
                )
                for reference in references
            ]
            pending_detail = _pending_operation_detail(entry, verified)
            return pending_detail

        async def execute() -> IntegrationAuditOutcome[GoogleAdsMutationLedger]:
            if client is None or pending_detail is None or not verified:
                raise RuntimeError("Campaign budget update preparation did not complete")
            ledger = await update_campaign_budget_amounts(
                client,
                customer_id=entry.external_id,
                login_customer_id=login_customer_id(entry),
                changes=[item.change for item in verified],
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
            tool_name="google_ads_update_campaign_budget_amounts",
            operation="update_campaign_budget_amounts",
            execute=execute,
            prepare_pending_operation=prepare_pending_operation,
        )
        return _split_result(verified, ledger)

    results = await run_context_targets(
        ctx,
        binding=GOOGLE_ADS_WRITE_BINDING,
        references=[update.budget for update in updates],
        operation=operation,
    )
    return fan_out_tool_return(results)


def _validate_updates(
    updates: Sequence[GoogleAdsCampaignBudgetAmountUpdate],
) -> dict[tuple[str, str], int]:
    if not updates:
        raise ModelRetry("Choose at least one Google Ads campaign budget.")
    if len(updates) > 100:
        raise ModelRetry("Choose at most 100 Google Ads campaign budgets per call.")
    identities = [update.budget.identity() for update in updates]
    if len(set(identities)) != len(identities):
        raise ModelRetry("Choose each Google Ads campaign budget only once.")
    return {
        (update.budget.customer_id, update.budget.budget_id): money_to_micros(update.amount)
        for update in updates
    }


def _verified_budget(
    entry: ResolvedContextEntry,
    selected: GoogleAdsCampaignBudgetReference,
    row: Mapping[str, Any],
    requested_amount_micros: int,
) -> _VerifiedBudget:
    reference = campaign_budget_reference_from_row(entry, selected, row)
    previous_amount_micros = cast(
        int,
        reference.amount_micros if reference.period == "DAILY" else reference.total_amount_micros,
    )
    return _VerifiedBudget(
        reference=reference,
        previous_amount_micros=previous_amount_micros,
        requested_amount_micros=requested_amount_micros,
    )


def _pending_operation_detail(
    entry: ResolvedContextEntry,
    verified: Sequence[_VerifiedBudget],
) -> PendingIntegrationOperationDetail:
    return PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key="campaign-budgets:update-amount",
                action="update_amount",
                entity_type="google_ads_campaign_budget",
                items=[
                    IntegrationOperationIntent(
                        fields={
                            "budget_id": item.reference.budget_id,
                            "budget_name": item.reference.label,
                            "period": str(item.reference.period),
                            "previous_amount": micros_to_money(item.previous_amount_micros),
                            "previous_amount_micros": str(item.previous_amount_micros),
                            "requested_amount": micros_to_money(item.requested_amount_micros),
                            "requested_amount_micros": str(item.requested_amount_micros),
                            "currency_code": str(item.reference.currency_code),
                            "reference_count": str(item.reference.reference_count),
                            **campaign_label_audit_evidence(item.reference.campaign_labels),
                        }
                    )
                    for item in verified
                ],
            )
        ],
    )


def _result(
    verified: Sequence[_VerifiedBudget],
    ledger: GoogleAdsMutationLedger,
) -> dict[str, Any]:
    if len(verified) != len(ledger.parents):
        raise ValueError("Google Ads returned contradictory campaign budget accounting")
    budgets = []
    for item, parent in zip(verified, ledger.parents, strict=True):
        if thaw_fields(parent.identity) != {"budget_id": item.reference.budget_id}:
            raise ValueError("Google Ads returned contradictory campaign budget accounting")
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
        reference = item.reference
        if outcome in {"updated", "already_set"}:
            field = "amount_micros" if reference.period == "DAILY" else "total_amount_micros"
            reference = reference.model_copy(update={field: item.requested_amount_micros})
        budgets.append(
            {
                "reference": reference,
                "previous_amount": micros_to_money(item.previous_amount_micros),
                "requested_amount": micros_to_money(item.requested_amount_micros),
                "previous_amount_micros": item.previous_amount_micros,
                "requested_amount_micros": item.requested_amount_micros,
                "outcome": outcome,
                "external_ref": external_ref,
                "error_code": error_code,
                "message": message,
            }
        )
    return {"budgets": budgets}


def _split_result(
    verified: Sequence[_VerifiedBudget],
    ledger: GoogleAdsMutationLedger,
) -> dict[str, Any]:
    full_result = _result(verified, ledger)
    return {
        "model_result": bounded_campaign_budget_amount_result(full_result),
        "display_result": display_campaign_budget_amount_result(full_result),
    }


DEFINITION = RuntimeToolDefinition(
    name="google_ads_update_campaign_budget_amounts",
    function=google_ads_update_campaign_budget_amounts,
    description=(
        "Set operator-selected amounts on named Google Ads campaign budgets. "
        "This tool does not recommend or choose an amount."
    ),
    provider="google_ads",
    label="Update Google Ads Campaign Budget Amounts",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=60,
    output_model=GoogleAdsUpdateCampaignBudgetAmountsOutput,
    max_public_result_chars=MAX_CAMPAIGN_BUDGET_AMOUNT_PUBLIC_RESULT_CHARS,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Updating Campaign Budget Amounts",
        completed_label="Updated Campaign Budget Amounts",
        failed_label="Couldn't Update Campaign Budget Amounts",
        approval_title="Update Google Ads Campaign Budget Amounts",
        approval_prompt=("The agent wants to change these campaign budget amounts in Google Ads."),
        approve_label="Approve & Update",
        arg_fields=(
            ToolFieldPresentation(
                key="updates",
                label="Budget Amount Updates",
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
