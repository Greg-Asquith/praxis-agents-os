# apps/api/services/integrations/microsoft_graph/__init__.py

"""Published Microsoft Graph integration-engine seam."""

from .client import GRAPH_API_BASE_URL, MicrosoftGraphClient, fixed_access_token
from .connection_client import graph_client_for_connection
from .entra import (
    ENTRA_HOST,
    authorization_url,
    entra_oauth_config,
    entra_oauth_protocol,
    resolve_entra_tenant,
    token_url,
    validate_entra_tenant,
)
from .errors import classify_entra_token_error, graph_response_error
from .identity import extract_token_identity, fetch_graph_identity
from .payloads import graph_string, required_graph_string
from .people import PersonResult, search_people

__all__ = [
    "ENTRA_HOST",
    "GRAPH_API_BASE_URL",
    "MicrosoftGraphClient",
    "PersonResult",
    "authorization_url",
    "classify_entra_token_error",
    "entra_oauth_config",
    "entra_oauth_protocol",
    "extract_token_identity",
    "fetch_graph_identity",
    "fixed_access_token",
    "graph_client_for_connection",
    "graph_response_error",
    "graph_string",
    "required_graph_string",
    "resolve_entra_tenant",
    "search_people",
    "token_url",
    "validate_entra_tenant",
]
