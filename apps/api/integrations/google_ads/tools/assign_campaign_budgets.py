# apps/api/integrations/google_ads/tools/assign_campaign_budgets.py

"""Approval-only Google Ads campaign budget assignment tool."""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext, ToolReturn

from core.exceptions.integration import IntegrationError, IntegrationFailureDisposition
from integrations.google_ads.operations.mutation_outcomes import (
    GoogleAdsMutationLedger,
    thaw_fields,
)
from integrations.google_ads.references import (
    GoogleAdsCampaignBudgetReference,
    GoogleAdsCampaignReference,
)
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
from services.integrations.entity_references import (
    ScopedEntityReference,
    resolve_runtime_references,
)
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.assign_campaign_budgets import (
    GoogleAdsCampaignBudgetAssignment,
    assign_campaign_budgets,
    campaign_budget_assignment_failure_ledger,
)
from .schemas import GoogleAdsAssignCampaignBudgetsOutput
from .utils import (
    GOOGLE_ADS_WRITE_BINDING,
    MAX_CAMPAIGN_BUDGET_ASSIGNMENT_PUBLIC_RESULT_CHARS,
    RESULTS_FIELD,
    bounded_campaign_budget_assignment_result,
    display_campaign_budget_assignment_result,
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
from .verifiers import (
    campaign_budget_reference_from_row,
    verify_campaign_budgets,
    verify_campaigns_for_budget_assignment,
)


@dataclass(frozen=True, slots=True)
class _VerifiedAssignment:
    """Describes one campaign assignment prepared from live provider state."""

    campaign: GoogleAdsCampaignReference
    previous_budget: GoogleAdsCampaignBudgetReference
    destination_budget: GoogleAdsCampaignBudgetReference
    experiment_type: str
    has_running_or_scheduled_trials: bool

    @property
    def assignment(self) -> GoogleAdsCampaignBudgetAssignment:
        return GoogleAdsCampaignBudgetAssignment(
            campaign_id=self.campaign.campaign_id,
            previous_budget_id=self.previous_budget.budget_id,
            requested_budget_id=self.destination_budget.budget_id,
        )


async def google_ads_assign_campaign_budgets(
    ctx: RunContext[RuntimeDeps],
    destination_budget: Annotated[
        GoogleAdsCampaignBudgetReference,
        Field(description="Campaign budget to assign."),
    ],
    campaigns: Annotated[
        list[GoogleAdsCampaignReference],
        Field(min_length=1, max_length=50, description="Campaigns to update."),
    ],
) -> ToolReturn[dict[str, Any]]:
    _validate_selection(destination_budget, campaigns)

    async def operation(
        entry: ResolvedContextEntry,
        references: Sequence[ScopedEntityReference],
    ) -> Any:
        selected_budget, selected_campaigns = _typed_references(references, len(campaigns))
        client = None
        verified: list[_VerifiedAssignment] = []
        pending_detail: PendingIntegrationOperationDetail | None = None

        async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
            nonlocal client, verified, pending_detail
            client = await google_ads_client(ctx, entry)
            campaign_rows = await verify_campaigns_for_budget_assignment(
                client,
                entry=entry,
                campaign_ids=[campaign.campaign_id for campaign in selected_campaigns],
            )
            previous_budget_ids = [
                _budget_id(campaign_rows[campaign.campaign_id]) for campaign in selected_campaigns
            ]
            all_budget_ids = tuple(dict.fromkeys([selected_budget.budget_id, *previous_budget_ids]))
            budget_rows = await verify_campaign_budgets(
                client,
                entry=entry,
                budget_ids=all_budget_ids,
            )
            live_budgets = {
                budget_id: campaign_budget_reference_from_row(
                    entry,
                    (
                        selected_budget
                        if budget_id == selected_budget.budget_id
                        else GoogleAdsCampaignBudgetReference(
                            customer_id=entry.external_id,
                            budget_id=budget_id,
                            label=f"Campaign budget {budget_id}",
                        )
                    ),
                    budget_rows[budget_id],
                )
                for budget_id in all_budget_ids
            }
            destination = live_budgets[selected_budget.budget_id]
            verified = [
                _verified_assignment(
                    entry,
                    selected=campaign,
                    row=campaign_rows[campaign.campaign_id],
                    previous_budget=live_budgets[previous_budget_id],
                    destination_budget=destination,
                )
                for campaign, previous_budget_id in zip(
                    selected_campaigns, previous_budget_ids, strict=True
                )
            ]
            _validate_live_assignment(destination, verified)
            pending_detail = _pending_operation_detail(entry, destination, verified)
            return pending_detail

        async def execute() -> IntegrationAuditOutcome[GoogleAdsMutationLedger]:
            if client is None or pending_detail is None or not verified:
                raise RuntimeError("Campaign budget assignment preparation did not complete")
            try:
                ledger = await assign_campaign_budgets(
                    client,
                    customer_id=entry.external_id,
                    login_customer_id=login_customer_id(entry),
                    assignments=[item.assignment for item in verified],
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
            tool_name="google_ads_assign_campaign_budgets",
            operation="assign_campaign_budgets",
            execute=execute,
            prepare_pending_operation=prepare_pending_operation,
        )
        return _split_result(verified, ledger)

    results = await run_context_targets(
        ctx,
        binding=GOOGLE_ADS_WRITE_BINDING,
        references=[destination_budget, *campaigns],
        operation=operation,
    )
    return fan_out_tool_return(results)


def _validate_selection(
    destination: GoogleAdsCampaignBudgetReference,
    campaigns: Sequence[GoogleAdsCampaignReference],
) -> None:
    if not campaigns:
        raise ModelRetry("Choose at least one Google Ads campaign.")
    if len(campaigns) > 50:
        raise ModelRetry("Choose at most 50 Google Ads campaigns per call.")
    identities = [campaign.identity() for campaign in campaigns]
    if len(set(identities)) != len(identities):
        raise ModelRetry("Choose each Google Ads campaign only once.")
    customer_ids = {destination.customer_id, *(campaign.customer_id for campaign in campaigns)}
    if len(customer_ids) != 1:
        raise ModelRetry(
            "The campaign budget and campaigns must belong to the same Google Ads account. "
            "Ask the user to choose them again."
        )


def _typed_references(
    references: Sequence[ScopedEntityReference],
    expected_campaign_count: int,
) -> tuple[GoogleAdsCampaignBudgetReference, list[GoogleAdsCampaignReference]]:
    budgets = [
        reference
        for reference in references
        if isinstance(reference, GoogleAdsCampaignBudgetReference)
    ]
    campaigns = [
        reference for reference in references if isinstance(reference, GoogleAdsCampaignReference)
    ]
    if len(budgets) != 1 or len(campaigns) != expected_campaign_count:
        raise ModelRetry("Choose one Google Ads campaign budget and its campaigns again.")
    return budgets[0], campaigns


def _budget_id(campaign: Mapping[str, Any]) -> str:
    budget_id = str(campaign.get("campaignBudget", "")).rsplit("/", 1)[-1]
    if not budget_id.isdigit():
        raise ModelRetry(
            "A selected Google Ads campaign has an invalid live budget. "
            "Refresh the connection and retry."
        )
    return budget_id


def _verified_assignment(
    entry: ResolvedContextEntry,
    *,
    selected: GoogleAdsCampaignReference,
    row: Mapping[str, Any],
    previous_budget: GoogleAdsCampaignBudgetReference,
    destination_budget: GoogleAdsCampaignBudgetReference,
) -> _VerifiedAssignment:
    campaign_id = str(row.get("id", "")).strip()
    if campaign_id != selected.campaign_id:
        raise ModelRetry("A selected Google Ads campaign changed during verification.")
    experiment_type = str(row.get("experimentType", "")).strip()
    if experiment_type not in {"BASE", "DRAFT", "EXPERIMENT"}:
        raise ModelRetry(
            "A selected Google Ads campaign has an unsupported live experiment type. "
            "Refresh the connection and retry."
        )
    return _VerifiedAssignment(
        campaign=GoogleAdsCampaignReference(
            customer_id=entry.external_id,
            campaign_id=campaign_id,
            label=(str(row.get("name", "")).strip() or selected.label)[:500],
            description="Campaign",
            scope_label=entry.display_name,
            status=str(row.get("status", "")).strip() or None,
        ),
        previous_budget=previous_budget,
        destination_budget=destination_budget,
        experiment_type=experiment_type,
        has_running_or_scheduled_trials=row.get("hasRunningOrScheduledTrials") is True,
    )


def _validate_live_assignment(
    destination: GoogleAdsCampaignBudgetReference,
    assignments: Sequence[_VerifiedAssignment],
) -> None:
    changed = [
        assignment
        for assignment in assignments
        if assignment.previous_budget.budget_id != destination.budget_id
    ]
    if any(assignment.experiment_type != "BASE" for assignment in changed):
        raise ModelRetry(
            "Draft and experiment campaigns cannot change budgets. "
            "Choose only base campaigns or leave the existing budget assigned."
        )
    if any(assignment.has_running_or_scheduled_trials for assignment in changed):
        raise ModelRetry(
            "A base campaign with a running or scheduled trial cannot change budgets. "
            "Choose a campaign without an active trial."
        )
    if any(assignment.previous_budget.period != destination.period for assignment in changed):
        raise ModelRetry(
            "A campaign budget can only be replaced by a budget with the same period. "
            "Choose a destination budget with a matching period."
        )
    if destination.explicitly_shared:
        return
    current_selected_references = sum(
        assignment.previous_budget.budget_id == destination.budget_id for assignment in assignments
    )
    live_reference_count = destination.reference_count
    if live_reference_count is None:
        raise ModelRetry("The destination campaign budget has no live reference count.")
    if current_selected_references > live_reference_count:
        raise ModelRetry(
            "The destination campaign budget has inconsistent live campaign references. "
            "Refresh the connection and retry."
        )
    final_reference_count = live_reference_count - current_selected_references + len(assignments)
    if final_reference_count > 1:
        raise ModelRetry(
            "This non-shared campaign budget would be used by more than one campaign. "
            "Choose a shared budget or one campaign."
        )


def _pending_operation_detail(
    entry: ResolvedContextEntry,
    destination: GoogleAdsCampaignBudgetReference,
    assignments: Sequence[_VerifiedAssignment],
) -> PendingIntegrationOperationDetail:
    return PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key="campaigns:assign-budget",
                action="assign_budget",
                entity_type="google_ads_campaign",
                fields={
                    "destination_budget_id": destination.budget_id,
                    "destination_budget_name": destination.label,
                    "destination_budget_resource_name": _budget_resource(destination),
                    "destination_budget_period": str(destination.period),
                    "destination_budget_explicitly_shared": str(
                        destination.explicitly_shared
                    ).lower(),
                    "destination_budget_reference_count": str(destination.reference_count),
                },
                items=[
                    IntegrationOperationIntent(
                        fields={
                            "campaign_id": item.campaign.campaign_id,
                            "campaign_name": item.campaign.label,
                            "campaign_status": str(item.campaign.status),
                            "experiment_type": item.experiment_type,
                            "has_running_or_scheduled_trials": str(
                                item.has_running_or_scheduled_trials
                            ).lower(),
                            "previous_budget_id": item.previous_budget.budget_id,
                            "previous_budget_name": item.previous_budget.label,
                            "previous_budget_resource_name": _budget_resource(item.previous_budget),
                            "requested_budget_id": destination.budget_id,
                            "requested_budget_name": destination.label,
                            "requested_budget_resource_name": _budget_resource(destination),
                        }
                    )
                    for item in assignments
                ],
            )
        ],
    )


