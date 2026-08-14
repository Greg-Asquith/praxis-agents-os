# apps/api/integrations/google_ads/tools/create_negative_keyword_list.py

"""Approval-only Google Ads negative keyword list creation tool."""

from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from integrations.google_ads.operations.mutation_outcomes import (
    GoogleAdsMutationLedger,
    thaw_fields,
)
from integrations.google_ads.references import GoogleAdsSharedSetReference
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
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    IntegrationOperationTarget,
    PendingIntegrationOperationDetail,
)
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.fan_out import run_context_fan_out
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.create_negative_keyword_list import create_negative_keyword_list
from .schemas import GoogleAdsCreateNegativeKeywordListOutput
from .utils import (
    GOOGLE_ADS_WRITE_BINDING,
    RESULTS_FIELD,
    google_ads_available,
    google_ads_client,
    login_customer_id,
)
from .utils.mutation_evidence import audit_status, terminal_operation_detail


async def google_ads_create_negative_keyword_list(
    ctx: RunContext[RuntimeDeps],
    names: Annotated[
        list[str],
        Field(min_length=1, max_length=20, description="Negative keyword list names."),
    ],
) -> dict[str, Any]:
    normalized_names = _normalize_names(names)

    async def operation(entry: ResolvedContextEntry) -> Any:
        pending_detail = _pending_operation_detail(entry, normalized_names)

        async def execute() -> Any:
            client = await google_ads_client(ctx, entry)
            ledger = await create_negative_keyword_list(
                client,
                customer_id=entry.external_id,
                login_customer_id=login_customer_id(entry),
                names=normalized_names,
            )
            result = ledger.result()
            operation_detail = terminal_operation_detail(pending_detail, ledger)
            return IntegrationAuditOutcome(
                ledger,
                status=audit_status(operation_detail),
                external_ref=",".join(result["resource_names"]) or None,
                operation_detail=operation_detail,
            )

        ledger = await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_ads_create_negative_keyword_list",
            operation="create_negative_keyword_list",
            execute=execute,
            pending_operation_detail=pending_detail,
        )
        return _creation_result(entry, ledger)

    results = await run_context_fan_out(
        ctx,
        binding=GOOGLE_ADS_WRITE_BINDING,
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


def _pending_operation_detail(
    entry: ResolvedContextEntry,
    names: list[str],
) -> PendingIntegrationOperationDetail:
    return PendingIntegrationOperationDetail(
        target=_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key="negative-keyword-lists:create",
                action="create",
                entity_type="google_ads_negative_keyword_list",
                items=[IntegrationOperationIntent(fields={"name": name}) for name in names],
            )
        ],
    )


def _account_target(entry: ResolvedContextEntry) -> IntegrationOperationTarget:
    return IntegrationOperationTarget(
        entity_type="google_ads_account",
        external_id=entry.external_id,
        display_name=entry.display_name,
        integration_resource_id=str(entry.integration_resource_id),
    )


def _normalize_names(names: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_name in names:
        name = " ".join(raw_name.split())
        if not name:
            continue
        if len(name.encode("utf-8")) > 255:
            raise ModelRetry("Negative keyword list names must be 255 UTF-8 bytes or fewer.")
        key = name.casefold()
        if key not in seen:
            seen.add(key)
            normalized.append(name)
    if not normalized:
        raise ModelRetry("Provide at least one non-empty negative keyword list name.")
    return normalized


def _creation_result(
    entry: ResolvedContextEntry,
    ledger: GoogleAdsMutationLedger,
) -> dict[str, Any]:
    outcomes: list[dict[str, Any]] = []
    for parent in ledger.parents:
        name = thaw_fields(parent.identity)["name"]
        if parent.decision == "skipped":
            external_ref = ledger.skipped_external_ref(parent)
            if external_ref is None:
                raise ValueError("Existing Google Ads list is missing its provider reference")
            shared_set_id = external_ref.rsplit("/", 1)[-1]
            outcomes.append(
                {
                    "name": name,
                    "outcome": "already_exists",
                    "reference": _shared_set_reference(entry, name, shared_set_id),
                }
            )
            continue
        effect = parent.effects[0]
        if effect.outcome == "applied" and effect.external_ref is not None:
            outcomes.append(
                {
                    "name": name,
                    "outcome": "created",
                    "reference": _shared_set_reference(
                        entry,
                        name,
                        effect.external_ref.rsplit("/", 1)[-1],
                    ),
                }
            )
        else:
            outcomes.append(
                {
                    "name": name,
                    "outcome": "failed",
                    "error_code": effect.error_code,
                    "message": effect.message,
                }
            )
    return {"outcomes": outcomes}


def _shared_set_reference(
    entry: ResolvedContextEntry,
    name: str,
    shared_set_id: str,
) -> GoogleAdsSharedSetReference:
    return GoogleAdsSharedSetReference(
        customer_id=entry.external_id,
        shared_set_id=shared_set_id,
        label=name,
        description="Negative keyword list",
        scope_label=entry.display_name,
    )


DEFINITION = RuntimeToolDefinition(
    name="google_ads_create_negative_keyword_list",
    function=google_ads_create_negative_keyword_list,
    description=(
        "Create named negative keyword lists in selected Google Ads accounts and return reusable "
        "negative-list references."
    ),
    provider="google_ads",
    label="Create Google Ads Negative Keyword Lists",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=60,
    output_model=GoogleAdsCreateNegativeKeywordListOutput,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Creating Negative Keyword Lists",
        completed_label="Created Negative Keyword Lists",
        failed_label="Couldn't Create Negative Keyword Lists",
        approval_title="Create Google Ads Negative Keyword Lists",
        approval_prompt=(
            "The agent wants to create negative keyword lists in the selected accounts."
        ),
        approve_label="Approve & Create",
        arg_fields=(
            ToolFieldPresentation(
                key="names",
                label="List Names",
                format="list",
                editable=True,
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
