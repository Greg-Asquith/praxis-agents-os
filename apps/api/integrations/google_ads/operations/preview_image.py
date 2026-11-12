# apps/api/integrations/google_ads/operations/preview_image.py

"""Read one image asset from Google's image host as a small JPEG, or PNG when transparent."""

from urllib.parse import urlsplit

import httpx2

from core.exceptions.integration import IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy
from services.integrations.previews.images import (
    PreviewTooLargeError,
    download_preview_image,
    image_preview,
)

from ..client import GoogleAdsClient, normalize_customer_id
from .utils import stream_rows

_OPERATION = "preview_image"
# Google serves uploaded image assets from these hosts.
_IMAGE_HOSTS = ("googlesyndication.com", "googleusercontent.com")


async def preview_image(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    asset_id: str,
    download_client: httpx2.AsyncClient | None = None,
) -> tuple[str, int, int]:
    """Returns a data URL and its size for an image asset in this account."""
    if not asset_id.isdigit():
        raise _invalid("The image reference is invalid.")
    customer = normalize_customer_id(customer_id)
    payload = await client.post(
        f"customers/{customer}/googleAds:searchStream",
        operation=_OPERATION,
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={
            # The query runs in this customer, so another account's image isn't found.
            "query": "SELECT asset.id, asset.type, asset.image_asset.full_size.url FROM asset "  # noqa: S608 -- digit-only id
            f"WHERE asset.id = {asset_id} AND asset.type = 'IMAGE' LIMIT 1"
        },
    )
    rows = stream_rows(payload, max_rows=1)
    full = ((rows[0].get("asset") or {}).get("imageAsset") or {}).get("fullSize") if rows else None
    url = full.get("url") if isinstance(full, dict) else None
    if not isinstance(url, str) or not _on_google_host(url):
        raise _invalid("Google didn't return an address for this image.")
    try:
        data = await download_preview_image(
            url, provider_key="google_ads", operation=_OPERATION, client=download_client
        )
    except PreviewTooLargeError:
        raise _invalid("The image is too large to preview.") from None
    # Logos are often round on a transparent square, so transparency is kept.
    return await image_preview(
        data, provider_key="google_ads", operation=_OPERATION, keep_transparency=True
    )


def _on_google_host(url: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(
        host == suffix or host.endswith(f".{suffix}") for suffix in _IMAGE_HOSTS
    )


def _invalid(message: str) -> IntegrationValidationError:
    return IntegrationValidationError(message, provider_key="google_ads", operation=_OPERATION)
