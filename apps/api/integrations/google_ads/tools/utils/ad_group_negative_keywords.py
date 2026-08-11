# apps/api/integrations/google_ads/tools/utils/ad_group_negative_keywords.py

"""Ad-group negative-keyword execution adapter."""

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic_ai import RunContext, ToolReturn

from integrations.google_ads.client import GoogleAdsClient
from integrations.google_ads.operations.ad_group_negative_keywords import (
    MAX_AD_GROUP_NEGATIVE_OPERATIONS,
    add_ad_group_negative_keywords,
    remove_ad_group_negative_keywords,
)
from integrations.google_ads.references import GoogleAdsAdGroupReference
from integrations.google_ads.tools.schemas.negative_keyword import (
    NegativeKeywordEntry,
    NegativeKeywordRemovalEntry,
)
from services.agents.runtime.context import RuntimeDeps
from services.audit_events import IntegrationOperationDetail
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.entity_references import ScopedEntityReference

from ..verifiers import verify_ad_groups
from .bindings import GOOGLE_ADS_WRITE_BINDING
from .negative_keyword_tools import (
    MAX_SCOPED_NEGATIVE_PUBLIC_RESULT_CHARS,
    NegativeKeywordAction,
    NegativeKeywordToolSpec,
    entity_result,
    operation_detail,
    pending_operation_detail,
    run_negative_keyword_tool,
)
from .routing import login_customer_id

MAX_AD_GROUP_NEGATIVE_PUBLIC_RESULT_CHARS = MAX_SCOPED_NEGATIVE_PUBLIC_RESULT_CHARS


async def run_ad_group_negative_keyword_tool(
    ctx: RunContext[RuntimeDeps],
    ad_group_ids: Sequence[GoogleAdsAdGroupReference],
    keywords: list[NegativeKeywordEntry | NegativeKeywordRemovalEntry],
    *,
    action: NegativeKeywordAction,
) -> ToolReturn[dict[str, Any]]:
    return await run_negative_keyword_tool(
        ctx,
        ad_group_ids,
        keywords,
        action=action,
        spec=_AD_GROUP_SPEC,
    )


def _pending_operation_detail(
    entry: ResolvedContextEntry,
    ad_groups: Sequence[GoogleAdsAdGroupReference],
    action: NegativeKeywordAction,
    keywords: Sequence[Mapping[str, str]],
) -> IntegrationOperationDetail:
    return pending_operation_detail(entry, ad_groups, action, keywords, spec=_AD_GROUP_SPEC)


def _operation_detail(
    entry: ResolvedContextEntry,
    ad_groups: Sequence[GoogleAdsAdGroupReference],
    keywords: Sequence[Mapping[str, str]],
    action: NegativeKeywordAction,
    result: Mapping[str, Any],
) -> IntegrationOperationDetail:
    return operation_detail(entry, ad_groups, keywords, action, result, spec=_AD_GROUP_SPEC)


def _ad_group_result(
    action: NegativeKeywordAction,
    ad_groups: Sequence[GoogleAdsAdGroupReference],
    result: Mapping[str, Any],
    *,
    max_ad_groups: int,
    keywords: Sequence[Mapping[str, str]] = (),
    include_keyword_outcomes: bool,
) -> dict[str, Any]:
    return entity_result(
        action,
        ad_groups,
        result,
        max_entities=max_ad_groups,
        keywords=keywords,
        include_keyword_outcomes=include_keyword_outcomes,
        spec=_AD_GROUP_SPEC,
    )


async def _verify_targets(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    ad_group_ids: list[str],
) -> None:
    await verify_ad_groups(client, entry=entry, ad_group_ids=ad_group_ids)


async def _mutate_targets(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    ad_group_ids: list[str],
    keywords: list[dict[str, str]],
    action: NegativeKeywordAction,
) -> dict[str, Any]:
    operation = (
        add_ad_group_negative_keywords if action == "add" else remove_ad_group_negative_keywords
    )
    return await operation(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        ad_group_ids=ad_group_ids,
        keywords=keywords,
    )


def _reference_fields(reference: ScopedEntityReference) -> dict[str, str]:
    return {
        "ad_group_id": reference.external_id,
        "ad_group_name": reference.label,
        "campaign_name": reference.scope_label or "",
    }


_AD_GROUP_SPEC = NegativeKeywordToolSpec(
    reference_type=GoogleAdsAdGroupReference,
    entity_id_key="ad_group_id",
    errors_key="ad_group_errors",
    collection_key="ad_groups",
    truncated_key="ad_groups_truncated",
    entity_type="ad_group_negative_keyword_batch",
    operation_entity="ad_group",
    selection_label="ad group",
    selection_plural_label="ad groups",
    max_operations=MAX_AD_GROUP_NEGATIVE_OPERATIONS,
    binding=GOOGLE_ADS_WRITE_BINDING,
    reference_fields=_reference_fields,
    verify_targets=_verify_targets,
    mutate_targets=_mutate_targets,
)
