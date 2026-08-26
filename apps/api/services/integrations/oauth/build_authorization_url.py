# apps/api/services/integrations/oauth/build_authorization_url.py

"""Build provider authorization URLs from provider-declared protocol data."""

from urllib.parse import urlencode

from core.settings import settings
from services.integrations.manifest import IntegrationProviderManifest
from services.integrations.oauth.resolve_provider_config import resolve_provider_oauth_config
from services.integrations.oauth.utils import code_challenge
from services.integrations.plugin import OAUTH_AUTHORIZATION_RESERVED_PARAMETERS


def build_authorization_url(
    manifest: IntegrationProviderManifest,
    *,
    state: str,
    code_verifier: str,
) -> str:
    oauth_config = resolve_provider_oauth_config(manifest.provider_key)
    protocol = oauth_config.protocol
    extra_params = dict(protocol.authorization_params)
    collisions = OAUTH_AUTHORIZATION_RESERVED_PARAMETERS.intersection(extra_params)
    if collisions:
        names = ", ".join(sorted(collisions))
        raise RuntimeError(f"OAuth authorization parameters override reserved fields: {names}")
    params = {
        "client_id": oauth_config.client_id,
        "redirect_uri": settings.INTEGRATIONS_OAUTH_REDIRECT_URI,
        "response_type": "code",
    }
    if protocol.scope_parameter:
        params["scope"] = protocol.scope_separator.join(manifest.oauth_scopes)
    params["state"] = state
    if protocol.pkce == "s256":
        params["code_challenge"] = code_challenge(code_verifier)
        params["code_challenge_method"] = "S256"
    params.update(extra_params)
    return f"{oauth_config.authorization_url}?{urlencode(params)}"
