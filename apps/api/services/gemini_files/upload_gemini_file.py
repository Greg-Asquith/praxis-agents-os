# apps/api/services/gemini_files/upload_gemini_file.py

"""Streams a stored object to the Gemini Files API and waits until Gemini can read it."""

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx2 as httpx

from services.gemini_files.delete_gemini_file import delete_gemini_file
from services.gemini_files.domain import (
    GEMINI_API_BASE_URL,
    GEMINI_FILES_MAX_BYTES,
    GEMINI_PROCESSING_POLL_SECONDS,
    GEMINI_PROCESSING_TIMEOUT_SECONDS,
    GEMINI_UPLOAD_CHUNK_BYTES,
    GeminiFile,
    GeminiFileError,
)
from services.gemini_files.utils import (
    gemini_api_key_header,
    gemini_files_client,
    parse_expiry,
    require_file_name,
)
from services.storage.domain import StorageObjectRef
from services.storage.factory import get_storage_provider


async def upload_gemini_file(
    ref: StorageObjectRef,
    *,
    size_bytes: int,
    media_type: str,
    display_name: str,
) -> GeminiFile:
    """Uploads one object without buffering it whole, then waits for Gemini to process it."""
    if size_bytes > GEMINI_FILES_MAX_BYTES:
        raise GeminiFileError(
            "This video is larger than the 2 GB Google accepts. Cut a shorter range first."
        )
    headers = gemini_api_key_header()
    async with gemini_files_client() as client:
        try:
            upload_url = await _start_upload(
                client, headers, size_bytes=size_bytes, media_type=media_type, name=display_name
            )
            uploaded = await _send_chunks(client, upload_url, ref, size_bytes=size_bytes)
            name = require_file_name(uploaded.get("name"))
        except httpx.HTTPError as exc:
            raise GeminiFileError(_upload_failure(exc)) from exc
        try:
            return await _wait_until_active(client, headers, uploaded, name=name)
        except Exception:
            await delete_gemini_file(name)
            raise


async def _start_upload(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    size_bytes: int,
    media_type: str,
    name: str,
) -> str:
    response = await client.post(
        f"{GEMINI_API_BASE_URL}/upload/v1beta/files",
        headers={
            **headers,
            "x-goog-upload-protocol": "resumable",
            "x-goog-upload-command": "start",
            "x-goog-upload-header-content-length": str(size_bytes),
            "x-goog-upload-header-content-type": media_type,
        },
        json={"file": {"display_name": name[:512]}},
    )
    response.raise_for_status()
    upload_url = response.headers.get("x-goog-upload-url", "")
    # The session URL carries its own authorisation, so the API key never goes elsewhere.
    if not upload_url.startswith(f"{GEMINI_API_BASE_URL}/"):
        raise GeminiFileError("Google didn't return an upload address.")
    return upload_url


async def _send_chunks(
    client: httpx.AsyncClient,
    upload_url: str,
    ref: StorageObjectRef,
    *,
    size_bytes: int,
) -> dict[str, Any]:
    offset = 0
    async for chunk in _fixed_chunks(get_storage_provider().stream_object(ref)):
        final = offset + len(chunk) >= size_bytes
        if offset + len(chunk) > size_bytes:
            raise GeminiFileError("The stored video changed size during upload.")
        response = await client.post(
            upload_url,
            headers={
                "x-goog-upload-command": "upload, finalize" if final else "upload",
                "x-goog-upload-offset": str(offset),
            },
            content=chunk,
        )
        response.raise_for_status()
        offset += len(chunk)
        if final:
            file = response.json().get("file")
            if not isinstance(file, dict):
                raise GeminiFileError("Google didn't confirm the upload.")
            return file
    raise GeminiFileError("The stored video changed size during upload.")


async def _fixed_chunks(stream: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    buffer = bytearray()
    async for piece in stream:
        buffer.extend(piece)
        while len(buffer) >= GEMINI_UPLOAD_CHUNK_BYTES:
            yield bytes(buffer[:GEMINI_UPLOAD_CHUNK_BYTES])
            del buffer[:GEMINI_UPLOAD_CHUNK_BYTES]
    if buffer:
        yield bytes(buffer)


async def _wait_until_active(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    file: dict[str, Any],
    *,
    name: str,
) -> GeminiFile:
    deadline = time.monotonic() + GEMINI_PROCESSING_TIMEOUT_SECONDS
    while file.get("state") not in ("ACTIVE", "FAILED"):
        if time.monotonic() >= deadline:
            raise GeminiFileError("Google took too long to prepare the video. Try again later.")
        await asyncio.sleep(GEMINI_PROCESSING_POLL_SECONDS)
        try:
            response = await client.get(f"{GEMINI_API_BASE_URL}/v1beta/{name}", headers=headers)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise GeminiFileError(_upload_failure(exc)) from exc
        file = response.json()
    if file.get("state") != "ACTIVE":
        raise GeminiFileError("Google couldn't process this video.")
    uri = file.get("uri")
    if not isinstance(uri, str) or not uri.startswith(f"{GEMINI_API_BASE_URL}/"):
        raise GeminiFileError("Google returned an unexpected file address.")
    return GeminiFile(name=name, uri=uri, expires_at=parse_expiry(file.get("expirationTime")))


def _upload_failure(exc: httpx.HTTPError) -> str:
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
        return "Google's video storage for this deployment is full or busy. Try again later."
    return "Google couldn't receive the video. Try again later."
