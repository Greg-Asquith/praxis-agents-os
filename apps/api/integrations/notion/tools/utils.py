# apps/api/integrations/notion/tools/utils.py

"""Shared Notion tool binding and credential access."""

import asyncio
from collections.abc import Mapping
from typing import Any, Literal

from pydantic_ai import ModelRetry, RunContext

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationConnectionError,
    IntegrationError,
    IntegrationFailureDisposition,
    IntegrationNotFoundError,
    IntegrationPermissionError,
    IntegrationRateLimitError,
    IntegrationTimeoutError,
    IntegrationValidationError,
)
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    IntegrationToolBinding,
    ToolFieldPresentation,
)
from services.audit_events import (
    AuditStatus,
    IntegrationOperationCounts,
    IntegrationOperationEffect,
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    IntegrationOperationOutcome,
    IntegrationOperationOutcomeGroup,
    IntegrationOperationTarget,
    PendingIntegrationOperationDetail,
    TerminalIntegrationOperationDetail,
    terminal_applied_operation_detail,
)
from services.integrations.connections.utils import refresh_oauth_credential
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import (
    IntegrationContextResult,
    serialize_fan_out_results,
)
from services.integrations.credentials import (
    ensure_fresh_credential,
    get_usable_connection_credential,
)
from services.integrations.operations import IntegrationAuditOutcome

from ..client import NotionClient
from ..operations.create_page import CreatePagePreparation
from ..operations.properties import NotionMutationTarget
from ..operations.update_page_markdown import (
    MULTIPLE_MATCHES_ERROR_MESSAGE,
    NO_MATCH_ERROR_MESSAGE,
    UpdatePageMarkdownPreparation,
)
from ..operations.update_page_properties import UpdatePagePropertiesPreparation
from ..operations.utils import serialized_json_bytes
from ..settings import notion_settings

NOTION_BINDING = IntegrationToolBinding(
    provider_keys=frozenset({"notion"}),
    resource_types=frozenset({"notion_workspace"}),
)
NOTION_WRITE_BINDING = IntegrationToolBinding(
    provider_keys=NOTION_BINDING.provider_keys,
    resource_types=NOTION_BINDING.resource_types,
    requires_write=True,
)
RESULTS_FIELD = (ToolFieldPresentation(key="results", label="Workspaces", format="list"),)
MAX_NOTION_RESULT_BYTES = 768 * 1024


def bounded_notion_output(results: list[IntegrationContextResult]) -> dict[str, object]:
    """Returns a Notion result only when its complete serialized value is bounded."""
    output: dict[str, object] = {"results": serialize_fan_out_results(results)}
    if serialized_json_bytes(output) > MAX_NOTION_RESULT_BYTES:
        raise ModelRetry("Notion returned too much data. Retry with a lower maximum result count.")
    return output


async def notion_client(
    ctx: RunContext[RuntimeDeps],
    entry: ResolvedContextEntry,
) -> NotionClient:
    return await notion_client_for_principal(
        ctx.deps.db,
        actor=ctx.deps.user,
        workspace=ctx.deps.workspace,
        entry=entry,
    )


async def notion_client_for_principal(
    db, *, actor, workspace, entry: ResolvedContextEntry
) -> NotionClient:
    async def access_token(force: bool) -> str:
        usable = await get_usable_connection_credential(
            db,
            connection_id=entry.connection_id,
            actor=actor,
            workspace=workspace,
        )
        credential = await ensure_fresh_credential(
            db,
            credential_id=usable.id,
            refresh_token=refresh_oauth_credential,
            force=force,
        )
        token = credential.access_token
        if not token:
            raise ModelRetry("The Notion connection needs to be reconnected.")
        return token

    return NotionClient(access_token, pacing_key=str(entry.connection_id))


def notion_available() -> bool:
    return bool(notion_settings.NOTION_OAUTH_CLIENT_ID.strip())


def notion_page_target(
    entry: ResolvedContextEntry,
    page: NotionMutationTarget,
) -> IntegrationOperationTarget:
    """Builds the provider page target used by Notion write evidence."""
    return _notion_target(entry, page)


