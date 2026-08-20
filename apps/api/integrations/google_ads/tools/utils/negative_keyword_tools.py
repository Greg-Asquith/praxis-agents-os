# apps/api/integrations/google_ads/tools/utils/negative_keyword_tools.py

"""Shared execution, result, and audit mechanics for scoped negative keywords."""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic_ai import ModelRetry, RunContext, ToolReturn

from integrations.google_ads.client import GoogleAdsClient
from integrations.google_ads.operations.mutation_outcomes import GoogleAdsMutationLedger
from integrations.google_ads.tools.schemas.negative_keyword import (
    NegativeKeywordEntry,
    NegativeKeywordRemovalEntry,
)
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import IntegrationToolBinding
from services.audit_events import (
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    IntegrationOperationTarget,
    PendingIntegrationOperationDetail,
)
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.targeted import run_context_targets
from services.integrations.entity_references import ScopedEntityReference
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from .client import google_ads_client
from .fan_out import fan_out_tool_return
from .mutation_evidence import audit_status, terminal_operation_detail
from .negative_keywords import normalize_negative_keywords

type NegativeKeywordAction = Literal["add", "remove"]
type NegativeKeywordRow = NegativeKeywordEntry | NegativeKeywordRemovalEntry
type VerifyTargets = Callable[[GoogleAdsClient, ResolvedContextEntry, list[str]], Awaitable[None]]
type MutateTargets = Callable[
    [GoogleAdsClient, ResolvedContextEntry, list[str], list[dict[str, str]], NegativeKeywordAction],
    Awaitable[GoogleAdsMutationLedger],
]
type ReferenceFields = Callable[[ScopedEntityReference], dict[str, str]]

MAX_SCOPED_NEGATIVE_PUBLIC_RESULT_CHARS = 1_000_000
_MAX_MODEL_ENTITIES = 10
_MAX_ERRORS_PER_ENTITY = 3


@dataclass(frozen=True, slots=True)
class NegativeKeywordToolSpec:
    """Entity policy retained by campaign and ad-group execution adapters."""

    reference_type: type[ScopedEntityReference]
    entity_id_key: Literal["campaign_id", "ad_group_id"]
    errors_key: Literal["campaign_errors", "ad_group_errors"]
    collection_key: Literal["campaigns", "ad_groups"]
    truncated_key: Literal["campaigns_truncated", "ad_groups_truncated"]
    entity_type: Literal["campaign_negative_keyword_batch", "ad_group_negative_keyword_batch"]
    operation_entity: Literal["campaign", "ad_group"]
    selection_label: Literal["campaign", "ad group"]
    selection_plural_label: Literal["campaigns", "ad groups"]
    max_operations: int
    binding: IntegrationToolBinding
    reference_fields: ReferenceFields
    verify_targets: VerifyTargets
    mutate_targets: MutateTargets


async def run_negative_keyword_tool(
    ctx: RunContext[RuntimeDeps],
    references: Sequence[ScopedEntityReference],
    keywords: list[NegativeKeywordRow],
    *,
    action: NegativeKeywordAction,
    spec: NegativeKeywordToolSpec,
) -> ToolReturn[dict[str, Any]]:
    normalized_keywords = normalize_negative_keywords(keywords)
    targets = _deduplicate_references(references, spec=spec)

    async def operation(
        entry: ResolvedContextEntry,
        scoped_references: Sequence[ScopedEntityReference],
    ) -> Any:
        entity_references = [
            reference
            for reference in scoped_references
            if isinstance(reference, spec.reference_type)
        ]
        if len(entity_references) != len(scoped_references) or not entity_references:
            raise ModelRetry(f"Choose the Google Ads {spec.selection_plural_label} again.")
        if len(entity_references) * len(normalized_keywords) > spec.max_operations:
            raise ModelRetry(
                f"{spec.selection_plural_label.capitalize()} multiplied by keyword rows must not "
                f"exceed {spec.max_operations:,} per account. Split the request into smaller groups."
            )
        normalized_entity_ids = sorted(
            {reference.provider_entity_id for reference in entity_references}
        )
        if any(not entity_id.isdigit() for entity_id in normalized_entity_ids):
            raise ModelRetry(f"A selected Google Ads {spec.selection_label} reference is invalid.")

        keyword_values = [keyword.model_dump() for keyword in normalized_keywords]
        pending_detail = pending_operation_detail(
            entry,
            entity_references,
            action,
            keyword_values,
            spec=spec,
        )

        async def execute() -> IntegrationAuditOutcome[dict[str, Any]]:
            client = await google_ads_client(ctx, entry)
            await spec.verify_targets(client, entry, normalized_entity_ids)
            ledger = await spec.mutate_targets(
                client,
                entry,
                normalized_entity_ids,
                keyword_values,
                action,
            )
            operation_evidence = terminal_operation_detail(pending_detail, ledger)
            return IntegrationAuditOutcome(
                ledger,
                status=audit_status(operation_evidence),
                external_ref=_single_external_ref(ledger),
                operation_detail=operation_evidence,
            )

        operation_name = f"{action}_{spec.operation_entity}_negative_keywords"
        full_ledger = await run_audited_integration_operation(
            ctx,
            entry,
            tool_name=f"google_ads_{operation_name}",
            operation=operation_name,
            execute=execute,
            pending_operation_detail=pending_detail,
        )
        return {
            "model_result": entity_result(
                action,
                entity_references,
                full_ledger,
                max_entities=_MAX_MODEL_ENTITIES,
                include_keyword_outcomes=False,
                spec=spec,
            ),
            "display_result": entity_result(
                action,
                entity_references,
                full_ledger,
                max_entities=len(entity_references),
                include_keyword_outcomes=True,
                spec=spec,
            ),
        }

    results = await run_context_targets(
        ctx,
        binding=spec.binding,
        references=targets,
        operation=operation,
    )
    return fan_out_tool_return(results)


