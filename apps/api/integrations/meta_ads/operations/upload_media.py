# apps/api/integrations/meta_ads/operations/upload_media.py

"""Uploads workspace images and videos to an ad account's media library, once each."""

import asyncio
import hashlib
import time
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from core.exceptions.integration import IntegrationError, IntegrationFailureDisposition
from services.integrations.http import IntegrationRequestPolicy
from services.integrations.report_results import ReportResultBudget

from ..client import MetaAdsClient, ad_account_path
from ..references import MetaAdsMediaReference
from ..throttle import ensure_account_available
from .list_assets import read_image_references, video_reference, video_status
from .media_source import MediaSource, RevisionStream, read_image
from .mutations import (
    NOT_DISPATCHED_CODE,
    NOT_DISPATCHED_MESSAGE,
    MetaAdsMutationEffect,
    MetaAdsMutationLedger,
    MetaAdsMutationParent,
    freeze_fields,
)
from .values import invalid_response

_OPERATION = "upload_media"
# Meta chooses each chunk's size; refuse one too large to hold in memory.
_MAX_VIDEO_CHUNK_BYTES = 64 * 1024 * 1024
_POLL_INTERVAL_SECONDS = 5
# Bounds the first status reads even when no processing wait is configured.
_MIN_READ_SECONDS = 10
_CANCEL_TIMEOUT_SECONDS = 5
_READINESS_MESSAGES = {
    "processing": (
        "Meta is still processing this video. List the account's videos to check it's ready "
        "before using it in an ad."
    ),
    "unknown": (
        "Meta didn't say whether this video is ready. List the account's videos to check it's "
        "ready before using it in an ad."
    ),
    "failed": "Meta couldn't process this video. Upload it again or choose another File.",
}
_UNCONFIRMED = (
    "Meta Ads didn't confirm this upload. Check the media library before uploading again."
)
_NOT_PUBLISHED = "Meta Ads didn't finish this upload, so the video isn't in the media library."

type MediaUploadOutcome = Literal["uploaded", "processing", "failed", "unverified"]
type MediaReadiness = Literal["ready", "processing", "failed", "unknown"]


@dataclass
class MediaUpload:
    """What one File's upload proved; `media_id` is the image hash or video ID."""

    source: MediaSource
    media_id: str | None = None
    effect: MetaAdsMutationEffect | None = None
    recovered: bool = False
    media: MetaAdsMediaReference | None = None
    # Set once the request that publishes the File has been sent.
    publishing: bool = False
    fields: dict[str, str] = field(default_factory=dict)

    @property
    def file_id(self) -> str:
        return str(self.source.file.id)

    @property
    def readiness(self) -> MediaReadiness:
        """What Meta last reported about using the media; a video never read is unknown."""
        if self.source.media_type == "image":
            return "ready"
        status = self.media.media_status if self.media else None
        return status or "unknown"

    @property
    def outcome(self) -> MediaUploadOutcome:
        if self.effect is None or self.effect.outcome == "unverified":
            return "unverified"
        if self.effect.outcome == "failed" or self.readiness == "failed":
            return "failed"
        return "processing" if self.readiness == "processing" else "uploaded"


async def upload_media(
    client: MetaAdsClient,
    *,
    account_id: str,
    scope_label: str,
    sources: Sequence[MediaSource],
    poll_seconds: int,
) -> tuple[list[MediaUpload], MetaAdsMutationLedger]:
    """Uploads in order, then reads every upload back and waits for videos to process.

    A cancellation or unexpected error raises with a `ledger` attribute holding what was
    proved so far.
    """
    uploads = [MediaUpload(source, fields={"media_type": source.media_type}) for source in sources]
    for index, upload in enumerate(uploads):
        try:
            if upload.source.media_type == "image":
                await _upload_image(client, account_id, scope_label, upload)
            else:
                await _upload_video(client, account_id, upload)
        except (asyncio.CancelledError, Exception) as exc:
            upload.effect = _interrupted_effect(upload, exc)
            for pending in uploads[index + 1 :]:
                pending.effect = _not_dispatched(pending)
            exc.ledger = _upload_ledger(uploads)
            raise
    try:
        await _read_back(client, account_id, scope_label, uploads, poll_seconds)
    except (asyncio.CancelledError, Exception) as exc:
        exc.ledger = _upload_ledger(uploads)
        raise
    return uploads, _upload_ledger(uploads)


