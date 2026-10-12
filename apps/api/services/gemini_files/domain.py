# apps/api/services/gemini_files/domain.py

"""Gemini Files API limits and results."""

from dataclasses import dataclass
from datetime import datetime

GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com"
# Documented limits: 2 GB per file, 20 GB per project, deleted after 48 hours.
GEMINI_FILES_MAX_BYTES = 2 * 1024 * 1024 * 1024
GEMINI_FILES_RETENTION_HOURS = 48
# Resumable upload chunks must be multiples of Google's 8 MiB granularity.
GEMINI_UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024
GEMINI_PROCESSING_TIMEOUT_SECONDS = 300
GEMINI_PROCESSING_POLL_SECONDS = 2.0


@dataclass(frozen=True)
class GeminiFile:
    """An uploaded file Gemini can read by URI until it expires."""

    name: str
    uri: str
    expires_at: datetime


class GeminiFileError(Exception):
    """The Files API refused or failed an upload; the message is safe to show."""