def pending_operation_detail(
    entry: ResolvedContextEntry,
    references: Sequence[ScopedEntityReference],
    action: NegativeKeywordAction,
    keywords: Sequence[Mapping[str, str]],
    *,
    spec: NegativeKeywordToolSpec,
) -> PendingIntegrationOperationDetail:
    """Build the pre-dispatch audit detail for a scoped keyword mutation."""
    return PendingIntegrationOperationDetail(
        target=_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key=(f"{spec.operation_entity}:{reference.provider_entity_id}:{action}-keywords"),
                action=action,
                entity_type=spec.entity_type,
                external_id=reference.provider_entity_id,
                display_name=reference.label,
                fields=spec.reference_fields(reference),
                items=[
                    IntegrationOperationIntent(
                        fields={spec.entity_id_key: reference.provider_entity_id, **keyword}
                    )
                    for keyword in keywords
                ],
            )
            for reference in references
        ],
    )


def entity_result(
    action: NegativeKeywordAction,
    references: Sequence[ScopedEntityReference],
    result: GoogleAdsMutationLedger,
    *,
    max_entities: int,
    include_keyword_outcomes: bool,
    spec: NegativeKeywordToolSpec,
) -> dict[str, Any]:
    """Build bounded model or display output from the mutation ledger."""
    applied_key = "added" if action == "add" else "removed"
    skipped_key = "skipped_existing" if action == "add" else "not_found"
    counts = _entity_counts(action, references, result, spec=spec)
    outcomes = (
        result.keyword_outcomes(entity_id_key=spec.entity_id_key)
        if include_keyword_outcomes
        else {}
    )
    errors_by_entity: dict[str, list[dict[str, str]]] = {}
    for error in result.get(spec.errors_key, []):
        if not isinstance(error, Mapping):
            continue
        entity_id = str(error.get(spec.entity_id_key, ""))
        errors_by_entity.setdefault(entity_id, []).append(
            {
                "text": str(error.get("text", ""))[:80],
                "match_type": str(error.get("match_type", ""))[:20],
                "message": str(error.get("message", ""))[:500],
                "error_code": str(error.get("error_code", "unknown"))[:100],
            }
        )
    entity_rows = []
    for reference in references[:max_entities]:
        errors = errors_by_entity.get(reference.provider_entity_id, [])
        entity_row: dict[str, Any] = {
            **spec.reference_fields(reference),
            "counts": counts[reference.provider_entity_id],
            spec.errors_key: errors[:_MAX_ERRORS_PER_ENTITY],
            "errors_truncated": len(errors) > _MAX_ERRORS_PER_ENTITY,
        }
        if include_keyword_outcomes:
            entity_row["keyword_outcomes"] = outcomes[reference.provider_entity_id]
        entity_rows.append(entity_row)
    return {
        "counts": {
            applied_key: len(result.get(applied_key, [])),
            skipped_key: len(result.get(skipped_key, [])),
            "failed": len(result.get(spec.errors_key, [])),
        },
        spec.collection_key: entity_rows,
        spec.truncated_key: len(references) > len(entity_rows),
    }


def _deduplicate_references(
    references: Sequence[ScopedEntityReference],
    *,
    spec: NegativeKeywordToolSpec,
) -> list[ScopedEntityReference]:
    unique: dict[tuple[str, str], ScopedEntityReference] = {}
    for reference in references:
        unique.setdefault(
            (reference.provider_scope_id, reference.provider_entity_id),
            reference,
        )
    if not unique:
        raise ModelRetry(f"Choose at least one Google Ads {spec.selection_label}.")
    return list(unique.values())


def _account_target(
    entry: ResolvedContextEntry,
) -> IntegrationOperationTarget:
    return IntegrationOperationTarget(
        entity_type="google_ads_account",
        external_id=entry.external_id,
        display_name=entry.display_name,
        integration_resource_id=str(entry.integration_resource_id),
    )


def _entity_counts(
    action: NegativeKeywordAction,
    references: Sequence[ScopedEntityReference],
    result: GoogleAdsMutationLedger,
    *,
    spec: NegativeKeywordToolSpec,
) -> dict[str, dict[str, int]]:
    applied_key = "added" if action == "add" else "removed"
    skipped_key = "skipped_existing" if action == "add" else "not_found"
    counts = {
        reference.provider_entity_id: {applied_key: 0, skipped_key: 0, "failed": 0}
        for reference in references
    }
    for key, items in (
        (applied_key, result.get(applied_key, [])),
        (skipped_key, result.get(skipped_key, [])),
        ("failed", result.get(spec.errors_key, [])),
    ):
        for item in items:
            if not isinstance(item, Mapping):
                continue
            entity_id = str(item.get(spec.entity_id_key, ""))
            if entity_id in counts:
                counts[entity_id][key] += 1
    return counts


def _single_external_ref(result: GoogleAdsMutationLedger) -> str | None:
    resource_names = result.get("resource_names")
    if isinstance(resource_names, list) and len(resource_names) == 1:
        resource_name = resource_names[0]
        return resource_name if isinstance(resource_name, str) else None
    return None