def _upload_ledger(uploads: Sequence[MediaUpload]) -> MetaAdsMutationLedger:
    return MetaAdsMutationLedger(
        action="upload_media",
        parents=tuple(
            MetaAdsMutationParent(
                identity=(("file_id", upload.file_id),),
                decision="submit",
                effects=(_terminal_effect(upload),),
            )
            for upload in uploads
        ),
    )


def _terminal_effect(upload: MediaUpload) -> MetaAdsMutationEffect:
    """Adds readiness and recovery to a published upload, since processing can still fail."""
    effect = upload.effect or _missing_effect(upload)
    if effect.outcome != "applied":
        return effect
    fields = {**dict(effect.fields), "media_status": upload.readiness}
    if upload.recovered:
        fields["recovered"] = "true"
    return replace(effect, fields=freeze_fields(fields))


def media_upload_row(upload: MediaUpload) -> dict[str, Any]:
    """Builds one upload's result row, shared with ad creation's own uploads."""
    effect = upload.effect
    failure = effect if effect is not None and effect.outcome != "applied" else None
    return {
        "file_id": upload.file_id,
        "revision_id": str(upload.source.revision.id),
        "name": upload.source.file.name[:500],
        "media_type": upload.source.media_type,
        "outcome": upload.outcome,
        "recovered": upload.recovered,
        "media": upload.media.model_dump(mode="json") if upload.media else None,
        "error_code": failure.error_code if failure else None,
        "message": failure.message if failure else _READINESS_MESSAGES.get(upload.readiness),
    }


async def _upload_image(
    client: MetaAdsClient, account_id: str, scope_label: str, upload: MediaUpload
) -> None:
    try:
        data = await read_image(upload.source)
    except IntegrationError as exc:
        upload.effect = _failed(upload, exc)
        return
    # Meta's image hash is expected to be the MD5 of the bytes; reconciliation relies on it.
    expected_hash = hashlib.md5(data, usedforsecurity=False).hexdigest()
    revision = upload.source.revision
    name = _upload_name(upload.source)
    upload.publishing = True
    try:
        ensure_account_available(account_id, operation=_OPERATION)
        payload = await client.graph_post_form(
            f"{ad_account_path(account_id)}/adimages",
            data={},
            files={"filename": (name, data, revision.content_type)},
            operation=_OPERATION,
            usage_account_id=account_id,
        )
        image_hash = _uploaded_hash(payload)
    except IntegrationError as exc:
        if _rejected(exc):
            upload.effect = MetaAdsMutationEffect.from_error(upload.fields, exc)
            return
        image_hash = None
    if image_hash is None:
        image_hash = await _find_image(client, account_id, scope_label, expected_hash)
        upload.recovered = image_hash is not None
    if image_hash is None:
        upload.effect = _unverified(upload)
        return
    upload.media_id = image_hash
    upload.fields["image_hash"] = image_hash
    upload.effect = _applied(upload)


async def _find_image(
    client: MetaAdsClient, account_id: str, scope_label: str, image_hash: str
) -> str | None:
    """Looks for an image with this content after an unclear reply; None when unproven."""
    try:
        found, _more = await read_image_references(
            client,
            account_id=account_id,
            scope_label=scope_label,
            budget=ReportResultBudget("meta_ads", _OPERATION),
            hashes=[image_hash],
        )
    except IntegrationError:
        return None
    return image_hash if any(item.image_hash == image_hash for item in found) else None


