# apps/api/services/integrations/previews/images.py

"""Download a provider's image and re-encode it as a small JPEG or PNG data URL for a preview."""

import asyncio
import base64
from io import BytesIO
from typing import Any

import httpx2
from PIL import Image, ImageOps, UnidentifiedImageError

from core.exceptions.integration import IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy, consume_stream_with_retries

_MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024
# Well above any ad image a provider accepts, so only a decompression bomb is refused.
_MAX_PIXELS = 50_000_000
_MAX_SIDE = 720
_JPEG_QUALITY = 82
_FORMATS = ("JPEG", "PNG", "WEBP", "GIF")


class PreviewTooLargeError(Exception):
    """The image is over the download cap, so a smaller copy may be tried instead."""


async def download_preview_image(
    url: str,
    *,
    provider_key: str,
    operation: str,
    client: httpx2.AsyncClient | None = None,
) -> bytes:
    """Downloads an image the caller has already checked is on the provider's own hosts.

    Raises:
        PreviewTooLargeError: When the image is over the download cap.
    """

    async def consume(response: httpx2.Response) -> bytes:
        # A redirect could lead off the provider's hosts, so only a direct answer is used.
        if response.status_code != 200:
            raise IntegrationValidationError(
                "The provider's media host didn't return the image.",
                provider_key=provider_key,
                operation=operation,
            )
        body = bytearray()
        async for chunk in response.aiter_bytes():
            if len(body) + len(chunk) > _MAX_DOWNLOAD_BYTES:
                raise PreviewTooLargeError
            body.extend(chunk)
        return bytes(body)

    return await consume_stream_with_retries(
        "GET",
        url,
        operation=operation,
        provider_key=provider_key,
        policy=IntegrationRequestPolicy.READ,
        consume=consume,
        client=client,
        follow_redirects=False,
    )


async def image_preview(
    data: bytes, *, provider_key: str, operation: str, keep_transparency: bool = False
) -> tuple[str, int, int]:
    """Returns the image as a data URL of at most 720 pixels a side, and its size.

    The URL is a JPEG, or a PNG when transparency is kept and the image has some.
    """
    return await asyncio.to_thread(
        _data_url, data, provider_key, operation, keep_transparency=keep_transparency
    )


def _data_url(
    data: bytes, provider_key: str, operation: str, *, keep_transparency: bool
) -> tuple[str, int, int]:
    def invalid(message: str) -> IntegrationValidationError:
        return IntegrationValidationError(message, provider_key=provider_key, operation=operation)

    try:
        with Image.open(BytesIO(data), formats=_FORMATS) as source:
            width, height = source.size
            if width * height > _MAX_PIXELS:
                raise invalid("The image is too large to preview.")
            source.draft("RGB", (_MAX_SIDE, _MAX_SIDE))
            oriented = ImageOps.exif_transpose(source)
            transparent = keep_transparency and _has_transparency(oriented)
            image = oriented.convert("RGBA") if transparent else _flatten(oriented)
            image.thumbnail((_MAX_SIDE, _MAX_SIDE))
            output = BytesIO()
            if transparent:
                image.save(output, format="PNG", optimize=True)
            else:
                image.save(output, format="JPEG", quality=_JPEG_QUALITY)
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError):
        raise invalid("The provider returned media that isn't an image.") from None
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    kind = "png" if transparent else "jpeg"
    return f"data:image/{kind};base64,{encoded}", image.width, image.height


def _has_transparency(image: Any) -> bool:
    if image.mode == "P":
        return "transparency" in image.info
    if image.mode not in {"RGBA", "LA"}:
        return False
    low, _high = image.getchannel("A").getextrema()
    return low < 255


def _flatten(image: Any) -> Image.Image:
    # Transparent areas show white, as they do in the providers' own previews.
    if image.mode in {"RGBA", "LA", "P"}:
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")
