# apps/api/integrations/bigquery/tools/utils.py

"""Shared BigQuery context, credential, routing, and audit helpers."""

import re
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from pydantic_ai import ModelRetry, RunContext

from models.integrations import ExternalCredential
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import IntegrationToolBinding
from services.audit_events import AuditStatus, record_integration_operation_audit_event
from services.integrations.connections.utils import get_visible_connection
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.credentials import (
    GoogleServiceAccountTokenProvider,
    parse_google_service_account_json,
)
from services.secrets import resolve_secret
from services.secrets.domain import SecretReference

from ..client import BigQueryClient
from ..discover_resources import BIGQUERY_SCOPE

BIGQUERY_BINDING = IntegrationToolBinding(
    provider_keys=frozenset({"bigquery"}),
    resource_types=frozenset({"bigquery_dataset"}),
)
_LABEL_CHARACTER = re.compile(r"[^a-z0-9_-]+")
_SERVICE_ACCOUNT_PROVIDERS: dict[
    tuple[str, str],
    GoogleServiceAccountTokenProvider,
] = {}


def active_bigquery_entries(ctx: RunContext[RuntimeDeps]) -> tuple[ResolvedContextEntry, ...]:
    active_context = ctx.deps.active_context
    entries = (
        active_context.compatible_entries(BIGQUERY_BINDING) if active_context is not None else ()
    )
    if not entries:
        raise ModelRetry(
            "No BigQuery datasets are in the active context. "
            "Ask the user to select a BigQuery dataset or context group."
        )
    return entries


def dataset_coordinates(entry: ResolvedContextEntry) -> tuple[str, str]:
    project_id = str(entry.permissions_metadata.get("project_id", "")).strip()
    dataset_id = str(entry.permissions_metadata.get("dataset_id", "")).strip()
    if not project_id or not dataset_id:
        raise ModelRetry(
            f"{entry.display_name} is missing BigQuery routing metadata. "
            "Ask the user to refresh the connection's resources."
        )
    return project_id, dataset_id


def dataset_location(entry: ResolvedContextEntry) -> str:
    location = str(entry.permissions_metadata.get("location", "")).strip()
    if not location:
        raise ModelRetry(
            f"{entry.display_name} is missing its BigQuery location. "
            "Ask the user to refresh the connection's resources."
        )
    return location


async def bigquery_query_client(
    ctx: RunContext[RuntimeDeps],
    entry: ResolvedContextEntry,
) -> tuple[BigQueryClient, str]:
    connection = await get_visible_connection(
        ctx.deps.db,
        connection_id=entry.connection_id,
        actor=ctx.deps.user,
        workspace=ctx.deps.workspace,
    )
    credential = await ctx.deps.db.get(ExternalCredential, connection.credential_id)
    if credential is None or credential.deleted or credential.auth_mode != "service_account":
        raise ModelRetry("The BigQuery connection needs to be reconnected.")
    cache_key = (str(credential.id), credential.secret_version or "")
    provider = _SERVICE_ACCOUNT_PROVIDERS.get(cache_key)
    if provider is None:
        raw = await resolve_secret(
            ctx.deps.db,
            SecretReference(
                provider=credential.secret_provider or "",
                name=credential.secret_name or "",
                version=credential.secret_version or "",
            ),
            workspace_id=ctx.deps.workspace.id,
            actor_id=ctx.deps.user.id,
        )
        provider = GoogleServiceAccountTokenProvider(
            parse_google_service_account_json(raw, provider_key="bigquery"),
            provider_key="bigquery",
            scope=BIGQUERY_SCOPE,
        )
        _SERVICE_ACCOUNT_PROVIDERS[cache_key] = provider
    return BigQueryClient(provider.access_token), provider.credentials.project_id


async def run_audited_operation(
    ctx: RunContext[RuntimeDeps],
    entries: Sequence[ResolvedContextEntry],
    *,
    tool_name: str,
    operation: str,
    execute: Callable[[], Awaitable[Any]],
) -> Any:
    try:
        result = await execute()
    except Exception as exc:
        await _record_operation_for_entries(
            ctx,
            entries,
            tool_name=tool_name,
            operation=operation,
            status=AuditStatus.FAILURE,
            error_code=exc.__class__.__name__,
        )
        raise
    await _record_operation_for_entries(
        ctx,
        entries,
        tool_name=tool_name,
        operation=operation,
        status=AuditStatus.SUCCESS,
    )
    return result


async def _record_operation_for_entries(
    ctx: RunContext[RuntimeDeps],
    entries: Sequence[ResolvedContextEntry],
    *,
    tool_name: str,
    operation: str,
    status: AuditStatus,
    error_code: str | None = None,
) -> None:
    for entry in entries:
        await record_integration_operation_audit_event(
            workspace_id=ctx.deps.workspace.id,
            agent=ctx.deps.agent,
            run=ctx.deps.run,
            tool_name=tool_name,
            provider_key="bigquery",
            connection_id=entry.connection_id,
            integration_resource_id=entry.integration_resource_id,
            external_id=entry.external_id,
            operation=operation,
            status=status,
            external_ref=None,
            error_code=error_code,
        )


def query_labels(ctx: RunContext[RuntimeDeps]) -> dict[str, str]:
    return {
        "praxis_workspace": _label_value(str(ctx.deps.workspace.id)),
        "praxis_agent": _label_value(str(ctx.deps.agent.id)),
        "praxis_run": _label_value(str(ctx.deps.run.id)),
    }


def _label_value(value: str) -> str:
    normalized = _LABEL_CHARACTER.sub("-", value.lower()).strip("-_")
    return normalized[:63] or "unknown"
