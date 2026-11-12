# apps/api/integrations/meta_ads/operations/preview_media.py

"""Read one library image, video thumbnail, or Page or post picture from Meta's CDN as a JPEG."""

import json
from typing import Literal

import httpx2

from core.exceptions.integration import IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy
from services.integrations.previews.images import (
    PreviewTooLargeError,
    download_preview_image,
    image_preview,
)
from services.integrations.report_results import ReportResultBudget

from ..client import MetaAdsClient, ad_account_path
from ..references import MetaAdsPostReference
from ..throttle import ensure_account_available
from .list_assets import (
    POST_SCAN_LIMIT,
    VIDEO_SCAN_LIMIT,
    find_post_references,
    find_video_references,
    media_url,
    preferred_thumbnail,
    read_page_references,
)

type MetaAdsPreviewType = Literal["image", "video", "page", "post", "igpost"]

_OPERATION = "preview_media"


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
        case "post" | "igpost":
            urls = await _post_urls(client, account_id=account_id, ref=media_id, kind=media_type)
    for url in urls:
        if media_url(url) is None:
            raise _invalid("Meta returned a media address off its own hosts.")
        try:
            data = await download_preview_image(
                url, provider_key="meta_ads", operation=_OPERATION, client=download_client
            )
        except PreviewTooLargeError:
            continue
        return await image_preview(data, provider_key="meta_ads", operation=_OPERATION)
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


async def _post_urls(
    client: MetaAdsClient, *, account_id: str, ref: str, kind: Literal["post", "igpost"]
) -> list[str]:
    # Only a post of a Page or Instagram account the ad account can use.
    owner, post_id = ref.split("_", 1)
    facebook = kind == "post"
    reference = MetaAdsPostReference(
        account_id=account_id,
        label="Post",
        source="facebook" if facebook else "instagram",
        post_id=ref if facebook else post_id,
        page_id=owner if facebook else None,
        instagram_user_id=None if facebook else owner,
    )
    found = await find_post_references(
        client,
        account_id=account_id,
        scope_label="",
        budget=ReportResultBudget("meta_ads", _OPERATION),
        references=[reference],
    )
    if not found:
        raise _invalid(
            f"This post isn't among the {POST_SCAN_LIMIT} most recent posts of a Page or "
            "Instagram account this ad account can use."
        )
    if found[0].thumbnail_url is None:
        raise _invalid("Meta has no picture for this post.")
    return [found[0].thumbnail_url]


def _invalid(message: str) -> IntegrationValidationError:
    return IntegrationValidationError(message, provider_key="meta_ads", operation=_OPERATION)