def _result(
    assignments: Sequence[_VerifiedAssignment],
    ledger: GoogleAdsMutationLedger,
) -> dict[str, Any]:
    if len(assignments) != len(ledger.parents):
        raise ValueError("Google Ads returned contradictory campaign budget assignment accounting")
    campaigns: list[dict[str, Any]] = []
    for item, parent in zip(assignments, ledger.parents, strict=True):
        if thaw_fields(parent.identity) != {"campaign_id": item.campaign.campaign_id}:
            raise ValueError(
                "Google Ads returned contradictory campaign budget assignment accounting"
            )
        if parent.decision == "skipped":
            outcome = "already_set"
            external_ref = ledger.skipped_external_ref(parent)
            error_code = message = None
        else:
            effect = parent.effects[0]
            outcome = "assigned" if effect.outcome == "applied" else effect.outcome
            external_ref = effect.external_ref
            error_code = effect.error_code
            message = effect.message
        campaigns.append(
            {
                "campaign": item.campaign,
                "previous_budget": item.previous_budget,
                "requested_budget": item.destination_budget,
                "outcome": outcome,
                "external_ref": external_ref,
                "error_code": error_code,
                "message": message,
            }
        )
    destination = assignments[0].destination_budget
    applied_count = sum(row["outcome"] == "assigned" for row in campaigns)
    has_unverified_outcome = any(row["outcome"] == "unverified" for row in campaigns)
    if has_unverified_outcome:
        destination = destination.model_copy(update={"reference_count": None})
    elif destination.reference_count is not None:
        destination = destination.model_copy(
            update={"reference_count": destination.reference_count + applied_count}
        )
    return {"destination_budget": destination, "campaigns": campaigns}


