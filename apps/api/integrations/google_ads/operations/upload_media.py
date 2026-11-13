# apps/api/integrations/google_ads/operations/upload_media.py

"""Uploads workspace images and videos, and links YouTube videos, as Google Ads assets, once each."""

import asyncio
import base64
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from core.exceptions.integration import IntegrationError, IntegrationFailureDisposition
from services.audit_events import IntegrationOperationCheckpoint
from services.integrations.files import read_pinned_file_source
from services.integrations.http import IntegrationRequestPolicy
from services.integrations.operations import checkpoint_integration_operation

from ..client import GoogleAdsClient, normalize_customer_id
from .media import ImageSource, VideoSource, image_fits, image_size
from .mutation_outcomes import (
    GoogleAdsMutationLedger,
    GoogleAdsMutationOutcome,
    GoogleAdsMutationProjection,
    build_mutation_ledger,
)
from .utils import escape_gaql_string_literal, nonnegative_int, stream_rows
from .video_upload import (
    FAILED_STATES,
    PROCESSED,
    UploadProgress,
    read_upload_states,
    upload_video,
)

_OPERATION = "upload_media"
_UNCONFIRMED = (
    "Google Ads didn't confirm this upload. Check the asset library before uploading again."
)
_INTERRUPTED = "This wasn't sent, because the upload was interrupted."
_VIDEO_STOPPED = "The upload stopped before it finished, so Google didn't make a video."
_VIDEO_UNCONFIRMED = (
    "Google Ads didn't confirm the end of this upload. Check the account's videos before "
    "uploading again."
)
# How long a run waits for Google to process uploaded videos, and how often it looks.
PROCESSING_WAIT_SECONDS = 120
POLL_INTERVAL_SECONDS = 5
VIDEO_UPLOAD_GROUP = "video:upload"
_READ_FIELDS = (
    "asset.id, asset.type, asset.image_asset.full_size.width_pixels, "
    "asset.image_asset.full_size.height_pixels, asset.youtube_video_asset.youtube_video_title"
)

# A video is a video File uploaded to YouTube here, or an earlier upload being finished.
type MediaKind = Literal["image", "youtube_video", "video"]
type MediaOutcome = Literal["uploaded", "linked", "processing", "failed", "unverified"]


@dataclass
class MediaItem:
    """One image File, YouTube link, or video upload, and what its upload proved."""

    kind: MediaKind
    image: ImageSource | None = None
    video: VideoSource | None = None
    video_id: str | None = None
    width: int | None = None
    height: int | None = None
    title: str | None = None
    description: str | None = None
    # The asset's outcome; for a video, set once the video processed or failed to.
    outcome: GoogleAdsMutationOutcome | None = None
    # The asset's ID, once Google returned it or it was found after an unclear reply.
    asset_id: str | None = None
    recovered: bool = False
    # Set once the request that creates the asset has been sent.
    sent: bool = False
    fits: list[str] = field(default_factory=list)
    # A video's upload: its progress, the outcome of sending the File, and Google's state.
    upload: UploadProgress | None = None
    upload_outcome: GoogleAdsMutationOutcome | None = None
    upload_state: str | None = None
    # Why an earlier upload wasn't finished in this run.
    skip_reason: str | None = None
    # The video's place in the audit record's upload group.
    intent_index: int = 0

    @property
    def key(self) -> str:
        """Names the item in the audit record."""
        if self.image is not None:
            return f"file:{self.image.file.id}"
        if self.video is not None:
            return f"file:{self.video.file.id}"
        if self.kind == "video" and self.upload is not None:
            return f"upload:{self.upload.upload_id}"
        return f"youtube:{self.video_id}"

    @property
    def result(self) -> MediaOutcome:
        if self.kind != "video":
            state = self.outcome[0] if self.outcome else "unverified"
            if state == "applied":
                return "uploaded" if self.kind == "image" else "linked"
            return state
        if self.asset_id is not None:
            return "uploaded"
        for outcome in (self.upload_outcome, self.outcome):
            if outcome is not None and outcome[0] in ("failed", "unverified"):
                return outcome[0]
        return "processing"

    @property
    def waiting(self) -> bool:
        """True for a video whose upload went through and hasn't processed or failed yet."""
        return (
            self.kind == "video"
            and self.upload is not None
            and self.upload.upload_id is not None
            and self.outcome is None
            and (self.upload_outcome is None or self.upload_outcome[0] == "applied")
        )