def pending_create_page_detail(
    entry: ResolvedContextEntry,
    prepared: CreatePagePreparation,
) -> PendingIntegrationOperationDetail:
    """Builds bounded intent for one page creation."""
    return PendingIntegrationOperationDetail(
        target=_notion_target(entry, prepared.parent),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key="page:create",
                action="create_page",
                entity_type="notion_page",
                items=[
                    IntegrationOperationIntent(
                        fields={
                            "title": prepared.title,
                            "content_bytes": len(prepared.content_md.encode("utf-8")),
                            "property_count": prepared.property_count,
                        }
                    )
                ],
            )
        ],
    )


def pending_update_content_detail(
    entry: ResolvedContextEntry,
    prepared: UpdatePageMarkdownPreparation,
) -> PendingIntegrationOperationDetail:
    """Builds bounded intent for exact-text page replacements."""
    return PendingIntegrationOperationDetail(
        target=notion_page_target(entry, prepared.page),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key=f"page:{prepared.page.external_id}:content",
                action="update_content",
                entity_type="notion_page",
                external_id=prepared.page.external_id,
                display_name=prepared.page.display_name,
                items=[
                    IntegrationOperationIntent(
                        fields={
                            "old_text": record.old_text[:1_000],
                            "new_text": record.new_text[:1_000],
                            "old_text_length": len(record.old_text),
                            "new_text_length": len(record.new_text),
                            "replace_all": record.replace_all,
                        }
                    )
                    for record in prepared.replacements
                ],
            )
        ],
    )


def pending_update_properties_detail(
    entry: ResolvedContextEntry,
    prepared: UpdatePagePropertiesPreparation,
) -> PendingIntegrationOperationDetail:
    """Builds bounded intent for schema-validated page properties."""
    return PendingIntegrationOperationDetail(
        target=notion_page_target(entry, prepared.page),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key=f"page:{prepared.page.external_id}:properties",
                action="update_properties",
                entity_type="notion_page",
                external_id=prepared.page.external_id,
                display_name=prepared.page.display_name,
                items=[
                    IntegrationOperationIntent(
                        fields={
                            "name": record.name,
                            "type": record.type,
                            "value": record.value[:1_000],
                        }
                    )
                    for record in prepared.records
                ],
            )
        ],
    )


def terminal_all_applied(
    pending: PendingIntegrationOperationDetail,
    *,
    external_ref: str,
) -> TerminalIntegrationOperationDetail:
    """Closes every Notion intent with one confirmed provider effect."""
    return _terminal_all(
        pending,
        status="applied",
        external_ref=external_ref,
    )


def terminal_all_failed(
    pending: PendingIntegrationOperationDetail,
    *,
    error_code: str,
) -> TerminalIntegrationOperationDetail:
    """Closes every Notion intent as rejected or not dispatched."""
    return _terminal_all(pending, status="failed", error_code=error_code)


def terminal_all_unverified(
    pending: PendingIntegrationOperationDetail,
    *,
    error_code: str,
) -> TerminalIntegrationOperationDetail:
    """Closes every Notion intent as ambiguous after provider dispatch."""
    return _terminal_all(pending, status="unverified", error_code=error_code)


def successful_notion_mutation_outcome(
    pending: PendingIntegrationOperationDetail,
    result: Mapping[str, Any],
    *,
    external_ref: str,
    single_item: bool = False,
) -> IntegrationAuditOutcome[dict[str, Any]]:
    """Builds a confirmed public result and aligned terminal evidence."""
    public_result = {**result, "outcome": "applied", "error_code": None}
    operation_detail = (
        terminal_applied_operation_detail(pending, external_ref=external_ref)
        if single_item
        else terminal_all_applied(pending, external_ref=external_ref)
    )
    return IntegrationAuditOutcome(
        public_result,
        status=AuditStatus.SUCCESS,
        external_ref=external_ref,
        operation_detail=operation_detail,
    )


