# apps/api/services/media/watch_video.py

"""Calls the video understanding model for find_video_moments and ask_video.

Each call is one Gemini request over the video part, with server-chosen
offsets, frame rate, and media resolution. Everything the model writes is
untrusted text from hostile media; callers use only the times they parse.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import replace

import httpx2 as httpx
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.exceptions import AgentRunError
from pydantic_ai.messages import BinaryContent, UploadedFile, VideoUrl
from pydantic_ai.usage import RunUsage, UsageLimits

from core.settings import settings
from services.agents.models.domain import PROVIDER_GOOGLE
from services.agents.models.factory import build_model
from services.agents.models.resolution import resolve_catalog_model
from services.ai_usage.domain import AIUsageEventData
from services.ai_usage.run_metered_helper import run_metered_helper
from services.media.domain import VideoUnderstandingError

type VideoPart = BinaryContent | VideoUrl | UploadedFile
type UnderstandingRequest = Sequence[str | VideoPart]

CONCURRENT_UNDERSTANDING_CALLS = 3


async def watch_video[T](
    requests: Sequence[UnderstandingRequest],
    *,
    instructions: str,
    output_type: type[T],
    usage: AIUsageEventData,
) -> list[T]:
    """Runs one model call per request, three at a time, metered as one usage event."""
    helper = PydanticAgent(
        build_model(resolve_catalog_model(PROVIDER_GOOGLE, settings.VIDEO_UNDERSTANDING_MODEL)),
        name="praxis_video_understanding_google",
        instructions=instructions,
        output_type=output_type,
        # One retry for an answer that doesn't match the schema.
        retries=1,
    )
    limit = asyncio.Semaphore(CONCURRENT_UNDERSTANDING_CALLS)

    async def call(run_usage: RunUsage) -> list[T]:
        async def one(request: UnderstandingRequest) -> T:
            async with limit:
                result = await helper.run(
                    list(request), usage_limits=UsageLimits(request_limit=2), usage=run_usage
                )
                return result.output

        # Every call finishes before any failure is raised, so none is left running.
        results = await asyncio.gather(
            *(one(request) for request in requests), return_exceptions=True
        )
        for result in results:
            if isinstance(result, (AgentRunError, httpx.TransportError)):
                raise VideoUnderstandingError(
                    "Gemini couldn't watch the video. Try again."
                ) from result
            if isinstance(result, BaseException):
                raise result
        return results

    return await run_metered_helper(
        replace(usage, details={**(usage.details or {}), "calls": len(requests)}), call
    )
