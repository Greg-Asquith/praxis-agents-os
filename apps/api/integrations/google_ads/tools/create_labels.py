# apps/api/integrations/google_ads/tools/create_labels.py

"""Google Ads label creation tool, approval-gated by default."""

from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from integrations.google_ads.operations.mutation_outcomes import (
    GoogleAdsMutationEffect,
    GoogleAdsMutationParent,
)
from integrations.google_ads.references import GoogleAdsLabelReference
from integrations.google_ads.references.label import label_reference_from_row
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
from services.integrations.context.fan_out import run_context_fan_out
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.create_labels import (
    GoogleAdsLabelCreate,
    GoogleAdsLabelCreation,
    create_labels,
)
from .schemas import GoogleAdsCreateLabelsOutput, GoogleAdsLabelDraft
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


async def google_ads_create_labels(
    ctx: RunContext[RuntimeDeps],
    labels: Annotated[
        list[GoogleAdsLabelDraft],
        Field(min_length=1, max_length=50, description="Labels to create in each account."),
    ],
) -> dict[str, Any]:
    drafts = _unique_drafts(labels)

    async def operation(entry: ResolvedContextEntry) -> Any:
        pending_detail = _pending_operation_detail(entry, drafts)

        async def execute() -> IntegrationAuditOutcome[dict[str, Any]]:
            client = await google_ads_client(ctx, entry)
            creation = await create_labels(
                client,
                customer_id=entry.external_id,
                login_customer_id=login_customer_id(entry),
                labels=[
                    GoogleAdsLabelCreate(
                        name=draft.name,
                        description=draft.description,
                        background_color=draft.background_color,
                    )
                    for draft in drafts
                ],
            )
            operation_detail = terminal_operation_detail(pending_detail, creation.ledger)
            status = audit_status(operation_detail)
            result = _creation_result(entry, drafts, creation)
            return IntegrationAuditOutcome(
                result,
                status=status,
                external_ref=",".join(creation.ledger.external_refs) or None,
                operation_detail=operation_detail,
                unverified_result=result if status is AuditStatus.UNVERIFIED else None,
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_ads_create_labels",
            operation="create_labels",
            execute=execute,
            pending_operation_detail=pending_detail,
        )

    results = await run_context_fan_out(
        ctx,
        binding=GOOGLE_ADS_WRITE_BINDING,
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


def _unique_drafts(labels: list[GoogleAdsLabelDraft]) -> list[GoogleAdsLabelDraft]:
    names = [label.name.casefold() for label in labels]
    if len(set(names)) != len(names):
        raise ModelRetry("Label names must be unique. Merge or rename the duplicate labels.")
    return labels


def _pending_operation_detail(
    entry: ResolvedContextEntry,
    drafts: list[GoogleAdsLabelDraft],
) -> PendingIntegrationOperationDetail:
    return PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key="labels:create",
                action="create",
                entity_type="google_ads_label",
                items=[
                    IntegrationOperationIntent(fields=draft.model_dump(exclude_none=True))
                    for draft in drafts
                ],
            )
        ],
    )


def _creation_result(
    entry: ResolvedContextEntry,
    drafts: list[GoogleAdsLabelDraft],
    creation: GoogleAdsLabelCreation,
) -> dict[str, Any]:
    ledger = creation.ledger
    if len(ledger.parents) != len(drafts):
        raise ValueError("Google Ads label ledger does not match the requested labels")
    return {
        "labels": [
            _existing_row(entry, creation, parent)
            if parent.decision == "skipped"
            else _submitted_row(entry, draft, parent.effects[0])
            for draft, parent in zip(drafts, ledger.parents, strict=True)
        ]
    }


def _existing_row(
    entry: ResolvedContextEntry,
    creation: GoogleAdsLabelCreation,
    parent: GoogleAdsMutationParent,
) -> dict[str, Any]:
    # Report the label as Google Ads holds it, since the requested metadata wasn't applied.
    external_ref = creation.ledger.skipped_external_ref(parent)
    row = creation.existing_labels.get(external_ref) if external_ref else None
    reference = (
        label_reference_from_row(entry.external_id, row, scope_label=entry.display_name)
        if row is not None
        else None
    )
    if reference is None:
        raise ValueError("Existing Google Ads label is missing its provider details")
    return {
        "name": reference.label,
        "description": reference.label_description,
        "background_color": reference.background_color,
        "outcome": "already_exists",
        "reference": reference,
    }


def _submitted_row(
    entry: ResolvedContextEntry,
    draft: GoogleAdsLabelDraft,
    effect: GoogleAdsMutationEffect,
) -> dict[str, Any]:
    row: dict[str, Any] = draft.model_dump()
    if effect.outcome == "applied" and effect.external_ref:
        return {
            **row,
            "outcome": "created",
            "reference": GoogleAdsLabelReference(
                customer_id=entry.external_id,
                label_id=effect.external_ref.rsplit("/", 1)[-1],
                label=draft.name,
                description=draft.description or "Label",
                scope_label=entry.display_name,
                status="ENABLED",
                label_description=draft.description,
                background_color=draft.background_color,
            ),
        }
    return {
        **row,
        "outcome": effect.outcome,
        "error_code": effect.error_code,
        "message": effect.message,
    }


DEFINITION = RuntimeToolDefinition(
    name="google_ads_create_labels",
    function=google_ads_create_labels,
    description=(
        "Create text labels in selected Google Ads accounts and return reusable label "
        "references. Existing names are reported instead of duplicated."
    ),
    provider="google_ads",
    label="Create Google Ads Labels",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=True,
    takes_ctx=True,
    timeout=60,
    output_model=GoogleAdsCreateLabelsOutput,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Creating Labels",
        completed_label="Created Labels",
        failed_label="Couldn't Create Labels",
        approval_title="Create Google Ads Labels",
        approval_prompt="The agent wants to create labels in the selected accounts.",
        approve_label="Approve & Create",
        arg_fields=(
            ToolFieldPresentation(
                key="labels",
                label="Labels",
                format="records",
                editable=True,
                min_rows=1,
                columns=(
                    ToolFieldColumn(key="name", label="Name", required=True),
                    ToolFieldColumn(key="description", label="Description", secondary=True),
                    ToolFieldColumn(
                        key="background_color",
                        label="Colour",
                        placeholder="#1A73E8",
                        secondary=True,
                    ),
                ),
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