async def _upload_video(client: MetaAdsClient, account_id: str, upload: MediaUpload) -> None:
    path = f"{ad_account_path(account_id)}/advideos"
    async with RevisionStream(upload.source.revision) as stream:
        session_id = await _transfer_video(client, account_id, path, stream, upload)
    if session_id is None:
        return
    upload.publishing = True
    try:
        reply = await _post(
            client,
            account_id,
            path,
            {
                "upload_phase": "finish",
                "upload_session_id": session_id,
                "title": upload.source.file.name[:255],
            },
        )
        if reply == {"success": True}:
            upload.effect = _applied(upload)
            return
    except IntegrationError as exc:
        if _rejected(exc):
            upload.effect = MetaAdsMutationEffect.from_error(upload.fields, exc)
            await _cancel(client, account_id, path, session_id)
            return
    await _reconcile_video(client, account_id, path, session_id, upload)


async def _transfer_video(
    client: MetaAdsClient,
    account_id: str,
    path: str,
    stream: RevisionStream,
    upload: MediaUpload,
) -> str | None:
    """Sends and verifies every byte; returns the session to finish, or None after a failure."""
    session_id: str | None = None
    try:
        start = await _post(
            client, account_id, path, {"upload_phase": "start", "file_size": str(stream.size)}
        )
        # Kept before the video ID is checked, so a bad ID still lets the session be cancelled.
        session_id = _digits(start, "upload_session_id")
        video_id = _digits(start, "video_id")
        upload.media_id = video_id
        upload.fields["video_id"] = video_id
        await _send_chunks(client, account_id, path, stream, session_id, start, upload.source)
        await stream.verify()
    except (IntegrationError, asyncio.CancelledError) as exc:
        # Nothing is published before finish, so a failure here leaves no usable video.
        if session_id is not None:
            await _cancel(client, account_id, path, session_id)
        if isinstance(exc, asyncio.CancelledError):
            raise
        upload.effect = _failed(upload, exc)
        return None
    return session_id


async def _send_chunks(
    client: MetaAdsClient,
    account_id: str,
    path: str,
    stream: RevisionStream,
    session_id: str,
    reply: dict[str, Any],
    source: MediaSource,
) -> None:
    start, end = _offsets(reply, stream.size, previous=0)
    while start < stream.size:
        if end - start > _MAX_VIDEO_CHUNK_BYTES:
            raise invalid_response(
                "Meta Ads asked for too large a video chunk.", operation=_OPERATION
            )
        chunk = await stream.read(end - start)
        ensure_account_available(account_id, operation=_OPERATION)
        reply = await client.graph_post_form(
            path,
            data={
                "upload_phase": "transfer",
                "upload_session_id": session_id,
                "start_offset": str(start),
            },
            files={"video_file_chunk": (_upload_name(source), chunk, "application/octet-stream")},
            operation=_OPERATION,
            usage_account_id=account_id,
        )
        start, end = _offsets(reply, stream.size, previous=end)


def _offsets(reply: dict[str, Any], size: int, *, previous: int) -> tuple[int, int]:
    """Accepts only the next contiguous range, since the File is read once in order."""
    start = int(_digits(reply, "start_offset"))
    end = int(_digits(reply, "end_offset"))
    done = start == end == size
    if start != previous or not (done or start < end <= size):
        raise invalid_response(
            "Meta Ads returned an unexpected upload range.", operation=_OPERATION
        )
    return start, end


async def _reconcile_video(
    client: MetaAdsClient, account_id: str, path: str, session_id: str, upload: MediaUpload
) -> None:
    """After an unclear finish, a video Meta is processing or has ready counts as uploaded."""
    try:
        payload = await client.graph_get(
            upload.media_id or "",
            params={"fields": "status"},
            operation=_OPERATION,
            policy=IntegrationRequestPolicy.READ,
            usage_account_id=account_id,
        )
        status = video_status(payload.get("status"))
    except IntegrationError:
        status = None
    if status in ("processing", "ready"):
        upload.recovered = True
        upload.effect = _applied(upload)
        return
    await _cancel(client, account_id, path, session_id)
    upload.effect = _unverified(upload)


