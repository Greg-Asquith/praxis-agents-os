# apps/api/integrations/meta_ads/operations/list_assets.py

"""Read the Pages, Instagram accounts, and media an ad account can use in ads."""

import json
from collections.abc import Awaitable, Callable, Sequence
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ValidationError

from core.exceptions.integration import IntegrationPermissionError
from services.integrations.http import IntegrationRequestPolicy
from services.integrations.report_results import ReportResultBudget, report_result_max_bytes

from ..client import MetaAdsClient, ad_account_path
from ..models import MetaAdsMediaStatus
from ..references import (
    MetaAdsInstagramAccountReference,
    MetaAdsMediaReference,
    MetaAdsPageReference,
)
from ..throttle import ensure_account_available
from ..tools.schemas.assets import MetaAdsAssetKind, MetaAdsAssetsData
from .paging import read_pages
from .values import bounded_string, invalid_response

_OPERATION = "list_assets"
_MEDIA_LIMIT = 50
_IDENTITY_LIMIT = 100
# Pages read per kind, so inactive or short pages can't hide assets behind them.
_MAX_PAGES = 5
_VIDEO_SCAN_PAGE_SIZE = 100
# Meta's video edge has no ID filter, so exact lookups scan this many recent videos.
VIDEO_SCAN_LIMIT = _VIDEO_SCAN_PAGE_SIZE * _MAX_PAGES
_MAX_URL_LENGTH = 2048
_MEDIA_HOSTS = ("fbcdn.net", "facebook.com", "cdninstagram.com")
ASSET_KINDS: tuple[MetaAdsAssetKind, ...] = ("pages", "instagram_accounts", "images", "videos")
_PERMISSION_NOTES: dict[MetaAdsAssetKind, str] = {
    "pages": (
        "Meta didn't allow reading this account's Pages. Give the system user Advertise "
        "access to the Page, and check the token has pages_show_list, pages_manage_ads, and "
        "pages_read_engagement."
    ),
    "instagram_accounts": (
        "Meta didn't allow reading this account's Instagram accounts. Connect the Instagram "
        "account to the ad account in Business Settings."
    ),
    "images": "Meta didn't allow reading this account's images.",
    "videos": "Meta didn't allow reading this account's videos.",
}
_VIDEO_STATUSES: dict[str, MetaAdsMediaStatus] = {
    "ready": "ready",
    "processing": "processing",
    "error": "failed",
    "expired": "failed",
}

type _Reader = Callable[..., Awaitable[tuple[Sequence[BaseModel], bool]]]


async def list_assets(
    client: MetaAdsClient,
    *,
    account_id: str,
    scope_label: str,
    kinds: Sequence[MetaAdsAssetKind] = ASSET_KINDS,
    max_response_bytes: int | None = None,
) -> MetaAdsAssetsData:
    """Reads each requested kind, turning a permission refusal into a note on that kind."""
    if max_response_bytes is None:
        max_response_bytes = report_result_max_bytes()
    budget = ReportResultBudget("meta_ads", _OPERATION, maximum=max_response_bytes)
    found: dict[MetaAdsAssetKind, Sequence[BaseModel]] = {kind: [] for kind in ASSET_KINDS}
    truncated: list[MetaAdsAssetKind] = []
    notes: list[str] = []
    for kind in (kind for kind in ASSET_KINDS if kind in kinds):
        try:
            found[kind], more = await _READERS[kind](
                client, account_id=account_id, scope_label=scope_label, budget=budget
            )
        except IntegrationPermissionError:
            notes.append(_PERMISSION_NOTES[kind])
            continue
        if more:
            truncated.append(kind)
    return MetaAdsAssetsData.model_validate({**found, "truncated": truncated, "notes": notes})


async def read_page_references(
    client: MetaAdsClient, *, account_id: str, scope_label: str, budget: ReportResultBudget
) -> tuple[list[MetaAdsPageReference], bool]:
    rows, more = await _read(
        client,
        account_id,
        "promote_pages",
        "id,name,picture.width(128).height(128){url}",
        _IDENTITY_LIMIT,
        budget,
    )
    pages = [
        _reference(
            MetaAdsPageReference,
            "Page",
            account_id=account_id,
            page_id=row.get("id"),
            label=_label(row.get("name"), "Facebook Page"),
            description="Facebook Page",
            scope_label=scope_label,
            picture_url=media_url(_picture_url(row.get("picture"))),
        )
        for row in rows
    ]
    return pages, more


