# apps/api/integrations/google_ads/tools/utils/label_associations.py

"""Shared runtime for the Google Ads label apply and remove tools."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import ModelRetry, RunContext

from integrations.google_ads.operations.mutate_label_associations import (
    MAX_LABEL_ASSOCIATIONS,
    GoogleAdsLabelAssociation,
    GoogleAdsLabelAssociationAction,
    mutate_label_associations,
)
from integrations.google_ads.operations.mutation_outcomes import GoogleAdsMutationLedger
from integrations.google_ads.references import (
    GoogleAdsAdGroupReference,
    GoogleAdsCampaignReference,
    GoogleAdsKeywordReference,
    GoogleAdsLabelReference,
)
from services.agents.runtime.context import RuntimeDeps
from services.audit_events import (
    AuditStatus,
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    PendingIntegrationOperationDetail,
)
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.context.targeted import run_context_targets
from services.integrations.entity_references import ScopedEntityReference
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..schemas.labels import (
    GoogleAdsAdGroupLabelTarget,
    GoogleAdsCampaignLabelTarget,
    GoogleAdsKeywordLabelTarget,
)
from ..verifiers import verify_label_targets, verify_labels
from .bindings import GOOGLE_ADS_WRITE_BINDING
from .client import google_ads_client
from .mutation_evidence import audit_status, google_ads_account_target, terminal_operation_detail
from .routing import login_customer_id

MAX_LABELS_PER_CALL = 10
MAX_LABEL_TARGETS_PER_CALL = 500

type LabelTarget = (
    GoogleAdsCampaignLabelTarget | GoogleAdsAdGroupLabelTarget | GoogleAdsKeywordLabelTarget
)


@dataclass(slots=True)
class _AccountSelection:
    labels: list[GoogleAdsLabelReference] = field(default_factory=list)
    targets: list[LabelTarget] = field(default_factory=list)


def label_association_selection(
    labels: Sequence[GoogleAdsLabelReference],
    targets: Sequence[LabelTarget],
) -> dict[str, _AccountSelection]:
    """Groups labels and targets by account, rejecting pairs that span accounts."""
    if not labels or len(labels) > MAX_LABELS_PER_CALL:
        raise ModelRetry(f"Choose 1 to {MAX_LABELS_PER_CALL} Google Ads labels.")
    if not targets or len(targets) > MAX_LABEL_TARGETS_PER_CALL:
        raise ModelRetry(
            f"Choose 1 to {MAX_LABEL_TARGETS_PER_CALL} campaigns, ad groups, or keywords."
        )
    if len({label.identity() for label in labels}) != len(labels):
        raise ModelRetry("Choose each Google Ads label only once.")
    if len({target_reference(target).identity() for target in targets}) != len(targets):
        raise ModelRetry("Choose each campaign, ad group, or keyword only once.")
    selection: dict[str, _AccountSelection] = {}
    for label in labels:
        selection.setdefault(label.customer_id, _AccountSelection()).labels.append(label)
    for target in targets:
        customer_id = target_reference(target).customer_id
        selection.setdefault(customer_id, _AccountSelection()).targets.append(target)
    if any(not account.labels or not account.targets for account in selection.values()):
        raise ModelRetry(
            "Labels only apply within their own Google Ads account. Choose labels and targets "
            "from the same account."
        )
    if sum(len(item.labels) * len(item.targets) for item in selection.values()) > (
        MAX_LABEL_ASSOCIATIONS
    ):
        raise ModelRetry(
            f"Each call can change at most {MAX_LABEL_ASSOCIATIONS} label and target pairs. "
            "Choose fewer labels or targets."
        )
    return selection


def target_reference(target: LabelTarget) -> ScopedEntityReference:
    if isinstance(target, GoogleAdsCampaignLabelTarget):
        return target.campaign
    if isinstance(target, GoogleAdsAdGroupLabelTarget):
        return target.ad_group
    return target.keyword


def _target_id(target: LabelTarget) -> str:
    if isinstance(target, GoogleAdsCampaignLabelTarget):
        return target.campaign.campaign_id
    if isinstance(target, GoogleAdsAdGroupLabelTarget):
        return target.ad_group.ad_group_id
    return f"{target.keyword.ad_group_id}~{target.keyword.criterion_id}"


async def run_label_association_tool(
    ctx: RunContext[RuntimeDeps],
    *,
    tool_name: str,
    action: GoogleAdsLabelAssociationAction,
    labels: Sequence[GoogleAdsLabelReference],
    targets: Sequence[LabelTarget],
) -> dict[str, Any]:
    selection = label_association_selection(labels, targets)

    async def operation(entry: ResolvedContextEntry, _references: Any) -> Any:
        selected = selection[entry.external_id]
        client = None
        live_labels: list[GoogleAdsLabelReference] = []
        pending_detail: PendingIntegrationOperationDetail | None = None

        async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
            nonlocal client, live_labels, pending_detail
            client = await google_ads_client(ctx, entry)
            live = await verify_labels(
                client, entry=entry, label_ids=[label.label_id for label in selected.labels]
            )
            live_labels = [live[label.label_id] for label in selected.labels]
            await _verify_targets(client, entry, selected.targets)
            pending_detail = _pending_operation_detail(entry, action, live_labels, selected.targets)
            return pending_detail

        async def execute() -> IntegrationAuditOutcome[dict[str, Any]]:
            if client is None or pending_detail is None:
                raise RuntimeError("Label change preparation did not complete")
            ledger = await mutate_label_associations(
                client,
                customer_id=entry.external_id,
                login_customer_id=login_customer_id(entry),
                action=action,
                associations=[
                    GoogleAdsLabelAssociation(label.label_id, target.kind, _target_id(target))
                    for label in live_labels
                    for target in selected.targets
                ],
            )
            detail = terminal_operation_detail(pending_detail, ledger)
            status = audit_status(detail)
            result = _association_result(action, live_labels, selected.targets, ledger)
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
            tool_name=tool_name,
            operation=f"{action}_labels",
            execute=execute,
            prepare_pending_operation=prepare_pending_operation,
        )

    results = await run_context_targets(
        ctx,
        binding=GOOGLE_ADS_WRITE_BINDING,
        references=[*labels, *(target_reference(target) for target in targets)],
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


async def _verify_targets(client: Any, entry: ResolvedContextEntry, targets: Sequence[LabelTarget]):
    references = [target_reference(target) for target in targets]
    await verify_label_targets(
        client,
        entry=entry,
        campaigns=[item for item in references if isinstance(item, GoogleAdsCampaignReference)],
        ad_groups=[item for item in references if isinstance(item, GoogleAdsAdGroupReference)],
        keywords=[item for item in references if isinstance(item, GoogleAdsKeywordReference)],
    )


def _pending_operation_detail(
    entry: ResolvedContextEntry,
    action: GoogleAdsLabelAssociationAction,
    labels: Sequence[GoogleAdsLabelReference],
    targets: Sequence[LabelTarget],
) -> PendingIntegrationOperationDetail:
    return PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key=f"label:{label.label_id}:{action}",
                action=action,
                entity_type="google_ads_label_association",
                external_id=label.label_id,
                display_name=label.label,
                fields={"label_id": label.label_id},
                items=[
                    IntegrationOperationIntent(
                        fields={
                            "target_kind": target.kind,
                            "target_id": _target_id(target),
                            "target_name": target_reference(target).label,
                        }
                    )
                    for target in targets
                ],
            )
            for label in labels
        ],
    )


def _association_result(
    action: GoogleAdsLabelAssociationAction,
    labels: Sequence[GoogleAdsLabelReference],
    targets: Sequence[LabelTarget],
    ledger: GoogleAdsMutationLedger,
) -> dict[str, Any]:
    pairs = [(label, target) for label in labels for target in targets]
    if len(pairs) != len(ledger.parents):
        raise ValueError("Google Ads label ledger does not match the requested pairs")
    rows: list[dict[str, Any]] = []
    for (label, target), parent in zip(pairs, ledger.parents, strict=True):
        row: dict[str, Any] = {
            "label_id": label.label_id,
            "label_name": label.label,
            "label_color": label.background_color,
            "target_kind": target.kind,
            "target_id": _target_id(target),
            "target_name": target_reference(target).label,
        }
        if parent.decision == "skipped":
            rows.append({**row, "outcome": parent.skip_reason})
            continue
        effect = parent.effects[0]
        if effect.outcome == "applied":
            rows.append({**row, "outcome": "applied" if action == "apply" else "removed"})
        else:
            rows.append(
                {
                    **row,
                    "outcome": effect.outcome,
                    "error_code": effect.error_code,
                    "message": effect.message,
                }
            )
    return {"associations": rows}
