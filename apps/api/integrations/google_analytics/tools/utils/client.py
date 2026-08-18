# apps/api/integrations/google_analytics/tools/utils/client.py

"""Google Analytics runtime credential resolution and client construction."""

from pydantic_ai import ModelRetry, RunContext

from integrations.google_analytics.client import GoogleAnalyticsClient
from integrations.google_analytics.discover_resources import ANALYTICS_READONLY_SCOPE
from models.integrations import ExternalCredential
from services.agents.runtime.context import RuntimeDeps
from services.integrations.connections.utils import refresh_oauth_credential
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.credentials import (
    GoogleServiceAccountTokenProvider,
    ensure_fresh_credential,
    get_usable_connection_credential,
    parse_google_service_account_json,
)
from services.secrets import resolve_secret
from services.secrets.domain import SecretReference

_SERVICE_ACCOUNT_PROVIDERS: dict[tuple[str, str], GoogleServiceAccountTokenProvider] = {}


async def google_analytics_client(
    ctx: RunContext[RuntimeDeps],
    entry: ResolvedContextEntry,
) -> GoogleAnalyticsClient:
    return await google_analytics_client_for_principal(
        ctx.deps.db,
        actor=ctx.deps.user,
        workspace=ctx.deps.workspace,
        entry=entry,
    )


async def google_analytics_client_for_principal(
    db,
    *,
    actor,
    workspace,
    entry: ResolvedContextEntry,
) -> GoogleAnalyticsClient:
    async def access_token(force: bool) -> str:
        credential = await get_usable_connection_credential(
            db,
            connection_id=entry.connection_id,
            actor=actor,
            workspace=workspace,
        )
        if credential.auth_mode == "oauth":
            fresh = await ensure_fresh_credential(
                db,
                credential_id=credential.id,
                refresh_token=refresh_oauth_credential,
                force=force,
            )
            if not fresh.access_token:
                raise ModelRetry("The Google Analytics connection needs to be reconnected.")
            return fresh.access_token
        if credential.auth_mode != "service_account":
            raise ModelRetry("The Google Analytics connection uses an unsupported credential type.")
        cache_key = (str(credential.id), credential.secret_version or "")
        provider = _SERVICE_ACCOUNT_PROVIDERS.get(cache_key)
        if provider is None:
            raw = await resolve_secret(
                db,
                _credential_reference(credential),
                workspace_id=workspace.id,
                actor_id=actor.id,
            )
            provider = GoogleServiceAccountTokenProvider(
                parse_google_service_account_json(raw, provider_key="google_analytics"),
                provider_key="google_analytics",
                scope=ANALYTICS_READONLY_SCOPE,
            )
            _SERVICE_ACCOUNT_PROVIDERS[cache_key] = provider
        return await provider.access_token(force)

    return GoogleAnalyticsClient(access_token)


def google_analytics_available() -> bool:
    return True


def _credential_reference(credential: ExternalCredential) -> SecretReference:
    return SecretReference(
        provider=credential.secret_provider or "",
        name=credential.secret_name or "",
        version=credential.secret_version or "",
    )
