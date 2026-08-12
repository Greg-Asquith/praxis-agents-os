# apps/api/integrations/google_ads/tools/remove_ad_group_negative_keywords.py

"""Approval-only ad-group negative-keyword removal tool."""

from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext, ToolReturn

from integrations.google_ads.references import GoogleAdsAdGroupReference
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

from .schemas import GoogleAdsOutput
from .schemas.negative_keyword import NegativeKeywordRemovalEntry
from .utils import GOOGLE_ADS_WRITE_BINDING, RESULTS_FIELD, google_ads_available
from .utils.ad_group_negative_keywords import (
    MAX_AD_GROUP_NEGATIVE_PUBLIC_RESULT_CHARS,
    run_ad_group_negative_keyword_tool,
)


async def google_ads_remove_ad_group_negative_keywords(
    ctx: RunContext[RuntimeDeps],
    ad_group_ids: Annotated[
        list[GoogleAdsAdGroupReference],
        Field(min_length=1, max_length=50, description="Ad groups to update."),
    ],
    keywords: Annotated[
        list[NegativeKeywordRemovalEntry],
        Field(min_length=1, max_length=500, description="Negative keywords to remove."),
    ],
) -> ToolReturn[dict[str, Any]]:
    if not ad_group_ids:
        raise ModelRetry("Choose at least one Google Ads ad group.")
    if len(ad_group_ids) > 50:
        raise ModelRetry("Choose at most 50 Google Ads ad groups per call.")
    if len(keywords) > 500:
        raise ModelRetry(
            "Remove at most 500 negative keywords per call. Split larger sets into chunks."
        )
    return await run_ad_group_negative_keyword_tool(ctx, ad_group_ids, keywords, action="remove")


DEFINITION = RuntimeToolDefinition(
    name="google_ads_remove_ad_group_negative_keywords",
    function=google_ads_remove_ad_group_negative_keywords,
    description="Remove negative keywords directly from selected Google Ads ad groups.",
    provider="google_ads",
    label="Remove Google Ads Ad Group Negative Keywords",
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=60,
    output_model=GoogleAdsOutput,
    max_public_result_chars=MAX_AD_GROUP_NEGATIVE_PUBLIC_RESULT_CHARS,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Removing Ad Group Negative Keywords",
        completed_label="Removed Ad Group Negative Keywords",
        failed_label="Couldn't Remove Ad Group Negative Keywords",
        approval_title="Remove Ad Group Negative Keywords",
        approval_prompt=(
            "The agent wants to remove exclusions from the selected ad groups, "
            "which can re-enable matching traffic and increase spend."
        ),
        approve_label="Approve & Remove",
        arg_fields=(
            ToolFieldPresentation(
                key="ad_group_ids",
                label="Ad Groups",
                format="entity_list",
                editable=True,
                entity_kind="google_ads_ad_group",
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
