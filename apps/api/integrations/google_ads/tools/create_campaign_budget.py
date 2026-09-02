# apps/api/integrations/google_ads/tools/create_campaign_budget.py

"""Approval-only Google Ads campaign budget creation tool."""

import asyncio
from typing import Annotated, Any, Literal

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from core.exceptions.integration import IntegrationError, IntegrationFailureDisposition
from integrations.google_ads.operations.mutation_outcomes import GoogleAdsMutationLedger
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
from services.integrations.context.fan_out import run_context_fan_out
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.create_campaign_budget import (
    campaign_budget_creation_failure_ledger,
    create_campaign_budget,
)
from .schemas import GoogleAdsCampaignBudgetAmount, GoogleAdsCreateCampaignBudgetOutput
from .schemas.campaign_budgets import GoogleAdsDailyBudgetAmount
from .utils import (
    GOOGLE_ADS_WRITE_BINDING,
    RESULTS_FIELD,
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


async def google_ads_create_campaign_budget(
    ctx: RunContext[RuntimeDeps],
    name: Annotated[str, Field(min_length=1, max_length=255)],
    amount: GoogleAdsCampaignBudgetAmount,
    explicitly_shared: bool,
    delivery_method: Literal["STANDARD", "ACCELERATED"],
) -> dict[str, Any]:
    normalized_name, period, amount_micros = _validated_create_input(
        name,
        amount,
        explicitly_shared=explicitly_shared,
        delivery_method=delivery_method,
    )

    async def operation(entry: ResolvedContextEntry) -> Any:
        currency_code = str(entry.permissions_metadata.get("currency_code", "")).strip()
        if not currency_code:
            raise ModelRetry(
                "The selected Google Ads account has no currency information. Refresh the connection and retry."
            )
        canonical_amount = micros_to_money(amount_micros)
        pending_detail = _pending_operation_detail(
            entry,
            name=normalized_name,
            period=period,
            amount=canonical_amount,
            amount_micros=amount_micros,
            currency_code=currency_code,
            explicitly_shared=explicitly_shared,
            delivery_method=delivery_method,
        )

        async def execute() -> Any:
            client = await google_ads_client(ctx, entry)
            try:
                ledger = await create_campaign_budget(
                    client,
                    customer_id=entry.external_id,
                    login_customer_id=login_customer_id(entry),
                    name=normalized_name,
                    period=period,
                    amount_micros=amount_micros,
                    explicitly_shared=explicitly_shared,
                    delivery_method=delivery_method,
                )
            except asyncio.CancelledError as exc:
                disposition = getattr(
                    exc,
                    "failure_disposition",
                    IntegrationFailureDisposition.NOT_DISPATCHED,
                )
                exception_outcome = _exception_outcome(
                    entry,
                    pending_detail,
                    exc,
                    name=normalized_name,
                    period=period,
                    amount=canonical_amount,
                    amount_micros=amount_micros,
                    currency_code=currency_code,
                    explicitly_shared=explicitly_shared,
                    delivery_method=delivery_method,
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
                    entry,
                    pending_detail,
                    exc,
                    name=normalized_name,
                    period=period,
                    amount=canonical_amount,
                    amount_micros=amount_micros,
                    currency_code=currency_code,
                    explicitly_shared=explicitly_shared,
                    delivery_method=delivery_method,
                    disposition=disposition,
                )
            detail = terminal_operation_detail(pending_detail, ledger)
            status = audit_status(detail)
            return IntegrationAuditOutcome(
                ledger,
                status=status,
                external_ref=ledger.external_refs[0] if ledger.external_refs else None,
                operation_detail=detail,
                unverified_result=(
                    _result(
                        entry,
                        ledger,
                        name=normalized_name,
                        period=period,
                        amount=canonical_amount,
                        amount_micros=amount_micros,
                        currency_code=currency_code,
                        explicitly_shared=explicitly_shared,
                        delivery_method=delivery_method,
                    )
                    if status is AuditStatus.UNVERIFIED
                    else None
                ),
            )

        ledger = await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_ads_create_campaign_budget",
            operation="create_campaign_budget",
            execute=execute,
            pending_operation_detail=pending_detail,
        )
        return _result(
            entry,
            ledger,
            name=normalized_name,
            period=period,
            amount=canonical_amount,
            amount_micros=amount_micros,
            currency_code=currency_code,
            explicitly_shared=explicitly_shared,
            delivery_method=delivery_method,
        )

    results = await run_context_fan_out(ctx, binding=GOOGLE_ADS_WRITE_BINDING, operation=operation)
    return {"results": serialize_fan_out_results(results)}


def _validate_create_args(
    _ctx: RunContext[RuntimeDeps],
    name: str,
    amount: GoogleAdsCampaignBudgetAmount,
    explicitly_shared: bool,
    delivery_method: Literal["STANDARD", "ACCELERATED"],
) -> None:
    """Reject invalid create combinations before approval is requested."""
    _validated_create_input(
        name,
        amount,
        explicitly_shared=explicitly_shared,
        delivery_method=delivery_method,
    )


