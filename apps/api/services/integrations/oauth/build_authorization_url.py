# apps/api/services/integrations/oauth/build_authorization_url.py

"""Build provider authorization URLs with mandatory PKCE S256."""

from urllib.parse import urlencode

from core.settings import settings
from services.integrations.manifest import IntegrationProviderManifest
from services.integrations.oauth.resolve_provider_config import resolve_provider_oauth_config
from services.integrations.oauth.utils import code_challenge


def build_authorization_url(
    manifest: IntegrationProviderManifest,
    *,
    state: str,
    code_verifier: str,
) -> str:
    oauth_config = resolve_provider_oauth_config(manifest.provider_key)
    params = {
        "client_id": oauth_config.client_id,
        "redirect_uri": settings.INTEGRATIONS_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(manifest.oauth_scopes),
        "state": state,
        "code_challenge": code_challenge(code_verifier),
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "false",
    }
    return f"{oauth_config.authorization_url}?{urlencode(params)}"
