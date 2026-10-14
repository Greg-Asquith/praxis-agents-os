# apps/api/services/media/get_video_transcript.py

"""Loads a video revision's transcript, creating it once on first need."""

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import replace

from pydantic import ValidationError
from pydantic_ai.usage import RunUsage
from sqlalchemy.ext.asyncio import AsyncSession

from models.files import FileRevision
from services.ai_usage.domain import AIUsageEventData
from services.ai_usage.run_metered_helper import run_metered_helper
from services.files.utils import (
    private_ref_from_key,
    revision_transcript_key,
    revision_video_metadata,
)
from services.media.domain import (
    INVALID_RESPONSE_MESSAGE,
    MAX_AUDIO_CHUNKS,
    ExtractAudioOperation,
    ExtractAudioResult,
    MediaOperationResult,
    MediaRendererError,
    StagedMediaOutput,
    Transcript,
    TranscriptionError,
    TranscriptWord,
)
from services.media.run_media_operation import run_media_operation
from services.media.transcription_providers import ChunkTranscript, TranscriptionProvider
from services.media.utils import discard_staged_outputs, sentences_from_words
from services.storage.factory import get_storage_provider

# Chunks aim at this share of the provider's limit, so a split moved into a silence still fits.
CHUNK_FILL = 0.8


async def get_video_transcript(
    db: AsyncSession,
    *,
    revision: FileRevision,
    provider: TranscriptionProvider,
    language: str | None,
    usage: AIUsageEventData,
    on_stage: Callable[[str], Awaitable[None]],
) -> tuple[Transcript, bool]:
    """Returns the transcript and whether this call created it.

    The caller must have resolved ``revision`` for its workspace. A stored
    transcript is reused whatever ``provider`` and ``language`` say, so a
    revision is transcribed, and billed, once.
    """
    if revision.transcript_object_key:
        return await _load(revision), False
    metadata = revision_video_metadata(revision)
    if metadata is None:
        raise TranscriptionError("The video is still being prepared. Try again in a minute.")
    if not metadata.has_audio:
        raise TranscriptionError("The video has no audio to transcribe.")
    chunks = min(
        MAX_AUDIO_CHUNKS,
        max(1, math.ceil(metadata.duration_ms / (provider.max_chunk_ms * CHUNK_FILL))),
    )
    await on_stage("Extracting Audio")
    try:
        extracted = await run_media_operation(
            workspace_id=revision.workspace_id,
            sources=[revision],
            operation=ExtractAudioOperation(chunks=chunks),
        )
    except MediaRendererError as exc:
        raise TranscriptionError(exc.message) from exc
    try:
        await on_stage("Transcribing")
        transcribed = await _transcribe(extracted, provider, language, usage, metadata.duration_ms)
    finally:
        await discard_staged_outputs(extracted.outputs)

    words = _on_source_timeline(transcribed, extracted.result)
    transcript = Transcript(
        provider=provider.name,
        model=provider.model,
        language=next((chunk.language for chunk in transcribed if chunk.language), None),
        duration_ms=metadata.duration_ms,
        words=words,
        sentences=sentences_from_words(words),
    )
    data = transcript.model_dump_json().encode()
    ref = private_ref_from_key(
        revision_transcript_key(revision.workspace_id, revision.file_id, revision.id)
    )
    await get_storage_provider().put_object(ref, data, content_type="application/json")
    revision.transcript_object_key = ref.key
    revision.transcript_size_bytes = len(data)
    await db.flush()
    return transcript, True


async def _load(revision: FileRevision) -> Transcript:
    data = await get_storage_provider().get_object(
        private_ref_from_key(revision.transcript_object_key)
    )
    try:
        return Transcript.model_validate_json(data)
    except ValidationError as exc:
        raise TranscriptionError("The stored transcript couldn't be read.") from exc


async def _transcribe(
    extracted: MediaOperationResult,
    provider: TranscriptionProvider,
    language: str | None,
    usage: AIUsageEventData,
    duration_ms: int,
) -> list[ChunkTranscript]:
    limit = asyncio.Semaphore(provider.concurrency)

    async def call(run_usage: RunUsage) -> list[ChunkTranscript]:
        async def one(chunk: StagedMediaOutput) -> ChunkTranscript:
            async with limit:
                return await provider.transcribe(chunk, language, run_usage)

        return list(await asyncio.gather(*(one(chunk) for chunk in extracted.outputs)))

    event = replace(
        usage,
        details={"audio_seconds": round(duration_ms / 1000), "chunks": len(extracted.outputs)},
    )
    return await run_metered_helper(event, call)


def _on_source_timeline(
    transcribed: list[ChunkTranscript], result: ExtractAudioResult
) -> tuple[TranscriptWord, ...]:
    """Moves each chunk's words onto the video's timeline and keeps them inside their chunk."""
    if not isinstance(result, ExtractAudioResult) or len(result.chunks_ms) != len(transcribed):
        raise TranscriptionError(INVALID_RESPONSE_MESSAGE)
    words: list[TranscriptWord] = []
    for (start_ms, end_ms), chunk in zip(result.chunks_ms, transcribed, strict=True):
        for word in chunk.words:
            word_start = min(start_ms + word.start_ms, end_ms)
            words.append(
                word.model_copy(
                    update={
                        "start_ms": word_start,
                        "end_ms": max(word_start, min(start_ms + word.end_ms, end_ms)),
                    }
                )
            )
    return tuple(words)
