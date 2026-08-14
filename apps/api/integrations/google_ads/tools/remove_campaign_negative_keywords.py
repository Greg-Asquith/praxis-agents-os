# apps/api/integrations/google_ads/tools/remove_campaign_negative_keywords.py

"""Approval-only campaign negative-keyword removal tool."""

from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext, ToolReturn

from integrations.google_ads.references import GoogleAdsCampaignReference
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

from .schemas import GoogleAdsRemoveCampaignKeywordOutput
from .schemas.negative_keyword import NegativeKeywordRemovalEntry
from .utils import (
    GOOGLE_ADS_WRITE_BINDING,
    MAX_CAMPAIGN_NEGATIVE_PUBLIC_RESULT_CHARS,
    RESULTS_FIELD,
    google_ads_available,
    run_campaign_negative_keyword_tool,
)


async def google_ads_remove_campaign_negative_keywords(
    ctx: RunContext[RuntimeDeps],
    campaign_ids: Annotated[
        list[GoogleAdsCampaignReference],
        Field(min_length=1, max_length=50, description="Campaigns to update."),
    ],
    keywords: Annotated[
        list[NegativeKeywordRemovalEntry],
        Field(min_length=1, max_length=500, description="Negative keywords to remove."),
    ],
) -> ToolReturn[dict[str, Any]]:
    if not campaign_ids:
        raise ModelRetry("Choose at least one Google Ads campaign.")
    if len(campaign_ids) > 50:
        raise ModelRetry("Choose at most 50 Google Ads campaigns per call.")
    if len(keywords) > 500:
        raise ModelRetry(
            "Remove at most 500 negative keywords per call. Split larger sets into chunks."
        )
    return await run_campaign_negative_keyword_tool(
        ctx,
        campaign_ids,
        keywords,
        action="remove",
    )


DEFINITION = RuntimeToolDefinition(
    name="google_ads_remove_campaign_negative_keywords",
    function=google_ads_remove_campaign_negative_keywords,
    description="Remove negative keywords directly from selected Google Ads campaigns.",
    provider="google_ads",
    label="Remove Google Ads Campaign Negative Keywords",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=60,
    output_model=GoogleAdsRemoveCampaignKeywordOutput,
    max_public_result_chars=MAX_CAMPAIGN_NEGATIVE_PUBLIC_RESULT_CHARS,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Removing Campaign Negative Keywords",
        completed_label="Removed Campaign Negative Keywords",
        failed_label="Couldn't Remove Campaign Negative Keywords",
        approval_title="Remove Campaign Negative Keywords",
        approval_prompt=(
            "The agent wants to remove exclusions from the selected campaigns, "
            "which can re-enable matching traffic and increase spend."
        ),
        approve_label="Approve & Remove",
        arg_fields=(
            ToolFieldPresentation(
                key="campaign_ids",
                label="Campaigns",
                format="entity_list",
                editable=True,
                entity_kind="google_ads_campaign",
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
                        options=("EXACT", "PHRASE", "BROAD", "ANY"),
                        required=True,
                    ),
                ),
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
