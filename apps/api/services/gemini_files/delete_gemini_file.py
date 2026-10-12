# apps/api/services/gemini_files/delete_gemini_file.py

"""Deletes an uploaded Gemini file without failing the caller."""

import logging

import httpx2 as httpx

from services.gemini_files.domain import GEMINI_API_BASE_URL, GeminiFileError
from services.gemini_files.utils import (
    gemini_api_key_header,
    gemini_files_client,
    require_file_name,
)

logger = logging.getLogger(__name__)


async def delete_gemini_file(name: str) -> None:
    """Deletes one Files API upload; Google removes anything missed after 48 hours."""
    try:
        file_name = require_file_name(name)
        async with gemini_files_client() as client:
            response = await client.delete(
                f"{GEMINI_API_BASE_URL}/v1beta/{file_name}", headers=gemini_api_key_header()
            )
        if response.status_code not in (200, 404):
            response.raise_for_status()
    except (GeminiFileError, httpx.HTTPError):
        logger.warning("Failed to delete a Gemini file", extra={"gemini_file": name}, exc_info=True)