async def _read_back(
    client: MetaAdsClient,
    account_id: str,
    scope_label: str,
    uploads: Sequence[MediaUpload],
    poll_seconds: int,
) -> None:
    """Builds references from what Meta shows, polling videos until ready or out of time.

    A failed read keeps the upload applied with a reference built from what was sent.
    """
    applied = [upload for upload in uploads if upload.effect and upload.effect.outcome == "applied"]
    for upload in applied:
        upload.media = _sent_reference(upload, account_id, scope_label)
    await _read_images(client, account_id, scope_label, applied)
    videos = [upload for upload in applied if upload.source.media_type == "video"]
    started = time.monotonic()
    poll_until = started + poll_seconds
    read_until = started + max(poll_seconds, _MIN_READ_SECONDS)
    while videos:
        for upload in videos:
            remaining = read_until - time.monotonic()
            if remaining <= 0:
                return
            await _read_video(client, account_id, scope_label, upload, remaining)
        videos = [upload for upload in videos if upload.readiness in ("unknown", "processing")]
        if not videos or time.monotonic() + _POLL_INTERVAL_SECONDS > poll_until:
            break
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)


async def _read_images(
    client: MetaAdsClient, account_id: str, scope_label: str, applied: Sequence[MediaUpload]
) -> None:
    """Reads each uploaded hash once; Files with identical bytes share it and its details."""
    images: dict[str, list[MediaUpload]] = {}
    for upload in applied:
        if upload.source.media_type == "image" and upload.media_id:
            images.setdefault(upload.media_id, []).append(upload)
    if not images:
        return
    try:
        found, _more = await read_image_references(
            client,
            account_id=account_id,
            scope_label=scope_label,
            budget=ReportResultBudget("meta_ads", _OPERATION),
            hashes=sorted(images),
        )
    except IntegrationError:
        return
    for item in found:
        for upload in images.get(item.image_hash or "", ()):
            upload.media = item.model_copy(update={"label": upload.media.label})


async def _read_video(
    client: MetaAdsClient,
    account_id: str,
    scope_label: str,
    upload: MediaUpload,
    seconds: float,
) -> None:
    """Refreshes the video's state; a failed or slow read leaves the last known state."""
    try:
        async with asyncio.timeout(seconds):
            payload = await client.graph_get(
                upload.media_id or "",
                params={"fields": "id,title,picture,status"},
                operation=_OPERATION,
                policy=IntegrationRequestPolicy.READ,
                usage_account_id=account_id,
            )
        item = video_reference(payload, account_id=account_id, scope_label=scope_label)
    except (IntegrationError, TimeoutError):
        return
    if item.video_id == upload.media_id:
        upload.media = item.model_copy(update={"label": upload.media.label})


def _sent_reference(
    upload: MediaUpload, account_id: str, scope_label: str
) -> MetaAdsMediaReference:
    image = upload.source.media_type == "image"
    return MetaAdsMediaReference(
        account_id=account_id,
        media_type=upload.source.media_type,
        image_hash=upload.media_id if image else None,
        video_id=None if image else upload.media_id,
        label=upload.source.file.name[:500] or ("Image" if image else "Video"),
        description="Image" if image else "Video",
        scope_label=scope_label,
        # A video's state is unknown until it's read; never assume it's ready.
        media_status="ready" if image else None,
    )


async def _post(
    client: MetaAdsClient, account_id: str, path: str, data: dict[str, str]
) -> dict[str, Any]:
    ensure_account_available(account_id, operation=_OPERATION)
    return await client.graph_post(
        path,
        data=data,
        operation=_OPERATION,
        policy=IntegrationRequestPolicy.MUTATION,
        usage_account_id=account_id,
    )


