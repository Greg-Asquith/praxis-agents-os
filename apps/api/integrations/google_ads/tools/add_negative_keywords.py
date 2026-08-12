# apps/api/integrations/google_ads/tools/add_negative_keywords.py

"""Approval-only Google Ads negative keyword list mutation tool."""

from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext, ToolReturn

from integrations.google_ads.references import GoogleAdsSharedSetReference
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
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    IntegrationOperationTarget,
    PendingIntegrationOperationDetail,
)
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.targeted import run_context_targets
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.add_negative_keywords import add_negative_keywords
from .schemas import GoogleAdsOutput
from .schemas.negative_keyword import NegativeKeywordEntry
from .utils import (
    GOOGLE_ADS_WRITE_BINDING,
    MAX_NEGATIVE_KEYWORD_PUBLIC_RESULT_CHARS,
    RESULTS_FIELD,
    bounded_negative_keyword_result,
    complete_negative_keyword_result,
    fan_out_tool_return,
    google_ads_available,
    google_ads_client,
    login_customer_id,
    normalize_negative_keywords,
)
from .utils.mutation_evidence import audit_status, terminal_operation_detail
from .verifiers import verify_shared_sets


async def google_ads_add_negative_keywords(
    ctx: RunContext[RuntimeDeps],
    negative_list: Annotated[
        GoogleAdsSharedSetReference,
        Field(description="Negative keyword list to update."),
    ],
    keywords: Annotated[
        list[NegativeKeywordEntry],
        Field(min_length=1, max_length=500, description="Negative keywords to add."),
    ],
) -> ToolReturn[dict[str, Any]]:
    if len(keywords) > 500:
        raise ModelRetry(
            "Add at most 500 negative keywords per call. Split larger sets into chunks."
        )
    normalized_keywords = normalize_negative_keywords(keywords)

    async def operation(
        entry: ResolvedContextEntry,
        references: list[GoogleAdsSharedSetReference],
    ) -> Any:
        reference = references[0] if references else negative_list
        pending_detail = _pending_negative_keyword_operation_detail(
            reference,
            [keyword.model_dump() for keyword in normalized_keywords],
        )

        async def execute() -> Any:
            if len(references) != 1:
                raise ModelRetry("Choose one negative keyword list.")
            if not reference.external_id.isdigit():
                raise ModelRetry("The selected negative keyword list reference is invalid.")
            client = await google_ads_client(ctx, entry)
            await verify_shared_sets(
                client,
                entry=entry,
                shared_set_ids=(reference.external_id,),
            )
            ledger = await add_negative_keywords(
                client,
                customer_id=entry.external_id,
                login_customer_id=login_customer_id(entry),
                shared_set_id=reference.external_id,
                keywords=[keyword.model_dump() for keyword in normalized_keywords],
            )
            result = ledger.result()
            operation_detail = terminal_operation_detail(pending_detail, ledger)
            return IntegrationAuditOutcome(
                result,
                status=audit_status(operation_detail),
                external_ref=(",".join(item["resource_name"] for item in result["added"]) or None),
                operation_detail=operation_detail,
            )

        full_result = await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_ads_add_negative_keywords",
            operation="add_negative_keywords",
            execute=execute,
            pending_operation_detail=pending_detail,
        )
        return {
            "model_result": bounded_negative_keyword_result(full_result),
            "display_result": complete_negative_keyword_result(full_result),
        }

    results = await run_context_targets(
        ctx,
        binding=GOOGLE_ADS_WRITE_BINDING,
        references=[negative_list],
        operation=operation,
    )
    return fan_out_tool_return(results)


def _pending_negative_keyword_operation_detail(
    reference: GoogleAdsSharedSetReference,
    keywords: list[dict[str, str]],
) -> PendingIntegrationOperationDetail:
    """Persist the complete intended write before contacting Google Ads."""
    return PendingIntegrationOperationDetail(
        target=IntegrationOperationTarget(
            entity_type=reference.entity_kind,
            external_id=reference.external_id,
            display_name=reference.label,
            integration_resource_id=str(reference.integration_resource_id),
            attributes={"member_count": reference.member_count},
        ),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key=f"shared-set:{reference.external_id}:add-keywords",
                action="add",
                entity_type="negative_keyword",
                external_id=reference.external_id,
                display_name=reference.label,
                items=[IntegrationOperationIntent(fields=keyword) for keyword in keywords],
            )
        ],
    )


DEFINITION = RuntimeToolDefinition(
    name="google_ads_add_negative_keywords",
    function=google_ads_add_negative_keywords,
    description="Add negative keywords to a selected Google Ads negative keyword list.",
    provider="google_ads",
    label="Add Google Ads Negative Keywords",
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=60,
    output_model=GoogleAdsOutput,
    max_public_result_chars=MAX_NEGATIVE_KEYWORD_PUBLIC_RESULT_CHARS,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Adding Negative Keywords",
        completed_label="Added Negative Keywords",
        failed_label="Couldn't Add Negative Keywords",
        approval_title="Add Negative Keywords",
        approval_prompt=(
            "The agent wants to add negative keywords to a shared list. "
            "Review and edit the rows before approving."
        ),
        approve_label="Approve & Add",
        arg_fields=(
            ToolFieldPresentation(
                key="negative_list",
                label="Negative Keyword List",
                format="entity",
                editable=True,
                entity_kind="google_ads_shared_set",
            ),
            ToolFieldPresentation(
                key="keywords",
                label="Keywords",
                format="records",
                editable=True,
                min_rows=1,
                columns=(
                    ToolFieldColumn(key="text", label="Keyword", required=True),
                    ToolFieldColumn(
                        key="match_type",
                        label="Match Type",
                        options=("EXACT", "PHRASE", "BROAD"),
                        required=True,
                    ),
                ),
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
