# apps/api/services/agents/models/google_vertex_client.py

"""Process-owned Google Vertex AI client lifecycle."""

from threading import Lock

from google.genai import Client
from google.genai.types import HttpOptions, HttpRetryOptions
from pydantic_ai.models import DEFAULT_HTTP_TIMEOUT

from core.settings import settings
from services.agents.models.domain import PROVIDER_GOOGLE, ModelConfigurationError

_clients: dict[tuple[str, str, int, float], Client] = {}
_clients_lock = Lock()


def get_google_vertex_client() -> Client:
    """Returns the process-owned Vertex client for the active configuration."""
    project = settings.GOOGLE_VERTEX_PROJECT or settings.GCP_PROJECT_ID
    if not project:
        raise ModelConfigurationError(
            "Vertex AI requires a project (GOOGLE_VERTEX_PROJECT or GCP_PROJECT_ID).",
            details={"provider": PROVIDER_GOOGLE},
        )

    client_key = (
        project,
        settings.GOOGLE_VERTEX_LOCATION,
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
                location=settings.GOOGLE_VERTEX_LOCATION,
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


async def close_google_vertex_clients() -> None:
    """Closes and forgets every process-owned Vertex client."""
    with _clients_lock:
        clients = tuple(_clients.values())
        _clients.clear()

    first_error: Exception | None = None
    for client in clients:
        try:
            await client.aio.aclose()
        except Exception as exc:  # pragma: no cover - defensive shutdown path
            if first_error is None:
                first_error = exc
    if first_error is not None:
        raise first_error
