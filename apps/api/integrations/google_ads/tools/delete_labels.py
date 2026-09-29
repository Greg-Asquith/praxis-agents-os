# apps/api/integrations/google_ads/tools/delete_labels.py

"""Approval-only Google Ads label deletion tool."""

from collections.abc import Mapping, Sequence
from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from integrations.google_ads.operations.mutation_outcomes import GoogleAdsMutationLedger
from integrations.google_ads.references import (
    GoogleAdsLabelAssociationCounts,
    GoogleAdsLabelReference,
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
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.context.targeted import run_context_targets
from services.integrations.entity_references import resolve_runtime_references
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.delete_labels import MAX_LABEL_DELETIONS, delete_labels
from .schemas import GoogleAdsDeleteLabelsOutput
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
from .verifiers import verify_labels_with_associations


async def google_ads_delete_labels(
    ctx: RunContext[RuntimeDeps],
    labels: Annotated[
        list[GoogleAdsLabelReference],
        Field(
            min_length=1,
            max_length=MAX_LABEL_DELETIONS,
            description="Labels to delete. Google Ads detaches them from every item.",
        ),
    ],
) -> dict[str, Any]:
    _validate_selection(labels)

    async def operation(
        entry: ResolvedContextEntry,
        references: Sequence[GoogleAdsLabelReference],
    ) -> Any:
        client = None
        live_labels: list[GoogleAdsLabelReference] = []
        pending_detail: PendingIntegrationOperationDetail | None = None

        async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
            nonlocal client, live_labels, pending_detail
            client = await google_ads_client(ctx, entry)
            live = await verify_labels_with_associations(
                client, entry=entry, label_ids=[reference.label_id for reference in references]
            )
            live_labels = [live[reference.label_id] for reference in references]
            pending_detail = _pending_operation_detail(entry, live_labels)
            return pending_detail

        async def execute() -> IntegrationAuditOutcome[dict[str, Any]]:
            if client is None or pending_detail is None:
                raise RuntimeError("Label deletion preparation did not complete")
            ledger = await delete_labels(
                client,
                customer_id=entry.external_id,
                login_customer_id=login_customer_id(entry),
                label_ids=[label.label_id for label in live_labels],
            )
            detail = terminal_operation_detail(pending_detail, ledger)
            status = audit_status(detail)
            result = _deletion_result(live_labels, ledger)
            return IntegrationAuditOutcome(
                result,
                status=status,
                external_ref=",".join(ledger.external_refs) or None,
                operation_detail=detail,
                unverified_result=result if status is AuditStatus.UNVERIFIED else None,
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_ads_delete_labels",
            operation="delete_labels",
            execute=execute,
            prepare_pending_operation=prepare_pending_operation,
        )

    results = await run_context_targets(
        ctx,
        binding=GOOGLE_ADS_WRITE_BINDING,
        references=labels,
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


def _validate_selection(labels: Sequence[GoogleAdsLabelReference]) -> None:
    if not labels or len(labels) > MAX_LABEL_DELETIONS:
        raise ModelRetry(f"Choose 1 to {MAX_LABEL_DELETIONS} Google Ads labels.")
    if len({label.identity() for label in labels}) != len(labels):
        raise ModelRetry("Choose each Google Ads label only once.")


def _validate_args(_ctx: RunContext[RuntimeDeps], labels: list[GoogleAdsLabelReference]) -> None:
    _validate_selection(labels)


def _pending_operation_detail(
    entry: ResolvedContextEntry,
    labels: Sequence[GoogleAdsLabelReference],
) -> PendingIntegrationOperationDetail:
    return PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key="labels:delete",
                action="delete",
                entity_type="google_ads_label",
                items=[
                    IntegrationOperationIntent(
                        fields={
                            "label_id": label.label_id,
                            "label_name": label.label,
                            "association_counts": _counts(label).model_dump(),
                        }
                    )
                    for label in labels
                ],
            )
        ],
    )


def _deletion_result(
    labels: Sequence[GoogleAdsLabelReference],
    ledger: GoogleAdsMutationLedger,
) -> dict[str, Any]:
    if len(labels) != len(ledger.parents):
        raise ValueError("Google Ads label ledger does not match the requested labels")
    rows: list[dict[str, Any]] = []
    for label, parent in zip(labels, ledger.parents, strict=True):
        effect = parent.effects[0]
        row: dict[str, Any] = {
            "label_id": label.label_id,
            "label_name": label.label,
            "label_color": label.background_color,
            "association_counts": _counts(label),
        }
        if effect.outcome == "applied":
            rows.append({**row, "outcome": "deleted"})
        else:
            rows.append(
                {
                    **row,
                    "outcome": effect.outcome,
                    "error_code": effect.error_code,
                    "message": effect.message,
                }
            )
    return {"labels": rows}


def _counts(label: GoogleAdsLabelReference) -> GoogleAdsLabelAssociationCounts:
    if label.association_counts is None:
        raise ValueError("Google Ads label deletion requires live association counts")
    return label.association_counts


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Hydrates live label details and association counts shown for approval."""
    selected = [dict(label) for label in args.get("labels", []) if isinstance(label, Mapping)]
    if not selected or len(selected) != len(args.get("labels", [])):
        raise TypeError("Google Ads label deletion approval arguments are invalid")
    labels = await resolve_runtime_references(
        deps,
        entity_kind="google_ads_label",
        field_key="labels",
        values=selected,
    )
    return {**args, "labels": labels}


DEFINITION = RuntimeToolDefinition(
    name="google_ads_delete_labels",
    function=google_ads_delete_labels,
    description=(
        "Permanently delete operator-selected labels from Google Ads. Google Ads also "
        "detaches each label from every campaign, ad group, keyword, and ad. To detach a "
        "label from some items only, use google_ads_remove_labels."
    ),
    provider="google_ads",
    label="Delete Google Ads Labels",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    args_validator=_validate_args,
    timeout=60,
    output_model=GoogleAdsDeleteLabelsOutput,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    approval_display_args=_approval_display_args,
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Deleting Labels",
        completed_label="Deleted Labels",
        failed_label="Couldn't Delete Labels",
        approval_title="Permanently Delete Google Ads Labels",
        approval_prompt=(
            "The agent wants to permanently delete these labels. Google Ads also detaches "
            "them from every item. This action cannot be undone."
        ),
        approve_label="Approve & Delete",
        arg_fields=(
            ToolFieldPresentation(
                key="labels",
                label="Labels",
                format="entity_list",
                editable=True,
                entity_kind="google_ads_label",
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
