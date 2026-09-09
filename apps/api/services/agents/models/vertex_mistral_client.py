# apps/api/services/agents/models/vertex_mistral_client.py

"""Process-owned HTTP clients for Mistral's Vertex publisher API."""

import json
from threading import Lock

import httpx2 as httpx

from core.settings import settings
from services.agents.models.utils import _build_retrying_http_client
from services.agents.models.vertex_openai_client import VertexBearerAuth

_clients: dict[tuple[str, str, str, int, float, float], httpx.AsyncClient] = {}
_lock = Lock()


def get_vertex_mistral_client(project: str, location: str, model: str) -> httpx.AsyncClient:
    """Bind publisher routing to one immutable endpoint configuration."""
    key = (
        project,
        location,
        model,
        settings.LLM_HTTP_RETRY_MAX_ATTEMPTS,
        settings.LLM_HTTP_RETRY_MAX_WAIT_SECONDS,
        settings.LLM_HTTP_RETRY_TOTAL_WAIT_CAP_SECONDS,
    )
    with _lock:
        client = _clients.get(key)
        if client is None:
            publisher, model_id = model.split("/", 1)
            endpoint = (
                f"https://{location}-aiplatform.googleapis.com/v1/projects/{project}"
                f"/locations/{location}/publishers/{publisher}/models/{model_id}"
            )

            async def route_request(request: httpx.Request) -> None:
                # The publisher API uses the same chat payload with different RPC paths.
                body = json.loads(request.content)
                method = "streamRawPredict" if body.get("stream") else "rawPredict"
                request.url = httpx.URL(f"{endpoint}:{method}")

            client = _build_retrying_http_client(auth=VertexBearerAuth())
            client.event_hooks["request"].append(route_request)
            _clients[key] = client
        return client


async def close_vertex_mistral_clients() -> None:
    """Close each endpoint-bound client without creating any during shutdown."""
    with _lock:
        clients = tuple(_clients.values())
        _clients.clear()
    first_error: Exception | None = None
    for client in clients:
        try:
            await client.aclose()
        except Exception as exc:
            first_error = first_error or exc
    if first_error is not None:
        raise first_error
