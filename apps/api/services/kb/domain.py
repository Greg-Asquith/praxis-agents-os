# apps/api/services/kb/domain.py

"""Knowledge-base domain constants and value objects."""

from dataclasses import dataclass

KB_STATUS_PENDING = "pending"
KB_STATUS_PROCESSING = "processing"
KB_STATUS_READY = "ready"
KB_STATUS_ERROR = "error"

KB_SOURCE_UPLOAD = "upload"
KB_SOURCE_URL = "url"
KB_SOURCE_MANUAL = "manual"
KB_SOURCE_CONVERSATION = "conversation"
KB_SOURCE_INTEGRATION = "integration"

ANNOTATION_DEFAULTS: dict[str, bool] = {
    KB_SOURCE_UPLOAD: True,
    KB_SOURCE_URL: True,
    KB_SOURCE_MANUAL: False,
    KB_SOURCE_CONVERSATION: False,
    KB_SOURCE_INTEGRATION: False,
}

KB_COLLECTION_DIMS = 1024


@dataclass(frozen=True)
class ChunkDraft:
    """One exact canonical-markdown substring ready for persistence."""

    chunk_index: int
    content: str
    char_start: int
    char_end: int
    token_estimate: int
    heading_path: tuple[str, ...]
