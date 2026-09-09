"""Offline Images API transport shared by helper and governed scenario tests."""

import base64
import json
from contextlib import asynccontextmanager
from email.parser import BytesParser
from email.policy import default

import httpx2 as httpx

from services.agents.models.utils import _build_retrying_http_client
from services.agents.runtime.tools.native import openai_images

IMAGE_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def image_response():
    return {
        "created": 1788940800,
        "data": [{"b64_json": base64.b64encode(IMAGE_BYTES).decode()}],
        "output_format": "png",
        "quality": "medium",
        "size": "1024x1024",
        "usage": {
            "input_tokens": 10,
            "output_tokens": 20,
            "total_tokens": 30,
            "input_tokens_details": {"text_tokens": 6, "image_tokens": 4},
            "output_tokens_details": {"text_tokens": 0, "image_tokens": 20},
        },
    }


def image_request(request):
    if request.headers["content-type"].startswith("application/json"):
        return json.loads(request.content)
    message = BytesParser(policy=default).parsebytes(
        f"Content-Type: {request.headers['content-type']}\r\n\r\n".encode() + request.content
    )
    return {
        part.get_param("name", header="content-disposition"): (
            part.get_payload(decode=True)
            if part.get_filename()
            else part.get_payload(decode=True).decode()
        )
        for part in message.iter_parts()
    }


@asynccontextmanager
async def mock_openai_images(monkeypatch, handler=None):
    requests = []

    def respond(request):
        requests.append(request)
        return handler(request) if handler else httpx.Response(200, json=image_response())

    async with _build_retrying_http_client(httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(openai_images, "retrying_http_client", lambda: client)
        yield requests