async def upload_media(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    items: Sequence[MediaItem],
) -> GoogleAdsMutationLedger:
    """Creates each asset or uploads each video in order, then finishes processed videos.

    A video becomes a YouTube video asset once Google has processed it; one still processing
    when the wait ends keeps its upload ID, so a later run can finish it. A cancellation or
    unexpected error raises with a `ledger` attribute holding what was proved so far; an
    item whose request was sent stays unverified, never failed.
    """
    customer = normalize_customer_id(customer_id)
    for index, item in enumerate(items):
        try:
            if item.video is not None:
                await _upload(client, customer, login_customer_id, item)
            elif item.kind != "video":
                await _create(client, customer, login_customer_id, item)
        except (asyncio.CancelledError, Exception) as exc:
            _interrupted(item, exc)
            for later in items[index + 1 :]:
                _not_sent(later, "CANCELLED")
            exc.ledger = media_ledger(items)
            raise
    try:
        await _await_processing(client, customer, login_customer_id, items)
        for item in items:
            if item.kind == "video" and item.video_id and item.waiting:
                await _create(client, customer, login_customer_id, item)
        await _read_back(client, customer, login_customer_id, items)
    except (asyncio.CancelledError, Exception) as exc:
        for item in items:
            if item.kind == "video" and item.sent and item.outcome is None:
                item.outcome = _unverified()
        exc.ledger = media_ledger(items)
        raise
    return media_ledger(items)


def media_ledger(items: Sequence[MediaItem]) -> GoogleAdsMutationLedger:
    """One parent per item; a video's upload and its asset are separate effects."""
    parents = [{"object": item.key} for item in items]
    submitted: list[tuple[int, dict[str, str]]] = []
    outcomes: list[GoogleAdsMutationOutcome] = []
    skipped: dict[int, str] = {}
    for index, item in enumerate(items):
        if item.kind != "video":
            submitted.append((index, parents[index]))
            outcomes.append(item.outcome or _unverified())
            continue
        if item.video is not None:
            submitted.append((index, {**parents[index], "effect": "upload"}))
            outcomes.append(item.upload_outcome or _unverified())
        if item.outcome is not None:
            submitted.append((index, {**parents[index], "effect": "asset"}))
            outcomes.append(item.outcome)
        elif item.video is None:
            skipped[index] = item.skip_reason or "still_processing"
    return build_mutation_ledger(
        family="assets",
        action="create",
        parent_fields=parents,
        skipped_indices=skipped,
        submitted=submitted,
        outcomes=outcomes,
        projection=GoogleAdsMutationProjection(
            applied_key="created", skipped_key="skipped", errors_key="errors"
        ),
    )


def _interrupted(item: MediaItem, exc: BaseException) -> None:
    """Keeps an item whose effect may have happened unverified, never failed or retried."""
    code = "CANCELLED" if isinstance(exc, asyncio.CancelledError) else "UPLOAD_FAILED"
    if item.video is not None and item.upload_outcome is None:
        if item.upload is not None and item.upload.finalizing:
            item.upload_outcome = ("unverified", None, "UPLOAD_NOT_CONFIRMED", _VIDEO_UNCONFIRMED)
        else:
            item.upload_outcome = ("failed", None, code, _VIDEO_STOPPED)
    elif item.kind != "video":
        item.outcome = _unverified() if item.sent else ("failed", None, code, _INTERRUPTED)


def _not_sent(item: MediaItem, code: str) -> None:
    if item.video is not None:
        item.upload_outcome = ("failed", None, code, _INTERRUPTED)
    else:
        item.outcome = ("failed", None, code, _INTERRUPTED)


