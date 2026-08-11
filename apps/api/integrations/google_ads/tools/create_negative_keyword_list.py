# apps/api/integrations/google_ads/tools/create_negative_keyword_list.py

"""Approval-only Google Ads negative keyword list creation tool."""

from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

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
    IntegrationOperationChange,
    IntegrationOperationCounts,
    IntegrationOperationDetail,
    IntegrationOperationTarget,
)
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.fan_out import run_context_fan_out
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.create_negative_keyword_list import create_negative_keyword_list
from .schemas import GoogleAdsOutput
from .utils import (
    GOOGLE_ADS_WRITE_BINDING,
    RESULTS_FIELD,
    google_ads_available,
    google_ads_client,
    login_customer_id,
)


async def google_ads_create_negative_keyword_list(
    ctx: RunContext[RuntimeDeps],
    names: Annotated[
        list[str],
        Field(min_length=1, max_length=20, description="Negative keyword list names."),
    ],
) -> dict[str, Any]:
    normalized_names = _normalize_names(names)

    async def operation(entry: ResolvedContextEntry) -> Any:
        async def execute() -> Any:
            client = await google_ads_client(ctx, entry)
            result = await create_negative_keyword_list(
                client,
                customer_id=entry.external_id,
                login_customer_id=login_customer_id(entry),
                names=normalized_names,
            )
            return IntegrationAuditOutcome(
                result,
                status=_audit_status(result),
                external_ref=",".join(result["resource_names"]) or None,
                operation_detail=_operation_detail(entry, result),
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_ads_create_negative_keyword_list",
            operation="create_negative_keyword_list",
            execute=execute,
            pending_operation_detail=_pending_operation_detail(entry, normalized_names),
        )

    results = await run_context_fan_out(
        ctx,
        binding=GOOGLE_ADS_WRITE_BINDING,
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


def _audit_status(result: dict[str, Any]) -> AuditStatus:
    if result["list_errors"] and not result["resource_names"]:
        return AuditStatus.FAILURE
    return AuditStatus.SUCCESS


def _operation_detail(
    entry: ResolvedContextEntry,
    result: dict[str, Any],
) -> IntegrationOperationDetail:
    created = list(zip(result["created_names"], result["resource_names"], strict=False))
    return IntegrationOperationDetail(
        target=_account_target(entry),
        changes=[
            *(
                IntegrationOperationChange(
                    action="create",
                    entity_type="google_ads_negative_keyword_list",
                    external_ref=resource_name,
                    fields={"name": name},
                )
                for name, resource_name in created
            ),
            *(
                IntegrationOperationChange(
                    action="create_failed",
                    entity_type="google_ads_negative_keyword_list",
                    fields={
                        "name": str(error.get("name", ""))[:255],
                        "error_code": str(error.get("error_code", "unknown"))[:100],
                    },
                )
                for error in result["list_errors"]
            ),
        ],
        counts=IntegrationOperationCounts(
            applied=len(created),
            skipped=len(result["skipped_existing"]),
            failed=len(result["list_errors"]),
        ),
    )


def _pending_operation_detail(
    entry: ResolvedContextEntry,
    names: list[str],
) -> IntegrationOperationDetail:
    return IntegrationOperationDetail(
        target=_account_target(entry),
        changes=[
            IntegrationOperationChange(
                action="create",
                entity_type="google_ads_negative_keyword_list",
                fields={"name": name},
            )
            for name in names
        ],
        counts=IntegrationOperationCounts(applied=0, skipped=0, failed=0),
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


DEFINITION = RuntimeToolDefinition(
    name="google_ads_create_negative_keyword_list",
    function=google_ads_create_negative_keyword_list,
    description="Create named negative keyword lists in selected Google Ads accounts.",
    provider="google_ads",
    label="Create Google Ads Negative Keyword Lists",
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=60,
    output_model=GoogleAdsOutput,
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