def failed_notion_mutation_outcome(
    pending: PendingIntegrationOperationDetail,
    result: Mapping[str, Any],
    exc: IntegrationError,
    *,
    operation: str,
) -> IntegrationAuditOutcome[dict[str, Any]]:
    """Builds a failed or unverified result from a typed provider error."""
    disposition = exc.failure_disposition or IntegrationFailureDisposition.AMBIGUOUS
    ambiguous = disposition is IntegrationFailureDisposition.AMBIGUOUS
    error_code = notion_mutation_error_code(exc, operation=operation)
    public_result = {
        **result,
        "outcome": "unverified" if ambiguous else "failed",
        "error_code": error_code,
    }
    operation_detail = (
        terminal_all_unverified(pending, error_code=error_code)
        if ambiguous
        else terminal_all_failed(pending, error_code=error_code)
    )
    return IntegrationAuditOutcome(
        public_result,
        status=AuditStatus.UNVERIFIED if ambiguous else AuditStatus.FAILURE,
        operation_detail=operation_detail,
        unverified_result=public_result if ambiguous else None,
    )


def attach_notion_cancellation_evidence(
    exc: asyncio.CancelledError,
    pending: PendingIntegrationOperationDetail,
    *,
    operation: str,
) -> None:
    """Attaches exact terminal evidence to a cancelled mutation."""
    disposition = getattr(
        exc,
        "failure_disposition",
        IntegrationFailureDisposition.NOT_DISPATCHED,
    )
    error_code = notion_mutation_error_code(exc, operation=operation)
    exc.failure_disposition = disposition
    exc.operation_detail = (
        terminal_all_unverified(pending, error_code=error_code)
        if disposition is IntegrationFailureDisposition.AMBIGUOUS
        else terminal_all_failed(pending, error_code=error_code)
    )


def notion_mutation_error_code(exc: BaseException, *, operation: str) -> str:
    """Returns a stable public code without exposing a provider message."""
    if operation == "update_page_markdown" and isinstance(exc, IntegrationValidationError):
        if exc.user_message == NO_MATCH_ERROR_MESSAGE:
            return "no_match"
        if exc.user_message == MULTIPLE_MATCHES_ERROR_MESSAGE:
            return "multiple_matches"
        return "validation_error"
    for error_type, code in (
        (IntegrationAuthError, "authentication_error"),
        (IntegrationPermissionError, "permission_denied"),
        (IntegrationNotFoundError, "not_found"),
        (IntegrationRateLimitError, "rate_limited"),
        (IntegrationTimeoutError, "timeout"),
        (IntegrationValidationError, "validation_error"),
        (IntegrationConnectionError, "connection_error"),
    ):
        if isinstance(exc, error_type):
            return code
    if isinstance(exc, asyncio.CancelledError):
        return "cancelled"
    return "integration_error"


def _terminal_all(
    pending: PendingIntegrationOperationDetail,
    *,
    status: Literal["applied", "failed", "unverified"],
    external_ref: str | None = None,
    error_code: str | None = None,
) -> TerminalIntegrationOperationDetail:
    if status == "applied":
        if not external_ref or error_code is not None:
            raise ValueError("Applied Notion evidence requires only an external reference")
    elif status in {"failed", "unverified"}:
        if external_ref is not None or not error_code:
            raise ValueError("Failed Notion evidence requires only an error code")
    else:
        raise ValueError("Notion terminal evidence requires a terminal mutation status")

    item_count = sum(len(group.items) for group in pending.intent_groups)
    counts = IntegrationOperationCounts(
        applied=item_count if status == "applied" else 0,
        skipped=0,
        failed=item_count if status == "failed" else 0,
        unverified=item_count if status == "unverified" else 0,
    )
    return TerminalIntegrationOperationDetail(
        target=pending.target,
        intent_groups=pending.intent_groups,
        outcome_groups=[
            IntegrationOperationOutcomeGroup(
                key=group.key,
                outcomes=[
                    IntegrationOperationOutcome(
                        intent_index=index,
                        status=status,
                        effects=[
                            IntegrationOperationEffect(
                                status=status,
                                external_ref=external_ref,
                                error_code=error_code,
                            )
                        ],
                    )
                    for index, _item in enumerate(group.items)
                ],
            )
            for group in pending.intent_groups
        ],
        intent_counts=counts,
        effect_counts=counts,
    )


def _notion_target(
    entry: ResolvedContextEntry,
    target: NotionMutationTarget,
) -> IntegrationOperationTarget:
    return IntegrationOperationTarget(
        entity_type=target.entity_type,
        external_id=target.external_id,
        display_name=target.display_name,
        integration_resource_id=str(entry.integration_resource_id),
    )