async def _upload(
    client: GoogleAdsClient, customer: str, login_customer_id: str, item: MediaItem
) -> None:
    """Sends a video File to YouTube through Google Ads, checkpointing the upload as it goes."""
    if item.video is None or item.upload is None or item.title is None:
        raise RuntimeError("A video upload needs its File, progress, and title")
    progress = item.upload

    async def checkpoint(**references: str) -> None:
        await checkpoint_integration_operation(
            IntegrationOperationCheckpoint(
                group_key=VIDEO_UPLOAD_GROUP, intent_index=item.intent_index, references=references
            )
        )

    try:
        upload_id = await upload_video(
            client,
            customer=customer,
            login_customer_id=login_customer_id,
            source=item.video,
            title=item.title,
            description=item.description,
            progress=progress,
            on_session=lambda session: checkpoint(upload_session=session),
        )
    except IntegrationError as exc:
        if progress.finalizing and not _rejected(exc):
            item.upload_outcome = ("unverified", None, "UPLOAD_NOT_CONFIRMED", _VIDEO_UNCONFIRMED)
        else:
            item.upload_outcome = _failed(exc)
        return
    await checkpoint(upload_session=progress.session or upload_id, video_upload_id=upload_id)
    item.upload_outcome = (
        "applied",
        f"customers/{customer}/youTubeVideoUploads/{upload_id}",
        None,
        None,
    )


async def _await_processing(
    client: GoogleAdsClient, customer: str, login_customer_id: str, items: Sequence[MediaItem]
) -> None:
    """Reads uploads until each has processed or failed, or the wait ends.

    A failed read keeps the last known state. An earlier upload Google doesn't return isn't
    in this account.
    """
    waiting = {item.upload.upload_id: item for item in items if item.waiting and item.upload}
    if not waiting:
        return
    deadline = time.monotonic() + PROCESSING_WAIT_SECONDS
    read = False
    while waiting:
        try:
            states = await read_upload_states(
                client,
                customer=customer,
                login_customer_id=login_customer_id,
                upload_ids=sorted(waiting),
            )
            read = True
        except IntegrationError:
            states = {}
        for upload_id, state in states.items():
            item = waiting[upload_id]
            item.upload_state = state.state
            if state.state in FAILED_STATES:
                message = (
                    "Google couldn't process this video. Upload it again or choose another File."
                )
                item.outcome = ("failed", None, f"VIDEO_{state.state}", message)
            elif state.state == PROCESSED and state.video_id:
                item.video_id = state.video_id
        waiting = {key: item for key, item in waiting.items() if item.waiting and not item.video_id}
        if not waiting or time.monotonic() + POLL_INTERVAL_SECONDS > deadline:
            break
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
    for item in waiting.values():
        if item.video is None and read and item.upload_state is None:
            message = "This upload isn't in the selected account."
            item.outcome = ("failed", None, "VIDEO_UPLOAD_NOT_FOUND", message)
        elif item.video is None:
            item.skip_reason = "still_processing" if read else "state_unknown"


async def _create(
    client: GoogleAdsClient, customer: str, login_customer_id: str, item: MediaItem
) -> None:
    if item.image is not None:
        try:
            data = await read_pinned_file_source(
                item.image.revision, provider_key="google_ads", operation=_OPERATION
            )
        except IntegrationError as exc:
            item.outcome = _failed(exc)
            return
        size = image_size(data, item.image.revision.content_type)
        if size is None:
            # The stored type is only declared, so bytes that aren't that image stay here.
            message = f"{item.image.file.name[:500]} isn't a readable image."
            item.outcome = ("failed", None, "unsupported_image", message)
            return
        item.width, item.height = size
        item.fits = image_fits(*size)[0]
        body: dict[str, Any] = {
            "name": item.image.asset_name,
            "type": "IMAGE",
            "imageAsset": {"data": base64.b64encode(data).decode("ascii")},
        }
    else:
        if item.kind == "video" and (
            existing := await _find(client, customer, login_customer_id, item)
        ):
            # Another run already made this video's asset; reuse it rather than make a second.
            item.asset_id = existing
            item.outcome = ("applied", f"customers/{customer}/assets/{existing}", None, None)
            return
        body = {"type": "YOUTUBE_VIDEO", "youtubeVideoAsset": {"youtubeVideoId": item.video_id}}
    item.sent = True
    try:
        payload = await client.post(
            f"customers/{customer}/assets:mutate",
            operation=_OPERATION,
            policy=IntegrationRequestPolicy.MUTATION,
            login_customer_id=login_customer_id,
            json={"operations": [{"create": body}]},
        )
        asset_id = _created_id(customer, payload)
    except IntegrationError as exc:
        if _rejected(exc):
            item.outcome = _failed(exc)
            return
        asset_id = None
    if asset_id is None:
        asset_id = await _find(client, customer, login_customer_id, item)
        item.recovered = asset_id is not None
    if asset_id is None:
        item.outcome = _unverified()
        return
    item.asset_id = asset_id
    item.outcome = ("applied", f"customers/{customer}/assets/{asset_id}", None, None)


