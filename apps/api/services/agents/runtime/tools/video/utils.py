# apps/api/services/agents/runtime/tools/video/utils.py

"""Steps the video tools share: the caller's own video, progress, transcripts, and audit."""

import re
from collections.abc import Awaitable, Callable
from uuid import UUID

from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.exceptions import ToolFailed

from core.settings import settings
from models.files import File, FileRevision
from services.agents.models.domain import PROVIDER_GOOGLE
from services.agents.models.resolution import has_available_helper_model
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.entity_references.domain import FileReference, internal_entity_id
from services.agents.runtime.stream_protocol import ToolProgressEvent
from services.agents.runtime.tools.files.utils import current_file_revision
from services.ai_usage.domain import PURPOSE_VIDEO_TRANSCRIPTION, AIUsageEventData
from services.audit_events import AuditAction, AuditActorType, AuditResourceType
from services.audit_events.operations import safe_record_operation_audit_event
from services.files.contract import FileCategory
from services.files.domain import VideoMetadata
from services.files.utils import format_duration, revision_video_metadata
from services.media.domain import Transcript, TranscriptionError
from services.media.get_video_transcript import get_video_transcript
from services.media.transcription_providers import transcription_provider
from services.media.understanding import parse_timestamp

# Below Gemini's 20 MB inline request ceiling; longer video goes by URI or Files API upload.
INLINE_VIDEO_MAX_BYTES = 18 * 1024 * 1024
DEFAULT_VIDEO_FPS = 1.0
DETAIL_VIDEO_FPS = 5.0
MAX_TEXT_ARGUMENT_CHARS = 2000
_LANGUAGE = re.compile(r"^[a-z]{2,3}(-[A-Z]{2})?$")


def video_understanding_available() -> bool:
    """Checks Gemini can watch workspace video; without long video input, only short ones."""
    return has_available_helper_model(
        PROVIDER_GOOGLE, {PROVIDER_GOOGLE: settings.VIDEO_UNDERSTANDING_MODEL}
    )


async def workspace_video(
    ctx: RunContext[RuntimeDeps], file_id: FileReference, *, tool_name: str
) -> tuple[File, FileRevision]:
    """Returns the current revision of one of the workspace's own videos."""
    file, revision = await current_file_revision(ctx, internal_entity_id(file_id))
    if file.category != FileCategory.VIDEO.value:
        raise ModelRetry(f"{tool_name} requires a video file from workspace Files.")
    if revision.workspace_id != ctx.deps.workspace.id:
        raise ModelRetry(f"{tool_name} can only read this workspace's own videos.")
    return file, revision


def probed_video(revision: FileRevision) -> VideoMetadata:
    metadata = revision_video_metadata(revision)
    if metadata is None:
        raise ToolFailed("The video is still being prepared. Try again in a minute.")
    return metadata


def video_range(
    start: str | None, end: str | None, *, duration_ms: int, max_ms: int, detail: bool
) -> tuple[int, int, float]:
    """Parses an optional MM:SS range and picks a frame rate that keeps the call bounded."""
    start_ms = parse_timestamp(start) if start else 0
    end_ms = parse_timestamp(end) if end else duration_ms
    if start_ms is None or end_ms is None:
        raise ModelRetry("start and end must be times such as 12:30 or 1:02:05.")
    end_ms = min(end_ms, duration_ms)
    if end_ms <= start_ms:
        raise ModelRetry(
            f"start must be before end, inside the video's {format_duration(duration_ms)}."
        )
    if not detail:
        return start_ms, end_ms, DEFAULT_VIDEO_FPS
    # Five times the frames costs five times the tokens, so detail covers a fifth as much.
    if end_ms - start_ms > max_ms / DETAIL_VIDEO_FPS:
        raise ModelRetry(
            f"detail works on up to {format_duration(int(max_ms / DETAIL_VIDEO_FPS))} of video. "
            "Pass start and end, or omit detail."
        )
    return start_ms, end_ms, DETAIL_VIDEO_FPS


def text_argument(value: str, *, name: str) -> str:
    text = value.strip()
    if not text:
        raise ModelRetry(f"{name} must not be empty.")
    if len(text) > MAX_TEXT_ARGUMENT_CHARS:
        raise ModelRetry(f"{name} must be at most {MAX_TEXT_ARGUMENT_CHARS} characters.")
    return text


def language_argument(language: str | None) -> str | None:
    language = (language or "").strip() or None
    if language is not None and not _LANGUAGE.match(language):
        raise ModelRetry("language must be a locale such as en-GB, or omitted.")
    return language


def progress(ctx: RunContext[RuntimeDeps]) -> Callable[[str], Awaitable[None]]:
    async def stage(name: str) -> None:
        await ctx.deps.sink.emit(ToolProgressEvent(tool_call_id=ctx.tool_call_id, stage=name))

    return stage


def usage_event(
    ctx: RunContext[RuntimeDeps], *, provider: str, model: str, purpose: str
) -> AIUsageEventData:
    return AIUsageEventData(
        workspace_id=ctx.deps.workspace.id,
        provider=provider,
        model=model,
        purpose=purpose,
        agent_id=ctx.deps.agent.id,
        user_id=ctx.deps.user.id,
        run_id=ctx.deps.run.id,
        conversation_id=ctx.deps.conversation.id,
    )


async def video_transcript(
    ctx: RunContext[RuntimeDeps],
    file: File,
    revision: FileRevision,
    *,
    language: str | None,
    tool_name: str,
) -> Transcript:
    """Returns the revision's transcript, creating and auditing it on first need."""
    provider = transcription_provider()
    if provider is None:
        raise ToolFailed("Transcription isn't available on this deployment.")
    try:
        transcript, created = await get_video_transcript(
            ctx.deps.db,
            revision=revision,
            provider=provider,
            language=language,
            usage=usage_event(
                ctx,
                provider=provider.name,
                model=provider.model,
                purpose=PURPOSE_VIDEO_TRANSCRIPTION,
            ),
            on_stage=progress(ctx),
        )
    except TranscriptionError as exc:
        raise ToolFailed(str(exc)) from exc
    if created:
        # Audio may go to a provider other than the one that reads the video, so record which.
        await record_video_audit(
            ctx,
            file.id,
            revision.id,
            operation="video_transcription",
            tool_name=tool_name,
            details={
                "provider": transcript.provider,
                "model": transcript.model,
                "duration_ms": transcript.duration_ms,
            },
        )
        # The audio has reached the provider, so keep the record and the transcript.
        await ctx.deps.db.commit()
    return transcript


async def record_video_audit(
    ctx: RunContext[RuntimeDeps],
    file_id: UUID,
    revision_id: UUID,
    *,
    operation: str,
    tool_name: str,
    details: dict[str, object],
) -> None:
    await safe_record_operation_audit_event(
        ctx.deps.db,
        workspace_id=ctx.deps.workspace.id,
        action=AuditAction.READ,
        resource_type=AuditResourceType.FILE,
        resource_id=file_id,
        actor_type=AuditActorType.AGENT,
        actor_id=ctx.deps.agent.id,
        actor_display=ctx.deps.agent.name,
        requested_by_user_id=ctx.deps.user.id,
        details={
            "operation": operation,
            "tool_name": tool_name,
            "run_id": str(ctx.deps.run.id),
            "revision_id": str(revision_id),
            **details,
        },
    )
