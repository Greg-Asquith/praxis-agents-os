# apps/api/integrations/google_ads/tools/utils/campaign_negative_keywords.py

"""Shared execution and result shaping for campaign negative-keyword tools."""

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic_ai import ModelRetry, RunContext, ToolReturn

from integrations.google_ads.operations.campaign_negative_keywords import (
    MAX_CAMPAIGN_NEGATIVE_OPERATIONS,
    add_campaign_negative_keywords,
    remove_campaign_negative_keywords,
)
from integrations.google_ads.references import GoogleAdsCampaignReference
from integrations.google_ads.tools.schemas.negative_keyword import (
    NegativeKeywordEntry,
    NegativeKeywordRemovalEntry,
)
from services.agents.runtime.context import RuntimeDeps
from services.audit_events import (
    AuditStatus,
    IntegrationOperationChange,
    IntegrationOperationCounts,
    IntegrationOperationDetail,
    IntegrationOperationTarget,
)
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.targeted import run_context_targets
from services.integrations.entity_references import ScopedEntityReference

from ..verifiers import verify_campaigns
from .audit import record_google_ads_operation_audit, run_audited_operation
from .bindings import GOOGLE_ADS_WRITE_BINDING
from .client import google_ads_client
from .fan_out import fan_out_tool_return
from .negative_keyword_evidence import exact_negative_keyword_outcomes
from .negative_keywords import normalize_negative_keywords
from .routing import login_customer_id

type CampaignNegativeAction = Literal["add", "remove"]
type CampaignNegativeKeyword = NegativeKeywordEntry | NegativeKeywordRemovalEntry

MAX_CAMPAIGN_NEGATIVE_PUBLIC_RESULT_CHARS = 1_000_000
_MAX_MODEL_CAMPAIGNS = 10
_MAX_ERRORS_PER_CAMPAIGN = 3


async def run_campaign_negative_keyword_tool(
    ctx: RunContext[RuntimeDeps],
    campaign_ids: Sequence[GoogleAdsCampaignReference],
    keywords: list[CampaignNegativeKeyword],
    *,
    action: CampaignNegativeAction,
) -> ToolReturn[dict[str, Any]]:
    normalized_keywords = normalize_negative_keywords(keywords)
    campaigns = _deduplicate_campaigns(campaign_ids)

    async def operation(
        entry: ResolvedContextEntry,
        references: Sequence[ScopedEntityReference],
    ) -> Any:
        campaign_references = [
            reference
            for reference in references
            if isinstance(reference, GoogleAdsCampaignReference)
        ]
        if len(campaign_references) != len(references) or not campaign_references:
            raise ModelRetry("Choose the Google Ads campaigns again.")
        if len(campaign_references) * len(normalized_keywords) > MAX_CAMPAIGN_NEGATIVE_OPERATIONS:
            raise ModelRetry(
                "Campaigns multiplied by keyword rows must not exceed 2,500 per account. "
                "Split the request into smaller groups."
            )
        normalized_campaign_ids = sorted(
            {reference.external_id for reference in campaign_references}
        )
        if any(not campaign_id.isdigit() for campaign_id in normalized_campaign_ids):
            raise ModelRetry("A selected Google Ads campaign reference is invalid.")

        async def execute() -> dict[str, Any]:
            client = await google_ads_client(ctx, entry)
            await verify_campaigns(
                client,
                entry=entry,
                campaign_ids=normalized_campaign_ids,
                ignore_removed=True,
            )
            operation_fn = (
                add_campaign_negative_keywords
                if action == "add"
                else remove_campaign_negative_keywords
            )
            return await operation_fn(
                client,
                customer_id=entry.external_id,
                login_customer_id=login_customer_id(entry),
                campaign_ids=normalized_campaign_ids,
                keywords=[keyword.model_dump() for keyword in normalized_keywords],
            )

        operation_name = f"{action}_campaign_negative_keywords"
        full_result = await run_audited_operation(
            ctx,
            entry,
            tool_name=f"google_ads_{operation_name}",
            operation=operation_name,
            execute=execute,
            external_ref_from_result=lambda value: _single_external_ref(value),
            operation_detail_from_result=lambda value: _operation_detail(
                entry,
                campaign_references,
                [keyword.model_dump() for keyword in normalized_keywords],
                action,
                value,
            ),
            status_from_result=lambda value: _audit_status(action, value),
            pending_operation_detail=_pending_operation_detail(
                entry,
                campaign_references,
                action,
                [keyword.model_dump() for keyword in normalized_keywords],
            ),
            require_durable_audit=True,
        )
        return {
            "model_result": _campaign_result(
                action,
                campaign_references,
                full_result,
                max_campaigns=_MAX_MODEL_CAMPAIGNS,
                include_keyword_outcomes=False,
            ),
            "display_result": _campaign_result(
                action,
                campaign_references,
                full_result,
                max_campaigns=len(campaign_references),
                keywords=[keyword.model_dump() for keyword in normalized_keywords],
                include_keyword_outcomes=True,
            ),
        }

    async def audit_write_denied(entry: ResolvedContextEntry) -> None:
        operation_name = f"{action}_campaign_negative_keywords"
        await record_google_ads_operation_audit(
            ctx,
            entry,
            tool_name=f"google_ads_{operation_name}",
            operation=operation_name,
            status=AuditStatus.FAILURE,
            error_code="write_not_permitted",
        )

    results = await run_context_targets(
        ctx.deps,
        binding=GOOGLE_ADS_WRITE_BINDING,
        references=campaigns,
        operation=operation,
        write=True,
        on_write_denied=audit_write_denied,
    )
    return fan_out_tool_return(results)


