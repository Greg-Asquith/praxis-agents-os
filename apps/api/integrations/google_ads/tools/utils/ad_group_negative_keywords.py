# apps/api/integrations/google_ads/tools/utils/ad_group_negative_keywords.py

"""Shared execution and result shaping for ad-group negative-keyword tools."""

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic_ai import ModelRetry, RunContext, ToolReturn

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

from ..verifiers import verify_ad_groups
from .audit import record_google_ads_operation_audit, run_audited_operation
from .bindings import GOOGLE_ADS_WRITE_BINDING
from .client import google_ads_client
from .fan_out import fan_out_tool_return
from .negative_keywords import normalize_negative_keywords
from .routing import login_customer_id

type AdGroupNegativeAction = Literal["add", "remove"]
type AdGroupNegativeKeyword = NegativeKeywordEntry | NegativeKeywordRemovalEntry

MAX_AD_GROUP_NEGATIVE_PUBLIC_RESULT_CHARS = 1_000_000
_MAX_MODEL_AD_GROUPS = 10
_MAX_ERRORS_PER_AD_GROUP = 3


async def run_ad_group_negative_keyword_tool(
    ctx: RunContext[RuntimeDeps],
    ad_group_ids: Sequence[GoogleAdsAdGroupReference],
    keywords: list[AdGroupNegativeKeyword],
    *,
    action: AdGroupNegativeAction,
) -> ToolReturn[dict[str, Any]]:
    normalized_keywords = normalize_negative_keywords(keywords)
    ad_groups = _deduplicate_ad_groups(ad_group_ids)

    async def operation(
        entry: ResolvedContextEntry,
        references: Sequence[ScopedEntityReference],
    ) -> Any:
        ad_group_references = [
            reference
            for reference in references
            if isinstance(reference, GoogleAdsAdGroupReference)
        ]
        if len(ad_group_references) != len(references) or not ad_group_references:
            raise ModelRetry("Choose the Google Ads ad groups again.")
        if len(ad_group_references) * len(normalized_keywords) > MAX_AD_GROUP_NEGATIVE_OPERATIONS:
            raise ModelRetry(
                "Ad groups multiplied by keyword rows must not exceed 2,500 per account. "
                "Split the request into smaller groups."
            )
        normalized_ad_group_ids = sorted(
            {reference.external_id for reference in ad_group_references}
        )
        if any(not ad_group_id.isdigit() for ad_group_id in normalized_ad_group_ids):
            raise ModelRetry("A selected Google Ads ad group reference is invalid.")

        async def execute() -> dict[str, Any]:
            client = await google_ads_client(ctx, entry)
            await verify_ad_groups(client, entry=entry, ad_group_ids=normalized_ad_group_ids)
            operation_fn = (
                add_ad_group_negative_keywords
                if action == "add"
                else remove_ad_group_negative_keywords
            )
            return await operation_fn(
                client,
                customer_id=entry.external_id,
                login_customer_id=login_customer_id(entry),
                ad_group_ids=normalized_ad_group_ids,
                keywords=[keyword.model_dump() for keyword in normalized_keywords],
            )

        operation_name = f"{action}_ad_group_negative_keywords"
        full_result = await run_audited_operation(
            ctx,
            entry,
            tool_name=f"google_ads_{operation_name}",
            operation=operation_name,
            execute=execute,
            external_ref_from_result=lambda value: _single_external_ref(value),
            operation_detail_from_result=lambda value: _operation_detail(
                entry, ad_group_references, action, value
            ),
            status_from_result=lambda value: _audit_status(action, value),
            pending_operation_detail=_pending_operation_detail(
                entry, ad_group_references, action, len(normalized_keywords)
            ),
            require_durable_audit=True,
        )
        return {
            "model_result": _ad_group_result(
                action,
                ad_group_references,
                full_result,
                max_ad_groups=_MAX_MODEL_AD_GROUPS,
            ),
            "display_result": _ad_group_result(
                action,
                ad_group_references,
                full_result,
                max_ad_groups=len(ad_group_references),
            ),
        }

    async def audit_write_denied(entry: ResolvedContextEntry) -> None:
        operation_name = f"{action}_ad_group_negative_keywords"
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
        references=ad_groups,
        operation=operation,
        write=True,
        on_write_denied=audit_write_denied,
    )
    return fan_out_tool_return(results)


def _deduplicate_ad_groups(
    ad_groups: Sequence[GoogleAdsAdGroupReference],
) -> list[GoogleAdsAdGroupReference]:
    unique: dict[tuple[object, str], GoogleAdsAdGroupReference] = {}
    for ad_group in ad_groups:
        unique.setdefault(
            (ad_group.integration_resource_id, ad_group.external_id),
            ad_group,
        )
    if not unique:
        raise ModelRetry("Choose at least one Google Ads ad group.")
    return list(unique.values())


def _audit_status(action: AdGroupNegativeAction, result: Mapping[str, Any]) -> AuditStatus:
    applied_key = "added" if action == "add" else "removed"
    if result.get("ad_group_errors") and not result.get(applied_key):
        return AuditStatus.FAILURE
    return AuditStatus.SUCCESS


