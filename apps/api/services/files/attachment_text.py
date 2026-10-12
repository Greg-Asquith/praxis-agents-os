# apps/api/services/files/attachment_text.py

"""Text conversion helpers for workspace file attachments."""

from models.files import File, FileRevision
from services.agents.runtime.untrusted import UntrustedContent, frame_untrusted_content
from services.assets.utils import normalize_content_type
from services.files.utils import describe_video, file_revision_ref, revision_video_metadata
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

VIDEO_FORMAT_LABELS: dict[str, str] = {
    "video/mp4": "MP4",
    "video/quicktime": "QuickTime",
    "video/webm": "WebM",
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


def video_attachment_note(file: File, revision: FileRevision) -> bytes:
    """Returns a reference to an attached video for the model, without its bytes."""
    content_type = normalize_content_type(revision.content_type)
    format_label = VIDEO_FORMAT_LABELS.get(content_type, content_type)
    # The name is uploader-controlled, so it is framed like other untrusted File content.
    name = frame_untrusted_content(
        UntrustedContent(
            source_kind="file",
            source_ref=f"file:{file.id}/revision:{revision.id}",
            content=f"Video name: {file.name}",
        )
    )
    return (
        "Attached video\n"
        f"File id: {file.id}\n"
        f"Format: {format_label} ({content_type}), {revision.size_bytes:,} bytes\n"
        f"{_video_state_line(file, revision)}"
        f"{name}\n"
        "The video itself isn't included in this message. To work with it, pass the file id "
        "to the video tools."
    ).encode()


def _video_state_line(file: File, revision: FileRevision) -> str:
    metadata = revision_video_metadata(revision)
    if metadata is not None:
        return f"Video: {describe_video(metadata)}\n"
    if file.processing_status == "error":
        return f"Video couldn't be prepared: {file.processing_error}\n"
    if file.processing_status in ("pending", "processing"):
        return "Video is still being prepared; its duration isn't known yet.\n"
    return ""
