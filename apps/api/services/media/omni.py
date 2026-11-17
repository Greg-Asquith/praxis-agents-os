# apps/api/services/media/omni.py

"""Omni video generation and editing through Google's Interactions API, on Vertex or the
Gemini API.

Each call runs in the background on Google's side and is polled, so a clip
that takes minutes never holds one HTTP request open. The clip comes back inline
as base64; its size is bounded by the duration and resolution the request names.
"""

import asyncio
import base64
import binascii
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING, Any

from core.settings import settings
from services.agents.models.domain import PROVIDER_GOOGLE
from services.agents.models.utils import provider_api_key, vertex_project
from services.agents.models.vertex_clients import google_vertex_location
from services.media.generation import (
    ChainExpiredError,
    GeneratedVideo,
    VideoEditRequest,
    VideoGenerationError,
    VideoGenerationRequest,
)

if TYPE_CHECKING:
    from google.genai.client import AsyncClient
    from google.genai.interactions import Interaction

POLL_INTERVAL_SECONDS = 5.0
_REQUEST_TIMEOUT_MS = 60_000
_MAX_POLL_FAILURES = 5
_MAX_THOUGHT_SUMMARY_CHARS = 2000
_REFUSAL_MARKERS = ("safety", "policy", "blocked", "prohibited", "responsible ai")
_REGION_MARKERS = ("location", "region", "country")
_REFUSED = "Google declined this prompt under its content policy. Revise the prompt and try again."
_UNAVAILABLE = "Google couldn't generate the video. Try again in a few minutes."
_REGION = (
    "Google doesn't edit uploaded video from this deployment's region. Edit a clip generated "
    "in Praxis instead, or ask an admin to use Google Vertex AI."
)


class OmniBackend:
    """Generates and edits clips with an Omni model on whichever Google transport is set up."""

    async def start(self, request: VideoGenerationRequest) -> str:
        return await _create(
            request.provider_model,
            input=request.prompt,
            response_format={
                "type": "video",
                "aspect_ratio": request.aspect_ratio,
                "resolution": request.resolution,
                "duration": f"{request.duration_seconds}s",
            },
            generation_config={"video_config": {"task": "text_to_video"}},
        )

    async def start_edit(self, request: VideoEditRequest) -> str:
        if request.previous_id is not None:
            # Google refuses a task alongside previous_interaction_id; the chain implies the edit.
            return await _create(
                request.provider_model,
                input=request.instruction,
                previous_interaction_id=request.previous_id,
                response_format={"type": "video"},
            )
        if request.video is None:
            raise ValueError("An edit needs the previous interaction or the clip.")
        return await _create(
            request.provider_model,
            input=[
                {
                    "type": "video",
                    "data": base64.b64encode(request.video).decode(),
                    "mime_type": "video/mp4",
                },
                {"type": "text", "text": request.instruction},
            ],
            response_format={"type": "video"},
            generation_config={"video_config": {"task": "edit"}},
            uploads_video=True,
        )

    async def wait(
        self,
        provider_model: str,
        external_id: str,
        *,
        timeout_seconds: float,
        max_bytes: int,
    ) -> GeneratedVideo:
        async with _client(provider_model) as client:
            try:
                async with asyncio.timeout(timeout_seconds):
                    interaction = await _poll(client, external_id)
            except TimeoutError as exc:
                await _cancel(client, external_id)
                raise VideoGenerationError(
                    "Google didn't finish the clip in time. Try a shorter or lower resolution clip."
                ) from exc
            except asyncio.CancelledError:
                await asyncio.shield(_cancel(client, external_id))
                raise
        return generated_video(interaction, max_bytes=max_bytes)


async def _create(provider_model: str, *, uploads_video: bool = False, **body: Any) -> str:
    """Sends one paid background request, stored so a later edit can chain from it."""
    from google.genai._interactions import APIError, APIStatusError

    async with _client(provider_model) as client:
        try:
            interaction = await client.interactions.create(
                model=provider_model, store=True, background=True, **body
            )
        except APIStatusError as exc:
            if "previous_interaction_id" in body and _chain_gone(exc.status_code, exc.message):
                raise ChainExpiredError(_UNAVAILABLE) from exc
            if uploads_video and _region_refused(exc.status_code, exc.message):
                raise VideoGenerationError(_REGION) from exc
            raise _status_error(exc.status_code, exc.message) from exc
        except APIError as exc:
            raise VideoGenerationError(_UNAVAILABLE) from exc
    if not interaction.id:
        raise VideoGenerationError(_UNAVAILABLE)
    return interaction.id