def _pending_operation_detail(
    entry: ResolvedContextEntry,
    ad_groups: Sequence[GoogleAdsAdGroupReference],
    action: AdGroupNegativeAction,
    keyword_count: int,
) -> IntegrationOperationDetail:
    return IntegrationOperationDetail(
        target=_account_target(entry),
        changes=[
            IntegrationOperationChange(
                action=action,
                entity_type="ad_group_negative_keyword_batch",
                fields={
                    "ad_group_id": ad_group.external_id,
                    "ad_group_name": ad_group.label,
                    "campaign_name": ad_group.scope_label or "",
                    "keyword_count": keyword_count,
                },
            )
            for ad_group in ad_groups
        ],
        counts=IntegrationOperationCounts(applied=0, skipped=0, failed=0),
    )


def _operation_detail(
    entry: ResolvedContextEntry,
    ad_groups: Sequence[GoogleAdsAdGroupReference],
    action: AdGroupNegativeAction,
    result: Mapping[str, Any],
) -> IntegrationOperationDetail:
    applied_key = "added" if action == "add" else "removed"
    skipped_key = "skipped_existing" if action == "add" else "not_found"
    by_ad_group = _ad_group_counts(action, ad_groups, result)
    return IntegrationOperationDetail(
        target=_account_target(entry),
        changes=[
            IntegrationOperationChange(
                action=action,
                entity_type="ad_group_negative_keyword_batch",
                fields={
                    "ad_group_id": ad_group.external_id,
                    "ad_group_name": ad_group.label,
                    "campaign_name": ad_group.scope_label or "",
                    **by_ad_group[ad_group.external_id],
                },
            )
            for ad_group in ad_groups
        ],
        counts=IntegrationOperationCounts(
            applied=len(result.get(applied_key, [])),
            skipped=len(result.get(skipped_key, [])),
            failed=len(result.get("ad_group_errors", [])),
        ),
    )


def _account_target(entry: ResolvedContextEntry) -> IntegrationOperationTarget:
    return IntegrationOperationTarget(
        entity_type="google_ads_account",
        external_id=entry.external_id,
        display_name=entry.display_name,
        integration_resource_id=str(entry.integration_resource_id),
    )


def _ad_group_result(
    action: AdGroupNegativeAction,
    ad_groups: Sequence[GoogleAdsAdGroupReference],
    result: Mapping[str, Any],
    *,
    max_ad_groups: int,
) -> dict[str, Any]:
    applied_key = "added" if action == "add" else "removed"
    skipped_key = "skipped_existing" if action == "add" else "not_found"
    counts = _ad_group_counts(action, ad_groups, result)
    errors_by_ad_group: dict[str, list[dict[str, str]]] = {}
    for error in result.get("ad_group_errors", []):
        if not isinstance(error, Mapping):
            continue
        ad_group_id = str(error.get("ad_group_id", ""))
        errors_by_ad_group.setdefault(ad_group_id, []).append(
            {
                "text": str(error.get("text", ""))[:80],
                "match_type": str(error.get("match_type", ""))[:20],
                "message": str(error.get("message", ""))[:500],
                "error_code": str(error.get("error_code", "unknown"))[:100],
            }
        )
    ad_group_rows = []
    for ad_group in ad_groups[:max_ad_groups]:
        errors = errors_by_ad_group.get(ad_group.external_id, [])
        ad_group_rows.append(
            {
                "ad_group_id": ad_group.external_id,
                "ad_group_name": ad_group.label,
                "campaign_name": ad_group.scope_label or "",
                "counts": counts[ad_group.external_id],
                "ad_group_errors": errors[:_MAX_ERRORS_PER_AD_GROUP],
                "errors_truncated": len(errors) > _MAX_ERRORS_PER_AD_GROUP,
            }
        )
    return {
        "counts": {
            applied_key: len(result.get(applied_key, [])),
            skipped_key: len(result.get(skipped_key, [])),
            "failed": len(result.get("ad_group_errors", [])),
        },
        "ad_groups": ad_group_rows,
        "ad_groups_truncated": len(ad_groups) > len(ad_group_rows),
    }


def _ad_group_counts(
    action: AdGroupNegativeAction,
    ad_groups: Sequence[GoogleAdsAdGroupReference],
    result: Mapping[str, Any],
) -> dict[str, dict[str, int]]:
    applied_key = "added" if action == "add" else "removed"
    skipped_key = "skipped_existing" if action == "add" else "not_found"
    counts = {
        ad_group.external_id: {applied_key: 0, skipped_key: 0, "failed": 0}
        for ad_group in ad_groups
    }
    for key, items in (
        (applied_key, result.get(applied_key, [])),
        (skipped_key, result.get(skipped_key, [])),
        ("failed", result.get("ad_group_errors", [])),
    ):
        for item in items:
            if not isinstance(item, Mapping):
                continue
            ad_group_id = str(item.get("ad_group_id", ""))
            if ad_group_id in counts:
                counts[ad_group_id][key] += 1
    return counts


def _single_external_ref(result: Mapping[str, Any]) -> str | None:
    resource_names = result.get("resource_names")
    if isinstance(resource_names, list) and len(resource_names) == 1:
        resource_name = resource_names[0]
        return resource_name if isinstance(resource_name, str) else None
    return None