def _created_id(customer: str, payload: Any) -> str | None:
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict):
        return None
    name = results[0].get("resourceName")
    match = re.fullmatch(
        rf"customers/{customer}/assets/(\d+)", name if isinstance(name, str) else ""
    )
    return match.group(1) if match else None


async def _find(
    client: GoogleAdsClient, customer: str, login_customer_id: str, item: MediaItem
) -> str | None:
    """Looks for the asset after an unclear reply; None when it isn't proved to exist."""
    if item.image is not None:
        name = escape_gaql_string_literal(item.image.asset_name)
        condition = f"asset.type = 'IMAGE' AND asset.name = '{name}'"
    else:
        # The ID matched `[A-Za-z0-9_-]{11}`, so it needs no escaping.
        condition = (
            "asset.type = 'YOUTUBE_VIDEO' "
            f"AND asset.youtube_video_asset.youtube_video_id = '{item.video_id}'"
        )
    try:
        payload = await client.post(
            f"customers/{customer}/googleAds:searchStream",
            operation="find_uploaded_asset",
            policy=IntegrationRequestPolicy.READ,
            login_customer_id=login_customer_id,
            json={"query": f"SELECT asset.id FROM asset WHERE {condition} LIMIT 1"},  # noqa: S608 -- escaped name, checked video ID
        )
    except IntegrationError:
        return None
    ids = [
        str((row.get("asset") or {}).get("id") or "") for row in stream_rows(payload, max_rows=1)
    ]
    return ids[0] if ids and ids[0].isdigit() else None


async def _read_back(
    client: GoogleAdsClient, customer: str, login_customer_id: str, items: Sequence[MediaItem]
) -> None:
    """Fills in Google's dimensions and video titles; a failed read keeps what was sent."""
    # Google returns one asset for Files with the same content.
    created: dict[str, list[MediaItem]] = {}
    for item in items:
        if item.asset_id:
            created.setdefault(item.asset_id, []).append(item)
    if not created:
        return
    try:
        payload = await client.post(
            f"customers/{customer}/googleAds:searchStream",
            operation="read_uploaded_assets",
            policy=IntegrationRequestPolicy.READ,
            login_customer_id=login_customer_id,
            json={
                "query": f"SELECT {_READ_FIELDS} FROM asset "  # noqa: S608 -- digit-only ids
                f"WHERE asset.id IN ({', '.join(sorted(created))})"
            },
        )
    except IntegrationError:
        return
    for row in stream_rows(payload, max_rows=len(created) + 1):
        asset = row.get("asset") or {}
        size = (asset.get("imageAsset") or {}).get("fullSize") or {}
        width = nonnegative_int(size.get("widthPixels"))
        height = nonnegative_int(size.get("heightPixels"))
        title = (asset.get("youtubeVideoAsset") or {}).get("youtubeVideoTitle")
        for item in created.get(str(asset.get("id") or ""), ()):
            if width and height:
                item.width, item.height = width, height
                item.fits = image_fits(width, height)[0]
            if isinstance(title, str) and title.strip():
                item.title = title.strip()[:500]


def _rejected(exc: IntegrationError) -> bool:
    return exc.failure_disposition in (
        IntegrationFailureDisposition.REJECTED,
        IntegrationFailureDisposition.NOT_DISPATCHED,
    )


def _failed(exc: IntegrationError) -> GoogleAdsMutationOutcome:
    message = " ".join(exc.user_message.split())[:1000] or "Google Ads didn't take this upload."
    return ("failed", None, (exc.error_code or exc.__class__.__name__)[:100], message)


def _unverified() -> GoogleAdsMutationOutcome:
    return ("unverified", None, "UPLOAD_NOT_CONFIRMED", _UNCONFIRMED)
