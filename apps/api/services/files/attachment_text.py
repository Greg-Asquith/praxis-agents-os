# apps/api/services/files/attachment_text.py

"""Text conversion helpers for workspace file attachments."""

from models.files import File, FileRevision
from services.assets.utils import normalize_content_type
from services.files.utils import private_ref_from_key
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


async def markdown_for_revision(
    file: File,
    revision: FileRevision,
    *,
    max_bytes: int,
) -> str:
    """Return stored Markdown or convert the original revision bytes."""
    provider = get_storage_provider()
    if revision.markdown_object_key:
        data = await provider.get_object(private_ref_from_key(revision.markdown_object_key))
        return truncate_markdown(data.decode("utf-8", errors="replace"), max_bytes=max_bytes)

    data = await provider.get_object(private_ref_from_key(revision.object_key))
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
        "This is a text conversion. To work with the original file (for example to edit "
        "it or read charts and images), pass the file id to run_code."
    )
    return f"{header}\n\n{markdown}".encode()