def _deduplicate_campaigns(
    campaigns: Sequence[GoogleAdsCampaignReference],
) -> list[GoogleAdsCampaignReference]:
    unique: dict[tuple[object, str], GoogleAdsCampaignReference] = {}
    for campaign in campaigns:
        unique.setdefault(
            (campaign.integration_resource_id, campaign.external_id),
            campaign,
        )
    if not unique:
        raise ModelRetry("Choose at least one Google Ads campaign.")
    return list(unique.values())


def _audit_status(action: CampaignNegativeAction, result: Mapping[str, Any]) -> AuditStatus:
    applied_key = "added" if action == "add" else "removed"
    if result.get("campaign_errors") and not result.get(applied_key):
        return AuditStatus.FAILURE
    return AuditStatus.SUCCESS


def _pending_operation_detail(
    entry: ResolvedContextEntry,
    campaigns: Sequence[GoogleAdsCampaignReference],
    action: CampaignNegativeAction,
    keywords: Sequence[Mapping[str, str]],
) -> IntegrationOperationDetail:
    return IntegrationOperationDetail(
        target=_account_target(entry, requested_keywords=keywords),
        changes=[
            IntegrationOperationChange(
                action=action,
                entity_type="campaign_negative_keyword_batch",
                fields={
                    "campaign_id": campaign.external_id,
                    "campaign_name": campaign.label,
                    "keyword_count": len(keywords),
                },
            )
            for campaign in campaigns
        ],
        counts=IntegrationOperationCounts(applied=0, skipped=0, failed=0),
    )


def _operation_detail(
    entry: ResolvedContextEntry,
    campaigns: Sequence[GoogleAdsCampaignReference],
    keywords: Sequence[Mapping[str, str]],
    action: CampaignNegativeAction,
    result: Mapping[str, Any],
) -> IntegrationOperationDetail:
    applied_key = "added" if action == "add" else "removed"
    skipped_key = "skipped_existing" if action == "add" else "not_found"
    by_campaign = _campaign_counts(action, campaigns, result)
    outcomes = exact_negative_keyword_outcomes(
        action=action,
        entity_id_key="campaign_id",
        entity_ids=[campaign.external_id for campaign in campaigns],
        keywords=keywords,
        result=result,
        errors_key="campaign_errors",
    )
    return IntegrationOperationDetail(
        target=_account_target(entry),
        changes=[
            IntegrationOperationChange(
                action=action,
                entity_type="campaign_negative_keyword_batch",
                fields={
                    "campaign_id": campaign.external_id,
                    "campaign_name": campaign.label,
                    **by_campaign[campaign.external_id],
                    "keyword_outcomes": outcomes[campaign.external_id],
                },
            )
            for campaign in campaigns
        ],
        counts=IntegrationOperationCounts(
            applied=len(result.get(applied_key, [])),
            skipped=len(result.get(skipped_key, [])),
            failed=len(result.get("campaign_errors", [])),
        ),
    )


