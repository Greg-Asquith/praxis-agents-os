# apps/api/integrations/meta_ads/tools/utils/client.py

"""Resolve workspace credentials through the shared secret store."""

from uuid import UUID

from pydantic_ai import RunContext

from core.exceptions.integration import IntegrationAuthError
from services.agents.runtime.context import RuntimeDeps
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.credentials import get_usable_connection_credential
from services.secrets import resolve_secret
from services.secrets.domain import SecretReference

from ...client import MetaAdsClient
from ...settings import meta_ads_settings
from .bindings import META_ADS_BINDING


def meta_ads_entries(deps: RuntimeDeps) -> dict[str, ResolvedContextEntry]:
    """Maps each ad account in the active context to its entry, by Meta account ID."""
    active_context = deps.active_context
    entries = active_context.compatible_entries(META_ADS_BINDING) if active_context else ()
    return {entry.external_id: entry for entry in entries}


async def meta_ads_client(
    ctx: RunContext[RuntimeDeps], entry: ResolvedContextEntry
) -> MetaAdsClient:
    return await meta_ads_client_for_principal(
        ctx.deps.db, actor=ctx.deps.user, workspace=ctx.deps.workspace, entry=entry
    )


async def meta_ads_client_for_principal(
    db, *, actor, workspace, entry: ResolvedContextEntry
) -> MetaAdsClient:
    return meta_ads_client_for_connection(
        db, actor=actor, workspace=workspace, connection_id=entry.connection_id
    )


def meta_ads_client_for_connection(db, *, actor, workspace, connection_id: UUID) -> MetaAdsClient:
    async def access_token() -> str:
        credential = await get_usable_connection_credential(
            db, connection_id=connection_id, actor=actor, workspace=workspace
        )
        if credential.auth_mode != "api_key":
            raise IntegrationAuthError(
                "Replace the Meta Ads access token to reconnect.", provider_key="meta_ads"
            )
        token = await resolve_secret(
            db,
            SecretReference(
                provider=credential.secret_provider or "",
                name=credential.secret_name or "",
                version=credential.secret_version or "",
            ),
            workspace_id=workspace.id,
            actor_id=actor.id,
        )
        if not token.strip():
            raise IntegrationAuthError(
                "Replace the Meta Ads access token to reconnect.", provider_key="meta_ads"
            )
        return token

    return MetaAdsClient(access_token, app_secret=meta_ads_settings.META_ADS_APP_SECRET)


def meta_ads_available() -> bool:
    return True
