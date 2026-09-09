# apps/api/services/agents/models/vertex_clients.py

"""Process-owned Google and Anthropic Vertex AI client lifecycle."""

from threading import Lock

from anthropic import AsyncAnthropicVertex
from google.genai import Client
from google.genai.types import HttpOptions, HttpRetryOptions
from pydantic_ai.models import DEFAULT_HTTP_TIMEOUT

from core.settings import settings
from services.agents.models.domain import (
    PROVIDER_ANTHROPIC,
    PROVIDER_GOOGLE,
    ModelConfigurationError,
)
from services.agents.models.registry import get_model
from services.agents.models.utils import (
    close_retrying_http_client,
    retrying_http_client,
    vertex_project,
)
from services.agents.models.vertex_mistral_client import close_vertex_mistral_clients
from services.agents.models.vertex_openai_client import close_vertex_openai_client

_clients: dict[tuple[str, str, int, float], Client] = {}
_anthropic_clients: dict[tuple[str, str, int, float], AsyncAnthropicVertex] = {}
_clients_lock = Lock()


def get_google_vertex_client(model: str | None = None) -> Client:
    """Returns the process-owned Vertex client for the active configuration."""
    project = vertex_project()
    if not project:
        raise ModelConfigurationError(
            "Vertex AI requires a project (GOOGLE_VERTEX_PROJECT or GCP_PROJECT_ID).",
            details={"provider": PROVIDER_GOOGLE},
        )

    info = get_model(PROVIDER_GOOGLE, model) if model is not None else None
    location = settings.GOOGLE_VERTEX_LOCATION
    if location == "auto":
        # Embeddings are outside the model catalog and retain their global default.
        location = info.vertex_default_location if info is not None else "global"
    if not location or (info is not None and location not in info.vertex_supported_locations):
        raise ModelConfigurationError(
            f"Unsupported Vertex AI location '{location}' for Google model '{model}'.",
            details={"provider": PROVIDER_GOOGLE, "model": model, "location": location},
        )

    client_key = (
        project,
        location,
        settings.LLM_HTTP_RETRY_MAX_ATTEMPTS,
        settings.LLM_HTTP_RETRY_MAX_WAIT_SECONDS,
    )
    with _clients_lock:
        client = _clients.get(client_key)
        if client is None:
            # Vertex uses google-genai's transport, configured with the shared request policy.
            client = Client(
                vertexai=True,
                project=project,
                location=location,
                http_options=HttpOptions(
                    timeout=DEFAULT_HTTP_TIMEOUT * 1000,
                    retry_options=HttpRetryOptions(
                        attempts=settings.LLM_HTTP_RETRY_MAX_ATTEMPTS,
                        max_delay=settings.LLM_HTTP_RETRY_MAX_WAIT_SECONDS,
                    ),
                ),
            )
            _clients[client_key] = client
        return client


def get_anthropic_vertex_client() -> AsyncAnthropicVertex:
    """Returns the process-owned Claude client for the active Vertex configuration."""
    project = vertex_project()
    if not project:
        raise ModelConfigurationError(
            "Vertex AI requires a project (GOOGLE_VERTEX_PROJECT or GCP_PROJECT_ID).",
            details={"provider": PROVIDER_ANTHROPIC},
        )

    client_key = (
        project,
        settings.ANTHROPIC_VERTEX_LOCATION,
        settings.LLM_HTTP_RETRY_MAX_ATTEMPTS,
        settings.LLM_HTTP_RETRY_MAX_WAIT_SECONDS,
    )
    with _clients_lock:
        client = _anthropic_clients.get(client_key)
        if client is None:
            client = AsyncAnthropicVertex(
                project_id=project,
                region=settings.ANTHROPIC_VERTEX_LOCATION,
                max_retries=0,
                http_client=retrying_http_client(),
                timeout=DEFAULT_HTTP_TIMEOUT,
            )
            _anthropic_clients[client_key] = client
        return client


async def close_vertex_clients() -> None:
    """Closes and forgets the Vertex clients and their shared provider transport."""
    with _clients_lock:
        clients = tuple(_clients.values())
        _clients.clear()
        anthropic_clients = tuple(_anthropic_clients.values())
        _anthropic_clients.clear()

    first_error: Exception | None = None
    close_operations = [client.aio.aclose for client in clients]
    close_operations.extend(client.close for client in anthropic_clients)
    close_operations.extend((close_vertex_openai_client, close_vertex_mistral_clients))
    close_operations.append(close_retrying_http_client)
    for close in close_operations:
        try:
            await close()
        except Exception as exc:  # pragma: no cover - defensive shutdown path
            if first_error is None:
                first_error = exc
    if first_error is not None:
        raise first_error
