# apps/api/integrations/google_ads/operations/upload_media.py

"""Uploads workspace images and links YouTube videos as Google Ads assets, once each."""

import asyncio
import base64
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from core.exceptions.integration import IntegrationError, IntegrationFailureDisposition
from services.integrations.files import read_pinned_file_source
from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .media import ImageSource, image_fits, image_size
from .mutation_outcomes import (
    GoogleAdsMutationLedger,
    GoogleAdsMutationOutcome,
    GoogleAdsMutationProjection,
    build_mutation_ledger,
)
from .utils import escape_gaql_string_literal, nonnegative_int, stream_rows

_OPERATION = "upload_media"
_UNCONFIRMED = (
    "Google Ads didn't confirm this upload. Check the asset library before uploading again."
)
_INTERRUPTED = "This wasn't sent, because the upload was interrupted."
_READ_FIELDS = (
    "asset.id, asset.type, asset.image_asset.full_size.width_pixels, "
    "asset.image_asset.full_size.height_pixels, asset.youtube_video_asset.youtube_video_title"
)

type MediaKind = Literal["image", "youtube_video"]
type MediaOutcome = Literal["uploaded", "linked", "failed", "unverified"]


@dataclass
class MediaItem:
    """One image File or YouTube video, and what its upload proved."""

    kind: MediaKind
    image: ImageSource | None = None
    video_id: str | None = None
    width: int | None = None
    height: int | None = None
    title: str | None = None
    outcome: GoogleAdsMutationOutcome | None = None
    # The asset's ID, once Google returned it or it was found after an unclear reply.
    asset_id: str | None = None
    recovered: bool = False
    # Set once the request that creates the asset has been sent.
    sent: bool = False
    fits: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        """Names the item in the audit record."""
        if self.image is not None:
            return f"file:{self.image.file.id}"
        return f"youtube:{self.video_id}"

    @property
    def result(self) -> MediaOutcome:
        state = self.outcome[0] if self.outcome else "unverified"
        if state == "applied":
            return "uploaded" if self.kind == "image" else "linked"
        return state


async def upload_media(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    items: Sequence[MediaItem],
) -> GoogleAdsMutationLedger:
    """Creates each asset in its own request, in order, then reads the created assets back.

    A cancellation or unexpected error raises with a `ledger` attribute holding what was
    proved so far; an item whose request was sent stays unverified, never failed.
    """
    customer = normalize_customer_id(customer_id)
    for index, item in enumerate(items):
        try:
            await _create(client, customer, login_customer_id, item)
        except (asyncio.CancelledError, Exception) as exc:
            code = "CANCELLED" if isinstance(exc, asyncio.CancelledError) else "UPLOAD_FAILED"
            item.outcome = _unverified() if item.sent else ("failed", None, code, _INTERRUPTED)
            for later in items[index + 1 :]:
                later.outcome = ("failed", None, "CANCELLED", _INTERRUPTED)
            exc.ledger = media_ledger(items)
            raise
    try:
        await _read_back(client, customer, login_customer_id, items)
    except (asyncio.CancelledError, Exception) as exc:
        exc.ledger = media_ledger(items)
        raise
    return media_ledger(items)


def media_ledger(items: Sequence[MediaItem]) -> GoogleAdsMutationLedger:
    fields = [{"object": item.key} for item in items]
    return build_mutation_ledger(
        family="assets",
        action="create",
        parent_fields=fields,
        skipped_indices={},
        submitted=list(enumerate(fields)),
        outcomes=[item.outcome or _unverified() for item in items],
        projection=GoogleAdsMutationProjection(
            applied_key="created", skipped_key="skipped", errors_key="errors"
        ),
    )


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
        if exc.failure_disposition in (
            IntegrationFailureDisposition.REJECTED,
            IntegrationFailureDisposition.NOT_DISPATCHED,
        ):
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


def _failed(exc: IntegrationError) -> GoogleAdsMutationOutcome:
    message = " ".join(exc.user_message.split())[:1000] or "Google Ads didn't take this upload."
    return ("failed", None, (exc.error_code or exc.__class__.__name__)[:100], message)


def _unverified() -> GoogleAdsMutationOutcome:
    return ("unverified", None, "UPLOAD_NOT_CONFIRMED", _UNCONFIRMED)