def _split_result(
    assignments: Sequence[_VerifiedAssignment],
    ledger: GoogleAdsMutationLedger,
) -> dict[str, Any]:
    full_result = _result(assignments, ledger)
    return {
        "model_result": bounded_campaign_budget_assignment_result(full_result),
        "display_result": display_campaign_budget_assignment_result(full_result),
    }


def _exception_outcome(
    verified: Sequence[_VerifiedAssignment],
    pending_detail: PendingIntegrationOperationDetail,
    exc: BaseException,
    *,
    disposition: IntegrationFailureDisposition,
) -> IntegrationAuditOutcome[GoogleAdsMutationLedger]:
    ambiguous = disposition is IntegrationFailureDisposition.AMBIGUOUS
    error_code = exc.__class__.__name__[:100]
    raw_message = exc.user_message if isinstance(exc, IntegrationError) else str(exc)
    message = " ".join(raw_message.split())[:1000] or "Campaign budget assignment failed"
    ledger = campaign_budget_assignment_failure_ledger(
        [item.assignment for item in verified],
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


def _budget_resource(reference: GoogleAdsCampaignBudgetReference) -> str:
    return f"customers/{reference.customer_id}/campaignBudgets/{reference.budget_id}"


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Hydrate live source-to-destination budget routes shown for approval."""
    campaigns_value = args.get("campaigns")
    destination_value = args.get("destination_budget")
    if not isinstance(campaigns_value, list) or not campaigns_value:
        raise TypeError("Google Ads campaign budget approval arguments are invalid")
    if not isinstance(destination_value, Mapping):
        raise TypeError("Google Ads campaign budget approval arguments are invalid")
    campaigns, destinations = await asyncio.gather(
        resolve_runtime_references(
            deps,
            entity_kind="google_ads_campaign",
            field_key="campaigns",
            values=campaigns_value,
        ),
        resolve_runtime_references(
            deps,
            entity_kind="google_ads_campaign_budget",
            field_key="destination_budget",
            values=[dict(destination_value)],
        ),
    )
    previous_budget_values = []
    for campaign in campaigns:
        budget_id = campaign.get("campaign_budget_id")
        customer_id = campaign.get("customer_id")
        if not isinstance(budget_id, str) or not isinstance(customer_id, str):
            raise TypeError("A selected campaign has no live campaign budget")
        previous_budget_values.append(
            {
                "entity_kind": "google_ads_campaign_budget",
                "customer_id": customer_id,
                "budget_id": budget_id,
                "label": "Campaign budget",
            }
        )
    previous_budgets = await resolve_runtime_references(
        deps,
        entity_kind="google_ads_campaign_budget",
        field_key="campaigns",
        values=previous_budget_values,
    )
    destination = destinations[0]
    routes = [
        {
            "campaign": campaign,
            "previous_budget": previous_budget,
            "destination_budget": destination,
        }
        for campaign, previous_budget in zip(campaigns, previous_budgets, strict=True)
    ]
    return {
        **args,
        "campaigns": campaigns,
        "destination_budget": destination,
        "_budget_routes": routes,
    }


DEFINITION = RuntimeToolDefinition(
    name="google_ads_assign_campaign_budgets",
    function=google_ads_assign_campaign_budgets,
    description=(
        "Assign one operator-selected Google Ads campaign budget to named campaigns. "
        "This tool does not recommend or choose a budget."
    ),
    provider="google_ads",
    label="Assign Google Ads Campaign Budgets",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=60,
    output_model=GoogleAdsAssignCampaignBudgetsOutput,
    max_public_result_chars=MAX_CAMPAIGN_BUDGET_ASSIGNMENT_PUBLIC_RESULT_CHARS,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    approval_display_args=_approval_display_args,
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Assigning Campaign Budgets",
        completed_label="Assigned Campaign Budgets",
        failed_label="Couldn't Assign Campaign Budgets",
        approval_title="Assign Google Ads Campaign Budgets",
        approval_prompt=(
            "The agent is requesting a budget replacement for these campaigns in Google Ads."
        ),
        approve_label="Approve & Assign",
        arg_fields=(
            ToolFieldPresentation(
                key="destination_budget",
                label="Destination Budget",
                format="entity",
                editable=True,
                entity_kind="google_ads_campaign_budget",
            ),
            ToolFieldPresentation(
                key="campaigns",
                label="Campaigns",
                format="entity_list",
                editable=True,
                entity_kind="google_ads_campaign",
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