async def _cancel(client: MetaAdsClient, account_id: str, path: str, session_id: str) -> None:
    """Asks Meta to drop an unfinished upload; best effort, since nothing was published.

    A known account throttle skips it rather than sending another request Meta would refuse.
    """
    try:
        async with asyncio.timeout(_CANCEL_TIMEOUT_SECONDS):
            await _post(
                client,
                account_id,
                path,
                {"upload_phase": "cancel", "upload_session_id": session_id},
            )
    except (IntegrationError, TimeoutError):
        pass


def _uploaded_hash(payload: dict[str, Any]) -> str | None:
    images = payload.get("images")
    if not isinstance(images, dict) or len(images) != 1:
        return None
    image = next(iter(images.values()))
    value = image.get("hash") if isinstance(image, dict) else None
    if isinstance(value, str) and value.isascii() and value.isalnum() and len(value) <= 64:
        return value
    return None


def _digits(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    # Matches MetaAdsId, so an ID Meta returns can always become a reference.
    if isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 128:
        return value
    raise invalid_response("Meta Ads returned an invalid upload reply.", operation=_OPERATION)


def _upload_name(source: MediaSource) -> str:
    """Keeps the File's name readable in Meta's library without unsafe header characters."""
    name = "".join(
        char if char.isascii() and (char.isalnum() or char in " ._-") else "_"
        for char in source.file.name
    ).strip(" .")
    return name[:255] or str(source.file.id)


def _rejected(exc: IntegrationError) -> bool:
    return exc.failure_disposition in (
        IntegrationFailureDisposition.REJECTED,
        IntegrationFailureDisposition.NOT_DISPATCHED,
    )


def _applied(upload: MediaUpload) -> MetaAdsMutationEffect:
    return MetaAdsMutationEffect(
        fields=freeze_fields(upload.fields), outcome="applied", external_ref=upload.media_id
    )


def _failed(upload: MediaUpload, exc: IntegrationError) -> MetaAdsMutationEffect:
    message = " ".join(exc.user_message.split())[:1000]
    return MetaAdsMutationEffect(
        fields=freeze_fields(upload.fields),
        outcome="failed",
        error_code=(exc.error_code or exc.__class__.__name__)[:100],
        message=message or _NOT_PUBLISHED,
    )


def _unverified(upload: MediaUpload) -> MetaAdsMutationEffect:
    return MetaAdsMutationEffect(
        fields=freeze_fields(upload.fields),
        outcome="unverified",
        error_code="UPLOAD_NOT_CONFIRMED",
        message=_UNCONFIRMED,
    )


def _missing_effect(upload: MediaUpload) -> MetaAdsMutationEffect:
    """Records an upload that never settled as unverified once sent, otherwise not dispatched."""
    return _unverified(upload) if upload.publishing else _not_dispatched(upload)


def _interrupted_effect(upload: MediaUpload, exc: BaseException) -> MetaAdsMutationEffect:
    """Keeps a File whose publishing request was sent unverified, never failed or retried."""
    if upload.publishing:
        return _unverified(upload)
    if isinstance(exc, IntegrationError):
        return _failed(upload, exc)
    return MetaAdsMutationEffect(
        fields=freeze_fields(upload.fields),
        outcome="failed",
        error_code="UPLOAD_FAILED" if isinstance(exc, Exception) else "CANCELLED",
        message=_NOT_PUBLISHED,
    )


def _not_dispatched(upload: MediaUpload) -> MetaAdsMutationEffect:
    return MetaAdsMutationEffect(
        fields=freeze_fields(upload.fields),
        outcome="failed",
        error_code=NOT_DISPATCHED_CODE,
        message=NOT_DISPATCHED_MESSAGE,
    )
