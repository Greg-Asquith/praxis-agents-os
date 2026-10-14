# apps/api/tests/support/media.py

"""Media renderer test helpers."""

import importlib
from collections.abc import Awaitable, Callable, Sequence
from hashlib import sha256
from pathlib import Path
from urllib.parse import unquote, urlsplit
from uuid import UUID

import pytest

from core.settings import settings
from models.files import File
from models.workspace import Workspace
from services.agents.runtime.entity_references.domain import FileReference
from services.files.utils import private_ref_from_key, revision_transcript_key
from services.media.domain import Transcript, TranscriptWord
from services.media.utils import sentences_from_words
from services.storage.domain import StorageBucket, StorageObjectRef, make_storage_object_ref
from services.storage.factory import get_storage_provider
from tests.factories import build_file, build_file_revision
from tests.support.scenario import ToolCall, ToolTurn
from tests.support.storage import reset_storage_provider_cache

# The package exports a function with the module's name.
run_media_operation_module = importlib.import_module("services.media.run_media_operation")


def use_fake_renderer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    post: Callable[[dict], Awaitable[dict]],
) -> None:
    """Stages through local storage and answers each renderer request with ``post``."""
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "APP_BASE_URL", "http://testserver")
    monkeypatch.setattr(settings, "MEDIA_RENDERER_URL", "http://renderer.test")
    monkeypatch.setattr(settings, "MEDIA_RENDERER_AUTH", "none")
    monkeypatch.setattr(
        settings, "MEDIA_RENDERER_LOCAL_STORAGE_URL", "http://host.docker.internal:8000"
    )
    reset_storage_provider_cache()
    monkeypatch.setattr(run_media_operation_module, "_post", post)


def file_tool_turn(tool_name: str, file: File, call_id: str | None = None, **arguments) -> ToolTurn:
    """Scripts one call of a tool that takes the File as `file_id`."""
    reference = FileReference(entity_id=file.id, label=file.name).model_dump(mode="json")
    return ToolTurn(
        (ToolCall(tool_name, {"file_id": reference, **arguments}, call_id or tool_name),)
    )


def staged_ref(url: str) -> StorageObjectRef:
    """Returns the platform staging object a local signed upload URL writes to."""
    key = unquote(urlsplit(url).path.split("/upload/platform_private/", 1)[1])
    return make_storage_object_ref(StorageBucket.PLATFORM_PRIVATE, key)


async def persist_analysed_video(
    db_session_factory,
    *,
    workspace_id: UUID,
    user_id: UUID,
    name: str,
    duration_ms: int,
    speech: Sequence[tuple[str, int, int]] | None,
    shot_cuts_ms: Sequence[int] = (),
) -> File:
    """Stores a probed 1920x1080 video with its shot cuts and, unless speech is None, transcript."""
    async with db_session_factory() as db:
        workspace = await db.get_one(Workspace, workspace_id)
        content = name.encode()
        digest = sha256(content).hexdigest()
        file = build_file(
            workspace=workspace,
            name=name,
            category="video",
            content_type="video/mp4",
            extension=".mp4",
            size_bytes=len(content),
            content_hash=digest,
        )
        db.add(file)
        await db.flush()
        revision = build_file_revision(
            file, created_by_user_id=user_id, size_bytes=len(content), content_hash=digest
        )
        revision.media_metadata = {
            "duration_ms": duration_ms,
            "width": 1920,
            "height": 1080,
            "fps": 30.0,
            "video_codec": "h264",
            "has_audio": True,
            "audio_codec": "aac",
            "rotation": 0,
        }
        revision.shot_cuts_ms = list(shot_cuts_ms)
        storage = get_storage_provider()
        await storage.put_object(
            private_ref_from_key(revision.object_key), content, content_type="video/mp4"
        )
        if speech is not None:
            words = tuple(
                TranscriptWord(text=text, start_ms=start, end_ms=end) for text, start, end in speech
            )
            transcript = Transcript(
                provider="openai",
                model="whisper-1",
                duration_ms=duration_ms,
                words=words,
                sentences=sentences_from_words(words),
            )
            key = revision_transcript_key(workspace.id, file.id, revision.id)
            data = transcript.model_dump_json().encode()
            await storage.put_object(private_ref_from_key(key), data)
            revision.transcript_object_key = key
            revision.transcript_size_bytes = len(data)
        db.add(revision)
        await db.flush()
        file.current_revision_id = revision.id
        await db.commit()
        return file
