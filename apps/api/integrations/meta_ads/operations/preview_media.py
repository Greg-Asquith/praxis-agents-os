# apps/api/integrations/meta_ads/operations/preview_media.py

"""Read one library image, video thumbnail, or Page picture from Meta's CDN as a small JPEG."""

import asyncio
import base64
import json
from io import BytesIO
from typing import Any, Literal

import httpx2
from PIL import Image, ImageOps, UnidentifiedImageError

from core.exceptions.integration import IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy, consume_stream_with_retries
from services.integrations.report_results import ReportResultBudget

from ..client import MetaAdsClient, ad_account_path
from ..throttle import ensure_account_available
from .list_assets import (
    VIDEO_SCAN_LIMIT,
    find_video_references,
    media_url,
    preferred_thumbnail,
    read_page_references,
)

type MetaAdsPreviewType = Literal["image", "video", "page"]

_OPERATION = "preview_media"
_MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024
# Well above any ad image Meta accepts, so only a decompression bomb is refused.
_MAX_PIXELS = 50_000_000
_MAX_SIDE = 720
_JPEG_QUALITY = 82
_FORMATS = ("JPEG", "PNG", "WEBP", "GIF")


class _TooLargeError(Exception):
    pass


async def preview_media(
    client: MetaAdsClient,
    *,
    account_id: str,
    media_type: MetaAdsPreviewType,
    media_id: str,
    download_client: httpx2.AsyncClient | None = None,
) -> tuple[str, int, int]:
    """Returns a JPEG data URL and its size for media or a Page this ad account can use."""
    ensure_account_available(account_id, operation=_OPERATION)
    match media_type:
        case "image":
            urls = await _image_urls(client, account_id=account_id, image_hash=media_id)
        case "page":
            urls = await _page_urls(client, account_id=account_id, page_id=media_id)
        case "video":
            urls = await _video_urls(client, account_id=account_id, video_id=media_id)
    for url in urls:
        try:
            data = await _download(url, download_client)
        except _TooLargeError:
            continue
        return await asyncio.to_thread(_jpeg_data_url, data)
    raise _invalid("The image is too large to preview.")


async def _image_urls(client: MetaAdsClient, *, account_id: str, image_hash: str) -> list[str]:
    payload = await client.graph_get(
        f"{ad_account_path(account_id)}/adimages",
        params={
            "hashes": json.dumps([image_hash]),
            "fields": "hash,url,url_128,width,height,status",
        },
        operation=_OPERATION,
        policy=IntegrationRequestPolicy.READ,
        usage_account_id=account_id,
    )
    rows = payload.get("data")
    rows = rows if isinstance(rows, list) else []
    row = next(
        (item for item in rows if isinstance(item, dict) and item.get("hash") == image_hash), None
    )
    if row is None:
        raise _invalid("This image isn't in the ad account's media library.")
    # The full image first; its small copy when the full one is over the download cap.
    urls = [url for url in (media_url(row.get("url")), media_url(row.get("url_128"))) if url]
    if not urls:
        raise _invalid("Meta didn't return an address for this image.")
    return urls


async def _video_urls(client: MetaAdsClient, *, account_id: str, video_id: str) -> list[str]:
    # Reading the video directly doesn't prove which account owns it, so it must be in the library.
    found = await find_video_references(
        client,
        account_id=account_id,
        scope_label="",
        budget=ReportResultBudget("meta_ads", _OPERATION),
        video_ids=[video_id],
    )
    if not found:
        raise _invalid(
            f"This video isn't among the ad account's {VIDEO_SCAN_LIMIT} most recent videos."
        )
    url = await preferred_thumbnail(client, account_id=account_id, video_id=video_id)
    if url is None:
        raise _invalid("Meta has no thumbnail for this video yet.")
    return [url]


async def _page_urls(client: MetaAdsClient, *, account_id: str, page_id: str) -> list[str]:
    # Only a Page the account can promote, so another Page's picture can't be read through it.
    pages, _more = await read_page_references(
        client,
        account_id=account_id,
        scope_label="",
        budget=ReportResultBudget("meta_ads", _OPERATION),
    )
    page = next((item for item in pages if item.page_id == page_id), None)
    if page is None:
        raise _invalid("This ad account can't advertise as this Page.")
    if page.picture_url is None:
        raise _invalid("Meta has no picture for this Page.")
    return [page.picture_url]


async def _download(url: str, client: httpx2.AsyncClient | None) -> bytes:
    async def consume(response: httpx2.Response) -> bytes:
        # A redirect could lead off Meta's hosts, so only a direct answer is used.
        if response.status_code != 200:
            raise _invalid("Meta's media host didn't return the image.")
        body = bytearray()
        async for chunk in response.aiter_bytes():
            if len(body) + len(chunk) > _MAX_DOWNLOAD_BYTES:
                raise _TooLargeError
            body.extend(chunk)
        return bytes(body)

    if media_url(url) is None:
        raise _invalid("Meta returned a media address off its own hosts.")
    return await consume_stream_with_retries(
        "GET",
        url,
        operation=_OPERATION,
        provider_key="meta_ads",
        policy=IntegrationRequestPolicy.READ,
        consume=consume,
        client=client,
        follow_redirects=False,
    )


def _jpeg_data_url(data: bytes) -> tuple[str, int, int]:
    try:
        with Image.open(BytesIO(data), formats=_FORMATS) as source:
            width, height = source.size
            if width * height > _MAX_PIXELS:
                raise _invalid("The image is too large to preview.")
            source.draft("RGB", (_MAX_SIDE, _MAX_SIDE))
            image = _flatten(ImageOps.exif_transpose(source))
            image.thumbnail((_MAX_SIDE, _MAX_SIDE))
            output = BytesIO()
            image.save(output, format="JPEG", quality=_JPEG_QUALITY)
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError):
        raise _invalid("Meta returned media that isn't an image.") from None
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}", image.width, image.height


def _flatten(image: Any) -> Image.Image:
    # Transparent areas show white, as they do in Meta's own previews.
    if image.mode in {"RGBA", "LA", "P"}:
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")


def _invalid(message: str) -> IntegrationValidationError:
    return IntegrationValidationError(message, provider_key="meta_ads", operation=_OPERATION)