@asynccontextmanager
async def _client(provider_model: str) -> AsyncIterator["AsyncClient"]:
    from google.genai import Client
    from google.genai.types import HttpOptions, HttpRetryOptions

    # No retries: a retried create is a second paid clip. Polling handles its own failures.
    options = HttpOptions(timeout=_REQUEST_TIMEOUT_MS, retry_options=HttpRetryOptions(attempts=0))
    if settings.GOOGLE_VERTEX_AI:
        client = Client(
            vertexai=True,
            project=vertex_project(),
            location=google_vertex_location(provider_model),
            http_options=options,
        )
    else:
        client = Client(api_key=provider_api_key(PROVIDER_GOOGLE), http_options=options)
    try:
        yield client.aio
    finally:
        await client.aio.aclose()


async def _poll(client: "AsyncClient", external_id: str) -> "Interaction":
    from google.genai._interactions import APIError

    failures = 0
    while True:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        try:
            interaction = await client.interactions.get(id=external_id)
        except APIError as exc:
            # Reads are free, so ride out brief failures before giving up on the clip.
            failures += 1
            if failures >= _MAX_POLL_FAILURES:
                raise VideoGenerationError(_UNAVAILABLE) from exc
            continue
        failures = 0
        if interaction.status != "in_progress":
            return interaction


async def _cancel(client: "AsyncClient", external_id: str) -> None:
    with suppress(Exception):
        await client.interactions.cancel(id=external_id)


def generated_video(interaction: "Interaction", *, max_bytes: int) -> GeneratedVideo:
    """Returns the clip from a finished interaction, refusing a failure or an oversized clip."""
    if interaction.status != "completed":
        messages = [error.message or "" for error in interaction.errors or ()]
        messages += [_step_error(step) for step in interaction.steps or ()]
        raise _failure(" ".join(messages))
    video = interaction.output_video
    if video is None or not video.data:
        raise VideoGenerationError("Google finished without returning a clip. Try again.")
    if video.mime_type not in (None, "video/mp4"):
        raise VideoGenerationError(_UNAVAILABLE)
    # Base64 is four characters for every three bytes; check before decoding.
    if len(video.data) * 3 // 4 > max_bytes:
        raise VideoGenerationError(
            "The clip is too large to save. Try a shorter or lower resolution clip."
        )
    try:
        content = base64.b64decode(video.data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise VideoGenerationError(_UNAVAILABLE) from exc
    usage = interaction.usage
    return GeneratedVideo(
        content=content,
        media_type="video/mp4",
        input_tokens=(usage.total_input_tokens or 0) if usage else 0,
        # Thinking bills at $9 a million against video's $12, so this slightly overstates it.
        output_tokens=((usage.total_output_tokens or 0) + (usage.total_thought_tokens or 0))
        if usage
        else 0,
        thought_summary=_thought_summary(interaction),
    )


def _status_error(status_code: int, message: str) -> VideoGenerationError:
    if status_code == 400:
        return _failure(message)
    if status_code == 429:
        return VideoGenerationError(
            "Google is limiting video generation on this project. Try again in a few minutes."
        )
    return VideoGenerationError(_UNAVAILABLE)


def _chain_gone(status_code: int, message: str) -> bool:
    return status_code == 404 or (status_code == 400 and "not found" in message.lower())


def _region_refused(status_code: int, message: str) -> bool:
    # The Gemini API doesn't edit uploaded video for EEA, Swiss, or UK callers.
    lowered = message.lower()
    return status_code in (400, 403) and any(marker in lowered for marker in _REGION_MARKERS)


def _failure(message: str) -> VideoGenerationError:
    lowered = message.lower()
    if any(marker in lowered for marker in _REFUSAL_MARKERS):
        return VideoGenerationError(_REFUSED, refused=True)
    return VideoGenerationError(_UNAVAILABLE)


def _step_error(step: Any) -> str:
    error = getattr(step, "error", None)
    return getattr(error, "message", None) or ""


def _thought_summary(interaction: "Interaction") -> str | None:
    texts = [
        text
        for step in interaction.steps or ()
        if getattr(step, "type", None) == "thought"
        for part in getattr(step, "summary", None) or ()
        if (text := getattr(part, "text", None))
    ]
    summary = "\n".join(texts).strip()
    return summary[:_MAX_THOUGHT_SUMMARY_CHARS] or None
