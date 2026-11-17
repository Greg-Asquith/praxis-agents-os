# apps/api/services/media/generation.py

"""The interface every paid video generation backend implements, keyed by catalogue route.

A generation runs in two steps so the caller can record the provider's ID between
them: ``start`` sends the one paid request and returns that ID, and ``wait`` polls
until the clip is ready. Neither step retries the paid request.
"""

from dataclasses import dataclass
from typing import Protocol

from services.media.catalogue import MediaRoute


@dataclass(frozen=True)
class VideoGenerationRequest:
    provider_model: str
    prompt: str
    aspect_ratio: str
    resolution: str
    duration_seconds: int


@dataclass(frozen=True)
class GeneratedVideo:
    content: bytes
    media_type: str
    input_tokens: int
    output_tokens: int
    # The provider's own summary of how it read the prompt; untrusted model text.
    thought_summary: str | None


class VideoGenerationError(Exception):
    """A generation failure with a message safe to show an agent.

    ``refused`` marks a content policy refusal, which a revised prompt can fix.
    """

    def __init__(self, message: str, *, refused: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.refused = refused


class VideoBackend(Protocol):
    async def start(self, request: VideoGenerationRequest) -> str:
        """Sends the paid request and returns the provider's ID for it."""
        ...

    async def wait(
        self,
        provider_model: str,
        external_id: str,
        *,
        timeout_seconds: float,
        max_bytes: int,
    ) -> GeneratedVideo:
        """Polls until the clip is ready and returns it, at most ``max_bytes`` long."""
        ...


def video_backend(route: MediaRoute) -> VideoBackend:
    """Returns the backend that serves one catalogue route."""
    if route == "google":
        from services.media.omni import OmniBackend

        return OmniBackend()
    raise VideoGenerationError(f"Video generation through {route} isn't available.")
