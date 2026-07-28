# apps/api/integrations/google_ads/tools/utils.py

"""Shared Google Ads bindings, credential access, routing metadata, and audit."""

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import SecretStr
from pydantic_ai import ModelRetry, RunContext

from models.integrations import ExternalCredential
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import IntegrationToolBinding, ToolFieldPresentation
from services.audit_events import AuditStatus, record_integration_operation_audit_event
from services.integrations.connections.utils import (
    get_visible_connection,
    refresh_oauth_credential,
)
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.credentials import (
    GoogleServiceAccountTokenProvider,
    ensure_fresh_credential,
    parse_google_service_account_json,
)
from services.secrets import resolve_secret
from services.secrets.domain import SecretReference

from ..client import GoogleAdsClient, normalize_customer_id
from ..settings import google_ads_settings

GOOGLE_ADS_SCOPE = "https://www.googleapis.com/auth/adwords"
GOOGLE_ADS_BINDING = IntegrationToolBinding(
    provider_keys=frozenset({"google_ads"}),
    resource_types=frozenset({"google_ads_account"}),
)
GOOGLE_ADS_WRITE_BINDING = IntegrationToolBinding(
    provider_keys=GOOGLE_ADS_BINDING.provider_keys,
    resource_types=GOOGLE_ADS_BINDING.resource_types,
    requires_write=True,
)
RESULTS_FIELD = (ToolFieldPresentation(key="results", label="Accounts", format="list"),)
_SERVICE_ACCOUNT_PROVIDERS: dict[tuple[str, str], GoogleServiceAccountTokenProvider] = {}


async def google_ads_client(
    ctx: RunContext[RuntimeDeps],
    entry: ResolvedContextEntry,
) -> GoogleAdsClient:
    connection = await get_visible_connection(
        ctx.deps.db,
        connection_id=entry.connection_id,
        actor=ctx.deps.user,
        workspace=ctx.deps.workspace,
    )
    credential = await ctx.deps.db.get(ExternalCredential, connection.credential_id)
    if credential is None or credential.deleted:
        raise ModelRetry("The Google Ads connection needs to be reconnected.")

    async def access_token(force: bool) -> str:
        if credential.auth_mode == "oauth":
            fresh = await ensure_fresh_credential(
                ctx.deps.db,
                credential_id=credential.id,
                refresh_token=refresh_oauth_credential,
                force=force,
            )
            if not fresh.access_token:
                raise ModelRetry("The Google Ads connection needs to be reconnected.")
            return fresh.access_token
        if credential.auth_mode != "service_account":
            raise ModelRetry("The Google Ads connection uses an unsupported credential type.")
        cache_key = (str(credential.id), credential.secret_version or "")
        provider = _SERVICE_ACCOUNT_PROVIDERS.get(cache_key)
        if provider is None:
            raw = await resolve_secret(
                ctx.deps.db,
                _credential_reference(credential),
                workspace_id=ctx.deps.workspace.id,
                actor_id=ctx.deps.user.id,
            )
            provider = GoogleServiceAccountTokenProvider(
                parse_google_service_account_json(
                    raw,
                    provider_key="google_ads",
                ),
                provider_key="google_ads",
                scope=GOOGLE_ADS_SCOPE,
            )
            _SERVICE_ACCOUNT_PROVIDERS[cache_key] = provider
        return await provider.access_token(force)

    developer_token = google_ads_settings.GOOGLE_ADS_DEVELOPER_TOKEN
    if developer_token is None or not developer_token.get_secret_value().strip():
        raise ModelRetry("Google Ads is not configured for provider operations.")
    return GoogleAdsClient(access_token, developer_token=developer_token)


def login_customer_id(entry: ResolvedContextEntry) -> str:
    value = str(entry.permissions_metadata.get("login_customer_id", "")).strip()
    if not value:
        raise ModelRetry(
            "This Google Ads account is missing routing metadata. Refresh its resources."
        )
    return normalize_customer_id(value)


async def run_audited_operation(
    ctx: RunContext[RuntimeDeps],
    entry: ResolvedContextEntry,
    *,
    tool_name: str,
    operation: str,
    execute: Callable[[], Awaitable[Any]],
    external_ref_from_result: Callable[[Any], str | None] | None = None,
) -> Any:
    try:
        result = await execute()
    except Exception as exc:
        await record_google_ads_operation_audit(
            ctx,
            entry,
            tool_name=tool_name,
            operation=operation,
            status=AuditStatus.FAILURE,
            error_code=exc.__class__.__name__,
        )
        raise
    external_ref = external_ref_from_result(result) if external_ref_from_result else None
    await record_google_ads_operation_audit(
        ctx,
        entry,
        tool_name=tool_name,
        operation=operation,
        status=AuditStatus.SUCCESS,
        external_ref=external_ref,
    )
    return result


async def record_google_ads_operation_audit(
    ctx: RunContext[RuntimeDeps],
    entry: ResolvedContextEntry,
    *,
    tool_name: str,
    operation: str,
    status: AuditStatus,
    external_ref: str | None = None,
    error_code: str | None = None,
) -> None:
    await record_integration_operation_audit_event(
        workspace_id=ctx.deps.workspace.id,
        agent=ctx.deps.agent,
        run=ctx.deps.run,
        tool_name=tool_name,
        provider_key="google_ads",
        connection_id=entry.connection_id,
        integration_resource_id=entry.integration_resource_id,
        external_id=entry.external_id,
        operation=operation,
        status=status,
        external_ref=external_ref,
        error_code=error_code,
    )


def fan_out_dict(item) -> dict[str, Any]:
    return {
        "integration_resource_id": item.integration_resource_id,
        "connection_id": item.connection_id,
        "provider_key": item.provider_key,
        "external_id": item.external_id,
        "display_name": item.display_name,
        "status": item.status,
        "data": item.data,
        "error_code": item.error_code,
        "error_message": item.error_message,
    }


def google_ads_available() -> bool:
    value: SecretStr | None = google_ads_settings.GOOGLE_ADS_DEVELOPER_TOKEN
    return value is not None and bool(value.get_secret_value().strip())


def _credential_reference(credential: ExternalCredential) -> SecretReference:
    return SecretReference(
        provider=credential.secret_provider or "",
        name=credential.secret_name or "",
        version=credential.secret_version or "",
    )
