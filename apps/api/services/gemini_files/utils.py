# apps/api/services/gemini_files/utils.py

"""Helpers for Gemini Files API requests."""

import re
from datetime import UTC, datetime, timedelta

import httpx2 as httpx

from core.settings import settings
from services.gemini_files.domain import GEMINI_FILES_RETENTION_HOURS, GeminiFileError

_FILE_NAME = re.compile(r"files/[a-z0-9-]{1,64}")
_FRACTION = re.compile(r"\.(\d{6})\d*")


def gemini_files_client() -> httpx.AsyncClient:
    """Returns a client for one Files API exchange; chunk uploads need a long read timeout."""
    return httpx.AsyncClient(timeout=httpx.Timeout(timeout=300, connect=10))


def gemini_api_key_header() -> dict[str, str]:
    """Returns the Gemini API key header, or refuses when the key isn't configured."""
    secret = settings.GOOGLE_API_KEY
    key = secret.get_secret_value().strip() if secret is not None else ""
    if not key:
        raise GeminiFileError("Google isn't configured for video input.")
    return {"x-goog-api-key": key}


def require_file_name(name: object) -> str:
    """Returns a Files API resource name, refusing anything that could address another path."""
    if not isinstance(name, str) or not _FILE_NAME.fullmatch(name):
        raise GeminiFileError("Google returned an unexpected file name.")
    return name


def parse_expiry(value: object) -> datetime:
    """Parses the Files API expiry, falling back to the documented retention."""
    if isinstance(value, str):
        try:
            # Google can send nanoseconds, which fromisoformat rejects.
            return datetime.fromisoformat(_FRACTION.sub(r".\1", value))
        except ValueError:
            pass
    return datetime.now(UTC) + timedelta(hours=GEMINI_FILES_RETENTION_HOURS)
