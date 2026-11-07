# apps/api/services/files/attachment_text.py

"""Text conversion helpers for workspace file attachments."""

from models.files import File, FileRevision
from services.agents.runtime.untrusted import UntrustedContent, frame_untrusted_content
from services.assets.utils import normalize_content_type
from services.files.utils import (
    describe_video,
    file_revision_ref,
    format_duration,
    revision_video_metadata,
)
from services.storage.factory import get_storage_provider
from utils.document_markdown import convert_document_to_markdown, truncate_markdown

DOCUMENT_FORMAT_LABELS: dict[str, str] = {
    "application/json": "JSON",
    "application/msword": "Word",
    "application/vnd.ms-excel": "Spreadsheet",
    "application/vnd.ms-powerpoint": "PowerPoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PowerPoint",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Spreadsheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word",
    "text/csv": "CSV",
    "text/html": "HTML",
    "text/markdown": "Markdown",
    "text/plain": "Text",
}

MEDIA_FORMAT_LABELS: dict[str, str] = {
    "video/mp4": "MP4",
    "video/quicktime": "QuickTime",
    "video/webm": "WebM",
    "audio/mpeg": "MP3",
    "audio/mp4": "M4A",
    "audio/wav": "WAV",
}


async def markdown_for_revision(
    file: File,
    revision: FileRevision,
    *,
    max_bytes: int,
) -> str:
    """Return stored Markdown or convert the original revision bytes."""
    provider = get_storage_provider()
    if revision.markdown_object_key:
        data = await provider.get_object(file_revision_ref(revision, markdown=True))
        return truncate_markdown(data.decode("utf-8", errors="replace"), max_bytes=max_bytes)

    data = await provider.get_object(file_revision_ref(revision))
    return await convert_document_to_markdown(
        data,
        content_type=revision.content_type,
        filename=file.name,
        max_bytes=max_bytes,
    )


def attachment_text_payload(
    file: File,
    revision: FileRevision,
    markdown: str,
) -> bytes:
    """Return converted Markdown framed with the original file's provenance."""
    content_type = normalize_content_type(revision.content_type)
    format_label = DOCUMENT_FORMAT_LABELS.get(content_type, content_type)
    header = (
        f"Attached file: {file.name}\n"
        f"File id: {file.id}\n"
        f"Original format: {format_label} ({content_type}), {revision.size_bytes:,} bytes\n"
        "This is a text conversion. To edit the original .pptx, .xlsx, or .docx file, or read "
        "its charts and images, pass the file id to read_presentation, read_workbook, or "
        "read_word_document."
    )
    return f"{header}\n\n{markdown}".encode()


def media_attachment_note(file: File, revision: FileRevision, *, audio: bool = False) -> bytes:
    """Returns a reference to an attached video or audio File for the model, without its bytes."""
    content_type = normalize_content_type(revision.content_type)
    format_label = MEDIA_FORMAT_LABELS.get(content_type, content_type)
    kind = "Audio" if audio else "Video"
    # The name is uploader-controlled, so it is framed like other untrusted File content.
    name = frame_untrusted_content(
        UntrustedContent(
            source_kind="file",
            source_ref=f"file:{file.id}/revision:{revision.id}",
            content=f"{kind} name: {file.name}",
        )
    )
    use = (
        "To put it under video clips as music, pass the file id to cut_video_clips."
        if audio
        else "To work with it, pass the file id to the video tools."
    )
    return (
        f"Attached {kind.lower()}\n"
        f"File id: {file.id}\n"
        f"Format: {format_label} ({content_type}), {revision.size_bytes:,} bytes\n"
        f"{_media_state_line(file, revision, kind)}"
        f"{name}\n"
        f"The {kind.lower()} itself isn't included in this message. {use}"
    ).encode()


def _media_state_line(file: File, revision: FileRevision, kind: str) -> str:
    metadata = revision_video_metadata(revision)
    if metadata is not None:
        summary = (
            format_duration(metadata.duration_ms) if kind == "Audio" else describe_video(metadata)
        )
        return f"{kind}: {summary}\n"
    if file.processing_status == "error":
        return f"{kind} couldn't be prepared: {file.processing_error}\n"
    if file.processing_status in ("pending", "processing"):
        return f"{kind} is still being prepared; its duration isn't known yet.\n"
    return ""
