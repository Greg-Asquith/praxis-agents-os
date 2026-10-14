# apps/api/services/media/render_clips.py

"""Renders planned clips on the media renderer."""

import asyncio
from collections.abc import Sequence
from uuid import UUID

from services.media.clips import PlannedClip
from services.media.domain import MediaOperationResult, MediaRendererError
from services.media.run_media_operation import run_media_operation
from services.media.utils import discard_staged_outputs, stage_media_input

# The renderer's default maximum instances.
RENDER_CONCURRENCY = 3


async def render_clips(
    workspace_id: UUID, clips: Sequence[PlannedClip]
) -> list[MediaOperationResult | MediaRendererError]:
    """Renders clips a few at a time; one clip's failure doesn't stop the others."""
    gate = asyncio.Semaphore(RENDER_CONCURRENCY)

    async def render(clip: PlannedClip) -> MediaOperationResult | MediaRendererError:
        async with gate:
            staged = (
                [await stage_media_input(workspace_id, clip.captions.encode(), extension=".ass")]
                if clip.captions
                else []
            )
            try:
                return await run_media_operation(
                    workspace_id=workspace_id,
                    sources=clip.sources,
                    operation=clip.operation,
                    staged_inputs=staged,
                )
            except MediaRendererError as exc:
                return exc
            finally:
                await discard_staged_outputs(staged)

    return list(await asyncio.gather(*(render(clip) for clip in clips)))