def _validated_create_input(
    name: str,
    amount: GoogleAdsCampaignBudgetAmount,
    *,
    explicitly_shared: bool,
    delivery_method: Literal["STANDARD", "ACCELERATED"],
) -> tuple[str, Literal["DAILY", "CUSTOM_PERIOD"], int]:
    normalized_name = " ".join(name.split())
    if not normalized_name:
        raise ModelRetry("Enter a campaign budget name.")
    if len(normalized_name.encode("utf-8")) > 255:
        raise ModelRetry("Campaign budget names must be 255 UTF-8 bytes or fewer.")
    period: Literal["DAILY", "CUSTOM_PERIOD"] = (
        "DAILY" if isinstance(amount, GoogleAdsDailyBudgetAmount) else "CUSTOM_PERIOD"
    )
    if period == "CUSTOM_PERIOD" and explicitly_shared:
        raise ModelRetry("Campaign total budgets can't be shared across campaigns.")
    if period == "CUSTOM_PERIOD" and delivery_method == "ACCELERATED":
        raise ModelRetry("Campaign total budgets require standard delivery.")
    amount_text = (
        amount.daily_amount
        if isinstance(amount, GoogleAdsDailyBudgetAmount)
        else amount.total_amount
    )
    amount_micros = money_to_micros(amount_text)
    return normalized_name, period, amount_micros


def _pending_operation_detail(
    entry: ResolvedContextEntry, **fields: Any
) -> PendingIntegrationOperationDetail:
    intent_fields = {
        **fields,
        "amount_micros": str(fields["amount_micros"]),
        "explicitly_shared": str(fields["explicitly_shared"]).lower(),
    }
    return PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key="campaign-budgets:create",
                action="create",
                entity_type="google_ads_campaign_budget",
                items=[IntegrationOperationIntent(fields=intent_fields)],
            )
        ],
    )


def _result(
    entry: ResolvedContextEntry, ledger: GoogleAdsMutationLedger, **fields: Any
) -> dict[str, Any]:
    parent = ledger.parents[0]
    effect = parent.effects[0]
    result = {
        **fields,
        "amount_micros": str(fields["amount_micros"]),
        "outcome": "created" if effect.outcome == "applied" else effect.outcome,
    }
    if effect.outcome == "applied" and effect.external_ref:
        budget_id = effect.external_ref.rsplit("/", 1)[-1]
        result["reference"] = GoogleAdsCampaignBudgetReference(
            customer_id=entry.external_id,
            budget_id=budget_id,
            label=str(fields["name"]),
            description="Campaign budget",
            scope_label=entry.display_name,
            status="ENABLED",
            period=str(fields["period"]),
            delivery_method=str(fields["delivery_method"]),
            amount_micros=int(fields["amount_micros"]) if fields["period"] == "DAILY" else None,
            total_amount_micros=int(fields["amount_micros"])
            if fields["period"] == "CUSTOM_PERIOD"
            else None,
            explicitly_shared=bool(fields["explicitly_shared"]),
            reference_count=0,
            currency_code=str(fields["currency_code"]),
        )
    else:
        result.update(error_code=effect.error_code, message=effect.message)
    return result


def _exception_outcome(
    entry: ResolvedContextEntry,
    pending_detail: PendingIntegrationOperationDetail,
    exc: BaseException,
    *,
    disposition: IntegrationFailureDisposition,
    **fields: Any,
) -> IntegrationAuditOutcome[GoogleAdsMutationLedger]:
    ambiguous = disposition is IntegrationFailureDisposition.AMBIGUOUS
    error_code = exc.__class__.__name__[:100]
    raw_message = exc.user_message if isinstance(exc, IntegrationError) else str(exc)
    message = " ".join(raw_message.split())[:1000] or "Campaign budget creation failed"
    ledger = campaign_budget_creation_failure_ledger(
        name=str(fields["name"]),
        period=fields["period"],
        amount_micros=int(fields["amount_micros"]),
        explicitly_shared=bool(fields["explicitly_shared"]),
        delivery_method=fields["delivery_method"],
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
        unverified_result=_result(entry, ledger, **fields) if ambiguous else None,
    )


def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Adds trusted account currencies to the approval-only argument projection."""
    entries = (
        deps.active_context.compatible_entries(GOOGLE_ADS_WRITE_BINDING)
        if deps.active_context
        else ()
    )
    accounts = [
        {
            "label": entry.display_name,
            "currency_code": str(entry.permissions_metadata["currency_code"]).strip(),
        }
        for entry in entries
        if entry.write_allowed
        and isinstance(entry.permissions_metadata.get("currency_code"), str)
        and str(entry.permissions_metadata["currency_code"]).strip()
    ]
    if not accounts:
        raise RuntimeError("Google Ads campaign budget approval requires account currencies")
    return {**args, "_account_currencies": accounts}


DEFINITION = RuntimeToolDefinition(
    name="google_ads_create_campaign_budget",
    function=google_ads_create_campaign_budget,
    description=(
        "Create one daily or total Google Ads campaign budget with an operator-selected amount. This tool does not recommend or choose an amount."
    ),
    provider="google_ads",
    label="Create Google Ads Campaign Budget",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    args_validator=_validate_create_args,
    timeout=60,
    output_model=GoogleAdsCreateCampaignBudgetOutput,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    approval_display_args=_approval_display_args,
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Creating Campaign Budget",
        completed_label="Created Campaign Budget",
        failed_label="Couldn't Create Campaign Budget",
        approval_title="Create Google Ads Campaign Budget",
        approval_prompt="The agent wants to create this campaign budget in the selected accounts.",
        approve_label="Approve & Create",
        arg_fields=(
            ToolFieldPresentation(key="name", label="Budget Name", editable=True),
            ToolFieldPresentation(key="amount", label="Amount", format="keyvalue"),
            ToolFieldPresentation(key="explicitly_shared", label="Shared Budget", format="boolean"),
            ToolFieldPresentation(
                key="delivery_method",
                label="Delivery Method",
                editable=True,
                options=("STANDARD", "ACCELERATED"),
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
