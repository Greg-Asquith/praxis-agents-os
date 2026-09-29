# apps/api/integrations/google_ads/tools/apply_labels.py

"""Google Ads label apply tool, approval-gated by default."""

from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import RunContext

from integrations.google_ads.references import GoogleAdsLabelReference
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_EXTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_EXTERNAL_WRITE,
    TOOL_POLICY_APPROVAL,
    RuntimeToolDefinition,
    ToolPresentation,
)

from .schemas import GoogleAdsApplyLabelsOutput, GoogleAdsLabelTarget
from .utils import GOOGLE_ADS_WRITE_BINDING, RESULTS_FIELD, google_ads_available
from .utils.label_associations import (
    MAX_LABEL_TARGETS_PER_CALL,
    MAX_LABELS_PER_CALL,
    label_association_selection,
    run_label_association_tool,
)


async def google_ads_apply_labels(
    ctx: RunContext[RuntimeDeps],
    labels: Annotated[
        list[GoogleAdsLabelReference],
        Field(
            min_length=1,
            max_length=MAX_LABELS_PER_CALL,
            description="Existing labels to attach.",
        ),
    ],
    targets: Annotated[
        list[GoogleAdsLabelTarget],
        Field(
            min_length=1,
            max_length=MAX_LABEL_TARGETS_PER_CALL,
            description="Campaigns, ad groups, or keywords, each tagged with its kind.",
        ),
    ],
) -> dict[str, Any]:
    return await run_label_association_tool(
        ctx, tool_name="google_ads_apply_labels", action="apply", labels=labels, targets=targets
    )


def _validate_args(
    _ctx: RunContext[RuntimeDeps],
    labels: list[GoogleAdsLabelReference],
    targets: list[GoogleAdsLabelTarget],
) -> None:
    label_association_selection(labels, targets)


DEFINITION = RuntimeToolDefinition(
    name="google_ads_apply_labels",
    function=google_ads_apply_labels,
    description=(
        "Attach existing labels to selected campaigns, ad groups, or positive keywords in "
        "Google Ads. Labels already attached are reported without a change. This tool "
        "doesn't create labels or choose targets."
    ),
    provider="google_ads",
    label="Apply Google Ads Labels",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=True,
    takes_ctx=True,
    args_validator=_validate_args,
    timeout=60,
    output_model=GoogleAdsApplyLabelsOutput,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Applying Labels",
        completed_label="Applied Labels",
        failed_label="Couldn't Apply Labels",
        approval_title="Apply Google Ads Labels",
        approval_prompt="The agent wants to attach labels to the selected items.",
        approve_label="Approve & Apply",
        result_fields=RESULTS_FIELD,
    ),
)
