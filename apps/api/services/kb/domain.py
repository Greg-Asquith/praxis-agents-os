# apps/api/services/kb/domain.py

"""Knowledge-base domain constants and value objects."""

from dataclasses import dataclass

from core.exceptions.general import AppValidationError

KB_STATUS_PENDING = "pending"
KB_STATUS_PROCESSING = "processing"
KB_STATUS_READY = "ready"
KB_STATUS_ERROR = "error"

KB_SYNC_PENDING = "pending"
KB_SYNC_READY = "ready"
KB_SYNC_UNAVAILABLE = "unavailable"
KB_SYNC_DISCONNECTED = "disconnected"
KB_SYNC_ERROR = "error"

KB_SOURCE_UPLOAD = "upload"
KB_SOURCE_URL = "url"
KB_SOURCE_MANUAL = "manual"
KB_SOURCE_CONVERSATION = "conversation"
KB_SOURCE_INTEGRATION = "integration"

KB_REFRESHABLE_SOURCE_TYPES = frozenset({KB_SOURCE_URL, KB_SOURCE_INTEGRATION})

KB_FRAMED_SOURCE_TYPES = frozenset(
    {
        KB_SOURCE_URL,
        KB_SOURCE_CONVERSATION,
        KB_SOURCE_INTEGRATION,
    }
)

ANNOTATION_DEFAULTS: dict[str, bool] = {
    KB_SOURCE_UPLOAD: True,
    KB_SOURCE_URL: True,
    KB_SOURCE_MANUAL: False,
    KB_SOURCE_CONVERSATION: False,
    KB_SOURCE_INTEGRATION: False,
}

KB_COLLECTION_DIMS = 1024
KB_DOCUMENT_TITLE_MAX_CHARS = 500


class KBSourceUnavailableError(AppValidationError):
    """Reports that a refreshable source is definitively unavailable."""

    def __init__(self, *, error_code: str, status_code: int) -> None:
        super().__init__(
            "Knowledge-base URL source is unavailable",
            field="url",
            details={"status_code": status_code},
        )
        self.error_code = error_code


@dataclass(frozen=True)
class FetchedUrl:
    """Contains one bounded response from a public URL source."""

    data: bytes
    content_type: str
    etag: str | None
    last_modified: str | None
    not_modified: bool


@dataclass(frozen=True)
class ChunkDraft:
    """One exact canonical-markdown substring ready for persistence."""

    chunk_index: int
    content: str
    char_start: int
    char_end: int
    token_estimate: int
    heading_path: tuple[str, ...]
