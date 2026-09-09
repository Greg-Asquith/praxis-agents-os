# apps/api/services/agents/models/vertex_openai_client.py

"""ADC authentication and HTTP client ownership for Vertex partner models."""

import asyncio
from collections.abc import AsyncGenerator
from functools import lru_cache
from threading import Lock

import google.auth
import httpx2 as httpx
from google.auth.credentials import Credentials
from google.auth.transport.requests import Request

from services.agents.models.utils import _build_retrying_http_client


class VertexBearerAuth(httpx.Auth):
    """Load and refresh scoped credentials outside the event loop."""

    def __init__(self) -> None:
        self._credentials: Credentials | None = None
        self._lock = Lock()

    def _token(self) -> str:
        # Keep the lock in the worker thread even if the awaiting request is cancelled.
        with self._lock:
            if self._credentials is None:
                self._credentials, _ = google.auth.default(
                    scopes=["https://www.googleapis.com/auth/cloud-platform"]
                )
            if not self._credentials.valid:
                self._credentials.refresh(Request())
            return self._credentials.token

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        request.headers["Authorization"] = f"Bearer {await asyncio.to_thread(self._token)}"
        yield request


def partner_base_url(project: str, location: str) -> str:
    """Returns the serverless Chat Completions base URL for a Vertex location."""
    host = (
        "aiplatform.googleapis.com"
        if location == "global"
        else f"{location}-aiplatform.googleapis.com"
    )
    return f"https://{host}/v1/projects/{project}/locations/{location}/endpoints/openapi"


@lru_cache(maxsize=1)
def get_vertex_openai_client() -> httpx.AsyncClient:
    """Returns the process-owned HTTP client with refreshable ADC authentication."""
    return _build_retrying_http_client(auth=VertexBearerAuth())


async def close_vertex_openai_client() -> None:
    """Closes the partner client without creating one during shutdown."""
    if get_vertex_openai_client.cache_info().currsize:
        client = get_vertex_openai_client()
        get_vertex_openai_client.cache_clear()
        await client.aclose()
