"""Offline Google transport with real SDK clients and model adapters."""

import base64
from contextlib import asynccontextmanager

import google.auth
import httpx2 as httpx
from google.genai import Client
from google.oauth2.credentials import Credentials
from pydantic_ai import models

from core.settings import settings
from services.agents.models import factory, vertex_clients
from services.agents.models.utils import _build_retrying_http_client
from tests.support.openai_images import IMAGE_BYTES


def google_image_response():
    return {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": "image/png",
                                "data": base64.b64encode(IMAGE_BYTES).decode(),
                            }
                        }
                    ],
                },
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 10,
            "candidatesTokenCount": 20,
            "totalTokenCount": 30,
        },
        "modelVersion": "gemini-3.1-flash-image",
    }


@asynccontextmanager
async def mock_google_native(monkeypatch, handler=None, *, vertex=False):
    requests = []
    clients = []

    def respond(request):
        requests.append(request)
        return handler(request) if handler else httpx.Response(200, json=google_image_response())

    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", True)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_AI", vertex)
    monkeypatch.setattr(vertex_clients, "_clients", {})
    credentials = Credentials(token="test-adc")  # noqa: S106 - Offline ADC fixture.
    monkeypatch.setattr(google.auth, "default", lambda **kwargs: (credentials, "test-project"))
    transport = httpx.MockTransport(respond)
    client_context = (
        httpx.AsyncClient(transport=transport) if vertex else _build_retrying_http_client(transport)
    )
    async with client_context as http_client:
        monkeypatch.setattr(factory, "retrying_http_client", lambda: http_client)

        def build_client(**kwargs):
            options = kwargs["http_options"]
            options.httpx_async_client = http_client
            client = Client(**kwargs)
            clients.append(client)
            return client

        monkeypatch.setattr(vertex_clients, "Client", build_client)
        try:
            yield requests
        finally:
            for client in clients:
                await client.aio.aclose()
                client.close()