async def read_instagram_references(
    client: MetaAdsClient, *, account_id: str, scope_label: str, budget: ReportResultBudget
) -> tuple[list[MetaAdsInstagramAccountReference], bool]:
    rows, more = await _read(
        client,
        account_id,
        "connected_instagram_accounts",
        "id,username,profile_pic",
        _IDENTITY_LIMIT,
        budget,
    )
    accounts = []
    for row in rows:
        username = _instagram_username(row.get("username"))
        accounts.append(
            _reference(
                MetaAdsInstagramAccountReference,
                "Instagram account",
                account_id=account_id,
                instagram_user_id=row.get("id"),
                username=username,
                label=f"@{username}" if username else f"Instagram account {row.get('id')}",
                description="Instagram account",
                scope_label=scope_label,
                picture_url=media_url(row.get("profile_pic")),
            )
        )
    return accounts, more


async def read_image_references(
    client: MetaAdsClient,
    *,
    account_id: str,
    scope_label: str,
    budget: ReportResultBudget,
    hashes: Sequence[str] = (),
) -> tuple[list[MetaAdsMediaReference], bool]:
    """Reads active images, or exactly the given hashes, from the account's media library."""
    wanted = set(hashes)

    def usable(row: dict[str, Any]) -> bool:
        return row.get("status") == "ACTIVE" and (not wanted or row.get("hash") in wanted)

    rows, more = await _read(
        client,
        account_id,
        "adimages",
        "hash,name,width,height,url_128,status",
        len(hashes) or _MEDIA_LIMIT,
        budget,
        params={"hashes": json.dumps(list(hashes))} if hashes else None,
        include=usable,
    )
    images = [image_reference(row, account_id=account_id, scope_label=scope_label) for row in rows]
    return images, more


async def read_video_references(
    client: MetaAdsClient, *, account_id: str, scope_label: str, budget: ReportResultBudget
) -> tuple[list[MetaAdsMediaReference], bool]:
    rows, more = await _read(
        client, account_id, "advideos", "id,title,picture,status", _MEDIA_LIMIT, budget
    )
    videos = [video_reference(row, account_id=account_id, scope_label=scope_label) for row in rows]
    return videos, more


async def find_video_references(
    client: MetaAdsClient,
    *,
    account_id: str,
    scope_label: str,
    budget: ReportResultBudget,
    video_ids: Sequence[str],
) -> list[MetaAdsMediaReference]:
    """Finds exact videos in the account's library by scanning its most recent videos.

    Meta's video edge has no ID filter, and reading a video directly doesn't prove which
    account owns it, so a video older than the scanned pages isn't found.
    """
    wanted = set(video_ids)
    rows, _more = await read_pages(
        client,
        path=f"{ad_account_path(account_id)}/advideos",
        account_id=account_id,
        params={"fields": "id,title,picture,status"},
        limit=len(wanted),
        budget=budget,
        operation=_OPERATION,
        page_size=_VIDEO_SCAN_PAGE_SIZE,
        max_pages=_MAX_PAGES,
        include=lambda row: row.get("id") in wanted,
    )
    return [video_reference(row, account_id=account_id, scope_label=scope_label) for row in rows]


async def preferred_thumbnail(
    client: MetaAdsClient, *, account_id: str, video_id: str
) -> str | None:
    """Returns the address of the thumbnail Meta prefers for a video, or None."""
    ensure_account_available(account_id, operation=_OPERATION)
    payload = await client.graph_get(
        f"{video_id}/thumbnails",
        params={"fields": "uri,is_preferred"},
        operation=_OPERATION,
        policy=IntegrationRequestPolicy.READ,
        usage_account_id=account_id,
    )
    rows = payload.get("data")
    if not isinstance(rows, list):
        return None
    usable = [row for row in rows if isinstance(row, dict) and media_url(row.get("uri"))]
    preferred = next((row for row in usable if row.get("is_preferred") is True), None)
    chosen = preferred or (usable[0] if usable else None)
    return media_url(chosen.get("uri")) if chosen else None


