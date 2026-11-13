# apps/api/integrations/google_ads/operations/video_upload.py

"""Uploads workspace videos to YouTube through Google Ads and reads their processing state."""

import asyncio
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2

from core.exceptions.integration import (
    IntegrationError,
    IntegrationFailureDisposition,
    IntegrationValidationError,
)
from services.integrations.files import RevisionStream
from services.integrations.http import IntegrationRequestPolicy

from ..client import GOOGLE_ADS_UPLOAD_BASE_URL, GoogleAdsClient
from .media import VideoSource
from .utils import stream_rows

_OPERATION = "upload_media"
# Chunks are whole multiples of Google's granularity, about this size.
_CHUNK_BYTES = 8 * 1024 * 1024
_MAX_GRANULARITY = 64 * 1024 * 1024
_MAX_RESUMES = 3
_CANCEL_TIMEOUT_SECONDS = 5
# Matches checkpoint references, so the session can be recorded before any bytes go.
_SESSION = re.compile(r"[A-Za-z0-9_.:-]{1,256}")
PROCESSED = "PROCESSED"
# Google won't make a video from these; the upload has to start again.
FAILED_STATES = frozenset({"FAILED", "REJECTED", "UNAVAILABLE"})
_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")


@dataclass
class UploadProgress:
    """How far one video upload got, so an interruption is reported truthfully."""

    session: str | None = None
    # Set once the request that finishes the upload has been sent.
    finalizing: bool = False
    # The `youTubeVideoUploads` ID, once Google confirmed it.
    upload_id: str | None = None


@dataclass(frozen=True, slots=True)
class UploadState:
    state: str
    video_id: str | None


def invalid_upload_reply(message: str) -> IntegrationValidationError:
    return IntegrationValidationError(
        message,
        provider_key="google_ads",
        operation=_OPERATION,
        error_code="invalid_upload_reply",
        failure_disposition=IntegrationFailureDisposition.AMBIGUOUS,
    )


async def upload_video(
    client: GoogleAdsClient,
    *,
    customer: str,
    login_customer_id: str,
    source: VideoSource,
    title: str,
    description: str | None,
    progress: UploadProgress,
    on_session: Callable[[str], Awaitable[None]],
) -> str:
    """Streams the pinned revision to Google in its chunk size; returns the upload's ID.

    `on_session` records the session before the first chunk. After an unclear chunk reply
    the upload resumes from the size Google says it received. An upload that stops before
    the final chunk is cancelled, so no video is made from part of a File.
    """
    url, granularity = await _start(
        client, customer, login_customer_id, source.revision.size_bytes, title, description
    )
    progress.session = _session(url)
    await on_session(progress.session)
    try:
        async with RevisionStream(
            source.revision, provider_key="google_ads", operation=_OPERATION
        ) as stream:
            reply = await _send_chunks(client, url, stream, _chunk_size(granularity), progress)
    except (asyncio.CancelledError, Exception):
        if not progress.finalizing:
            await _cancel(client, url)
        raise
    progress.upload_id = _upload_id(customer, reply)
    return progress.upload_id


async def _start(
    client: GoogleAdsClient,
    customer: str,
    login_customer_id: str,
    size: int,
    title: str,
    description: str | None,
) -> tuple[str, int]:
    upload: dict[str, Any] = {"video_title": title}
    if description:
        upload["video_description"] = description
    response = await client.upload_request(
        "POST",
        f"{GOOGLE_ADS_UPLOAD_BASE_URL}/customers/{customer}/youTubeVideoUploads:create",
        operation=_OPERATION,
        login_customer_id=login_customer_id,
        headers={
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(size),
        },
        json={"customer_id": customer, "you_tube_video_upload": upload},
    )
    url = response.headers.get("x-goog-upload-url") or ""
    granularity = response.headers.get("x-goog-upload-chunk-granularity") or ""
    if not url or not granularity.isdigit() or not 0 < int(granularity) <= _MAX_GRANULARITY:
        raise invalid_upload_reply("Google Ads didn't return an upload address.")
    return url, int(granularity)


def _session(url: str) -> str:
    """The upload session's ID, which the address carries as `upload_id`."""
    values = parse_qs(urlsplit(url).query).get("upload_id") or [""]
    if not _SESSION.fullmatch(values[0]):
        raise invalid_upload_reply("Google Ads returned an upload address without a session.")
    return values[0]