def _account_target(
    entry: ResolvedContextEntry,
    *,
    requested_keywords: Sequence[Mapping[str, str]] = (),
) -> IntegrationOperationTarget:
    return IntegrationOperationTarget(
        entity_type="google_ads_account",
        external_id=entry.external_id,
        display_name=entry.display_name,
        integration_resource_id=str(entry.integration_resource_id),
        attributes={"requested_keywords": [dict(keyword) for keyword in requested_keywords]},
    )


def _campaign_result(
    action: CampaignNegativeAction,
    campaigns: Sequence[GoogleAdsCampaignReference],
    result: Mapping[str, Any],
    *,
    max_campaigns: int,
    keywords: Sequence[Mapping[str, str]] = (),
    include_keyword_outcomes: bool,
) -> dict[str, Any]:
    applied_key = "added" if action == "add" else "removed"
    skipped_key = "skipped_existing" if action == "add" else "not_found"
    counts = _campaign_counts(action, campaigns, result)
    outcomes = (
        exact_negative_keyword_outcomes(
            action=action,
            entity_id_key="campaign_id",
            entity_ids=[campaign.external_id for campaign in campaigns],
            keywords=keywords,
            result=result,
            errors_key="campaign_errors",
        )
        if include_keyword_outcomes
        else {}
    )
    errors_by_campaign: dict[str, list[dict[str, str]]] = {}
    for error in result.get("campaign_errors", []):
        if not isinstance(error, Mapping):
            continue
        campaign_id = str(error.get("campaign_id", ""))
        errors_by_campaign.setdefault(campaign_id, []).append(
            {
                "text": str(error.get("text", ""))[:80],
                "match_type": str(error.get("match_type", ""))[:20],
                "message": str(error.get("message", ""))[:500],
                "error_code": str(error.get("error_code", "unknown"))[:100],
            }
        )
    campaign_rows = []
    for campaign in campaigns[:max_campaigns]:
        errors = errors_by_campaign.get(campaign.external_id, [])
        campaign_row = {
            "campaign_id": campaign.external_id,
            "campaign_name": campaign.label,
            "counts": counts[campaign.external_id],
            "campaign_errors": errors[:_MAX_ERRORS_PER_CAMPAIGN],
            "errors_truncated": len(errors) > _MAX_ERRORS_PER_CAMPAIGN,
        }
        if include_keyword_outcomes:
            campaign_row["keyword_outcomes"] = outcomes[campaign.external_id]
        campaign_rows.append(campaign_row)
    return {
        "counts": {
            applied_key: len(result.get(applied_key, [])),
            skipped_key: len(result.get(skipped_key, [])),
            "failed": len(result.get("campaign_errors", [])),
        },
        "campaigns": campaign_rows,
        "campaigns_truncated": len(campaigns) > len(campaign_rows),
    }


def _campaign_counts(
    action: CampaignNegativeAction,
    campaigns: Sequence[GoogleAdsCampaignReference],
    result: Mapping[str, Any],
) -> dict[str, dict[str, int]]:
    applied_key = "added" if action == "add" else "removed"
    skipped_key = "skipped_existing" if action == "add" else "not_found"
    counts = {
        campaign.external_id: {applied_key: 0, skipped_key: 0, "failed": 0}
        for campaign in campaigns
    }
    for key, items in (
        (applied_key, result.get(applied_key, [])),
        (skipped_key, result.get(skipped_key, [])),
        ("failed", result.get("campaign_errors", [])),
    ):
        for item in items:
            if not isinstance(item, Mapping):
                continue
            campaign_id = str(item.get("campaign_id", ""))
            if campaign_id in counts:
                counts[campaign_id][key] += 1
    return counts


def _single_external_ref(result: Mapping[str, Any]) -> str | None:
    resource_names = result.get("resource_names")
    if isinstance(resource_names, list) and len(resource_names) == 1:
        resource_name = resource_names[0]
        return resource_name if isinstance(resource_name, str) else None
    return None