def image_reference(
    row: dict[str, Any], *, account_id: str, scope_label: str
) -> MetaAdsMediaReference:
    image_hash = row.get("hash")
    return _reference(
        MetaAdsMediaReference,
        "image",
        account_id=account_id,
        media_type="image",
        image_hash=image_hash,
        label=_label(row.get("name"), f"Image {str(image_hash)[:8]}"),
        description="Image",
        scope_label=scope_label,
        width=_dimension(row.get("width")),
        height=_dimension(row.get("height")),
        media_status="ready",
        thumbnail_url=media_url(row.get("url_128")),
    )


def video_reference(
    row: dict[str, Any], *, account_id: str, scope_label: str
) -> MetaAdsMediaReference:
    return _reference(
        MetaAdsMediaReference,
        "video",
        account_id=account_id,
        media_type="video",
        video_id=row.get("id"),
        label=_label(row.get("title"), f"Video {row.get('id')}"),
        description="Video",
        scope_label=scope_label,
        media_status=video_status(row.get("status")),
        thumbnail_url=media_url(row.get("picture")),
    )


def video_status(value: Any) -> MetaAdsMediaStatus | None:
    """Maps Meta's video status object; an unknown state is None, never ready."""
    if not isinstance(value, dict):
        return None
    status = value.get("video_status")
    return _VIDEO_STATUSES.get(status) if isinstance(status, str) else None


_READERS: dict[MetaAdsAssetKind, _Reader] = {
    "pages": read_page_references,
    "instagram_accounts": read_instagram_references,
    "images": read_image_references,
    "videos": read_video_references,
}


async def _read(
    client: MetaAdsClient,
    account_id: str,
    edge: str,
    fields: str,
    limit: int,
    budget: ReportResultBudget,
    *,
    params: dict[str, Any] | None = None,
    include: Callable[[dict[str, Any]], bool] | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    return await read_pages(
        client,
        path=f"{ad_account_path(account_id)}/{edge}",
        account_id=account_id,
        params={"fields": fields, **(params or {})},
        limit=limit,
        budget=budget,
        operation=_OPERATION,
        page_size=limit,
        max_pages=_MAX_PAGES,
        include=include,
    )


def _reference[T: BaseModel](model: type[T], noun: str, **values: Any) -> T:
    """Builds a reference, failing without echoing Meta's value when it doesn't validate."""
    try:
        return model(**values)
    except ValidationError:
        raise invalid_response(
            f"Meta Ads returned an invalid {noun}.", operation=_OPERATION
        ) from None


def _label(value: Any, fallback: str) -> str:
    text = bounded_string(value, operation=_OPERATION, maximum=500) or ""
    return " ".join(text.split()) or fallback


def _picture_url(value: Any) -> Any:
    # Expanded as picture{url}, Meta nests the address under data.
    data = value.get("data") if isinstance(value, dict) else None
    return data.get("url") if isinstance(data, dict) else value


def media_url(value: Any) -> str | None:
    """Keeps only HTTPS addresses on Meta's own hosts; anything else is dropped."""
    if not isinstance(value, str) or len(value) > _MAX_URL_LENGTH:
        return None
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    on_meta_host = any(host == item or host.endswith(f".{item}") for item in _MEDIA_HOSTS)
    has_userinfo = parts.username is not None or parts.password is not None
    return value if parts.scheme == "https" and on_meta_host and not has_userinfo else None


def _dimension(value: Any) -> int | None:
    return value if isinstance(value, int) and 1 <= value <= 100_000 else None


def _instagram_username(value: Any) -> str | None:
    """Returns a handle within Instagram's rules; anything else is shown by ID instead."""
    if not isinstance(value, str) or not 1 <= len(value) <= 30:
        return None
    if not all(char.isascii() and (char.isalnum() or char in "._") for char in value):
        return None
    return value
