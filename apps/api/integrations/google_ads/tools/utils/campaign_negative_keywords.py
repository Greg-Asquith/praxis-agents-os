# apps/api/integrations/google_ads/tools/utils/campaign_negative_keywords.py

"""Campaign negative-keyword execution adapter."""

from collections.abc import Sequence
from typing import Any

from pydantic_ai import RunContext, ToolReturn

from integrations.google_ads.client import GoogleAdsClient
from integrations.google_ads.operations.campaign_negative_keywords import (
    MAX_CAMPAIGN_NEGATIVE_OPERATIONS,
    add_campaign_negative_keywords,
    remove_campaign_negative_keywords,
)
from integrations.google_ads.operations.mutation_outcomes import GoogleAdsMutationLedger
from integrations.google_ads.references import GoogleAdsCampaignReference
from integrations.google_ads.tools.schemas.negative_keyword import (
    NegativeKeywordEntry,
    NegativeKeywordRemovalEntry,
)
from services.agents.runtime.context import RuntimeDeps
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.entity_references import ScopedEntityReference

from ..verifiers import verify_campaigns
from .bindings import GOOGLE_ADS_WRITE_BINDING
from .negative_keyword_tools import (
    MAX_SCOPED_NEGATIVE_PUBLIC_RESULT_CHARS,
    NegativeKeywordAction,
    NegativeKeywordToolSpec,
    run_negative_keyword_tool,
)
from .routing import login_customer_id

MAX_CAMPAIGN_NEGATIVE_PUBLIC_RESULT_CHARS = MAX_SCOPED_NEGATIVE_PUBLIC_RESULT_CHARS


async def run_campaign_negative_keyword_tool(
    ctx: RunContext[RuntimeDeps],
    campaign_ids: Sequence[GoogleAdsCampaignReference],
    keywords: list[NegativeKeywordEntry | NegativeKeywordRemovalEntry],
    *,
    action: NegativeKeywordAction,
) -> ToolReturn[dict[str, Any]]:
    return await run_negative_keyword_tool(
        ctx,
        campaign_ids,
        keywords,
        action=action,
        spec=CAMPAIGN_NEGATIVE_KEYWORD_TOOL_SPEC,
    )


async def _verify_targets(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    campaign_ids: list[str],
) -> None:
    await verify_campaigns(client, entry=entry, campaign_ids=campaign_ids, ignore_removed=True)


async def _mutate_targets(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    campaign_ids: list[str],
    keywords: list[dict[str, str]],
    action: NegativeKeywordAction,
) -> GoogleAdsMutationLedger:
    operation = (
        add_campaign_negative_keywords if action == "add" else remove_campaign_negative_keywords
    )
    return await operation(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        campaign_ids=campaign_ids,
        keywords=keywords,
    )


def _reference_fields(reference: ScopedEntityReference) -> dict[str, str]:
    return {
        "campaign_id": reference.campaign_id,
        "campaign_name": reference.label,
    }


CAMPAIGN_NEGATIVE_KEYWORD_TOOL_SPEC = NegativeKeywordToolSpec(
    reference_type=GoogleAdsCampaignReference,
    entity_id_key="campaign_id",
    errors_key="campaign_errors",
    collection_key="campaigns",
    truncated_key="campaigns_truncated",
    entity_type="campaign_negative_keyword_batch",
    operation_entity="campaign",
    selection_label="campaign",
    selection_plural_label="campaigns",
    max_operations=MAX_CAMPAIGN_NEGATIVE_OPERATIONS,
    binding=GOOGLE_ADS_WRITE_BINDING,
    reference_fields=_reference_fields,
    verify_targets=_verify_targets,
    mutate_targets=_mutate_targets,
)
