# apps/api/services/media/utils.py

"""Helpers for the media renderer client."""

import asyncio
import logging
import re
from uuid import UUID, uuid4

from core.settings import settings
from services.media.domain import (
    MEDIA_STAGING_PREFIX,
    MediaRendererError,
    StagedMediaOutput,
    TranscriptSentence,
    TranscriptWord,
)
from services.storage.domain import StorageBucket, StorageObjectRef, make_storage_object_ref
from services.storage.factory import get_storage_provider

logger = logging.getLogger(__name__)

_SENTENCE_END = re.compile(r"[.?!][\"')\]]*$")
SENTENCE_PAUSE_MS = 2000


def staging_ref(
    workspace_id: UUID, request_id: UUID, index: int, extension: str
) -> StorageObjectRef:
    """Returns a platform staging key scoped to one workspace and one renderer request."""
    return make_storage_object_ref(
        StorageBucket.PLATFORM_PRIVATE,
        f"{MEDIA_STAGING_PREFIX}/{workspace_id}/{request_id}/output-{index}{extension}",
    )


async def stage_media_input(workspace_id: UUID, data: bytes, *, extension: str) -> StorageObjectRef:
    """Writes a file the API built, such as captions, to staging for one renderer request."""
    ref = make_storage_object_ref(
        StorageBucket.PLATFORM_PRIVATE,
        f"{MEDIA_STAGING_PREFIX}/{workspace_id}/{uuid4()}/input{extension}",
    )
    await get_storage_provider().put_object(
        ref, data, content_type="application/octet-stream", overwrite=False
    )
    return ref


def renderer_transfer_url(url: str) -> str:
    """Points local storage URLs at the API origin the renderer container can reach."""
    if get_storage_provider().provider_key != "local_fs":
        return url
    origin = settings.APP_BASE_URL.rstrip("/")
    if not url.startswith(f"{origin}/"):
        raise MediaRendererError("unavailable", "The media renderer can't reach local storage.")
    return settings.MEDIA_RENDERER_LOCAL_STORAGE_URL.rstrip("/") + url[len(origin) :]


async def renderer_auth_headers() -> dict[str, str]:
    """Returns the renderer's authorization header for the configured auth mode."""
    if settings.MEDIA_RENDERER_AUTH == "none":
        return {}
    if settings.MEDIA_RENDERER_AUTH == "shared_secret":
        secret = settings.MEDIA_RENDERER_SHARED_SECRET.get_secret_value()
        return {"authorization": f"Bearer {secret}"}
    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import id_token
    except ImportError as exc:
        raise MediaRendererError("unavailable", "The media renderer isn't available.") from exc
    token = await asyncio.to_thread(id_token.fetch_id_token, Request(), settings.MEDIA_RENDERER_URL)
    return {"authorization": f"Bearer {token}"}


async def discard_staged_outputs(
    outputs: tuple[StagedMediaOutput, ...] | list[StorageObjectRef],
) -> None:
    """Deletes staged renderer outputs; the staging lifecycle rule removes any left behind."""
    provider = get_storage_provider()
    for item in outputs:
        ref = item.ref if isinstance(item, StagedMediaOutput) else item
        try:
            await provider.delete_object(ref)
        except Exception:
            logger.warning("Failed to delete staged media output", extra={"object_key": ref.key})


def normalized_token(text: str) -> str:
    """Lowercases a word and drops punctuation, for matching one provider's words to its text."""
    return "".join(
        character for character in text.lower() if character.isalnum() or character == "'"
    )


def sentences_from_words(words: tuple[TranscriptWord, ...]) -> tuple[TranscriptSentence, ...]:
    """Groups words into sentences at end punctuation, a change of speaker, or a long pause."""
    sentences: list[TranscriptSentence] = []
    current: list[TranscriptWord] = []
    for index, word in enumerate(words):
        current.append(word)
        following = words[index + 1] if index + 1 < len(words) else None
        if (
            following is None
            or _SENTENCE_END.search(word.text)
            or following.speaker != word.speaker
            or following.start_ms - word.end_ms >= SENTENCE_PAUSE_MS
        ):
            sentences.append(
                TranscriptSentence(
                    text=" ".join(item.text for item in current),
                    start_ms=current[0].start_ms,
                    end_ms=current[-1].end_ms,
                    speaker=word.speaker,
                )
            )
            current = []
    return tuple(sentences)


def transcript_srt(sentences: tuple[TranscriptSentence, ...]) -> str:
    """Formats sentences as SubRip cues, one cue per sentence."""
    cues = [
        f"{index}\n{_srt_time(sentence.start_ms)} --> {_srt_time(sentence.end_ms)}\n"
        f"{sentence.text}\n"
        for index, sentence in enumerate(sentences, start=1)
    ]
    return "\n".join(cues)


def _srt_time(milliseconds: int) -> str:
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"