def _chunk_size(granularity: int) -> int:
    return max(granularity, _CHUNK_BYTES // granularity * granularity)


async def _send_chunks(
    client: GoogleAdsClient,
    url: str,
    stream: RevisionStream,
    chunk_size: int,
    progress: UploadProgress,
) -> dict[str, Any]:
    """Reads the File once in order; returns the reply to the final chunk."""
    offset = 0
    while True:
        data = await stream.read(min(chunk_size, stream.size - offset))
        final = offset + len(data) == stream.size
        if final:
            # The hash check runs here, before the request that makes the video.
            await stream.verify()
            progress.finalizing = True
        reply = await _send_chunk(client, url, data, offset, final=final)
        if final:
            return reply
        offset += len(data)


async def _send_chunk(
    client: GoogleAdsClient, url: str, data: bytes, offset: int, *, final: bool
) -> dict[str, Any]:
    """Sends one chunk, resuming from Google's received size after an unclear reply."""
    sent_from = offset
    resumes = 0
    while True:
        try:
            response = await client.upload_request(
                "PUT",
                url,
                operation=_OPERATION,
                headers={
                    "X-Goog-Upload-Command": "upload, finalize" if final else "upload",
                    "X-Goog-Upload-Offset": str(sent_from),
                    "Content-Type": "application/octet-stream",
                },
                content=data[sent_from - offset :],
            )
            return _json(response) if final else {}
        except IntegrationError as exc:
            if (
                exc.failure_disposition is not IntegrationFailureDisposition.AMBIGUOUS
                or resumes >= _MAX_RESUMES
            ):
                raise
            resumes += 1
        status, received, reply = await _query(client, url)
        if status == "final":
            if final:
                return reply
            raise invalid_upload_reply("Google Ads finished the upload before the last chunk.")
        if not offset <= received <= offset + len(data):
            raise invalid_upload_reply("Google Ads returned an unexpected upload size.")
        if received == offset + len(data) and not final:
            return {}
        sent_from = received


async def _query(client: GoogleAdsClient, url: str) -> tuple[str, int, dict[str, Any]]:
    response = await client.upload_request(
        "POST", url, operation=_OPERATION, headers={"X-Goog-Upload-Command": "query"}
    )
    status = response.headers.get("x-goog-upload-status") or ""
    if status == "final":
        return status, -1, _json(response)
    received = response.headers.get("x-goog-upload-size-received") or ""
    if status != "active" or not received.isdigit():
        raise invalid_upload_reply("Google Ads didn't say how much of the upload it has.")
    return status, int(received), {}


async def _cancel(client: GoogleAdsClient, url: str) -> None:
    """Asks Google to drop an unfinished upload; best effort, since no video was made."""
    try:
        async with asyncio.timeout(_CANCEL_TIMEOUT_SECONDS):
            await client.upload_request(
                "POST", url, operation=_OPERATION, headers={"X-Goog-Upload-Command": "cancel"}
            )
    except (IntegrationError, TimeoutError):
        pass


def _json(response: httpx2.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        raise invalid_upload_reply("Google Ads returned an invalid upload reply.")
    return payload


def _upload_id(customer: str, reply: dict[str, Any]) -> str:
    name = reply.get("resourceName") or reply.get("resource_name")
    match = re.fullmatch(
        rf"customers/{customer}/youTubeVideoUploads/(\d+)", name if isinstance(name, str) else ""
    )
    if match is None:
        raise invalid_upload_reply("Google Ads didn't return the uploaded video.")
    return match.group(1)


async def read_upload_states(
    client: GoogleAdsClient,
    *,
    customer: str,
    login_customer_id: str,
    upload_ids: Sequence[str],
) -> dict[str, UploadState]:
    """Reads each upload's processing state; an ID Google doesn't return is left out."""
    if not upload_ids:
        return {}
    payload = await client.post(
        f"customers/{customer}/googleAds:searchStream",
        operation="read_video_uploads",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={
            "query": "SELECT you_tube_video_upload.video_upload_id, "  # noqa: S608 -- digit-only ids
            "you_tube_video_upload.video_id, you_tube_video_upload.state "
            "FROM you_tube_video_upload "
            f"WHERE you_tube_video_upload.video_upload_id IN ({', '.join(sorted(upload_ids))})"
        },
    )
    states: dict[str, UploadState] = {}
    for row in stream_rows(payload, max_rows=len(upload_ids) + 1):
        upload = row.get("youTubeVideoUpload") or {}
        upload_id = str(upload.get("videoUploadId") or "")
        state = upload.get("state")
        video_id = upload.get("videoId")
        if upload_id in upload_ids and isinstance(state, str):
            states[upload_id] = UploadState(
                state,
                video_id if isinstance(video_id, str) and _VIDEO_ID.fullmatch(video_id) else None,
            )
    return states
