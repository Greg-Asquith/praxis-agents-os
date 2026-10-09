"""Meta library media previews: account ownership, Meta-only hosts, and re-encoded images."""

import base64
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import httpx2
import pytest
from PIL import Image

from core.exceptions.integration import IntegrationValidationError
from integrations.meta_ads.client import MetaAdsClient
from integrations.meta_ads.operations.preview_media import preview_media
from integrations.meta_ads.preview import fetch_media_preview
from services.integrations.plugin import IntegrationPreviewRequest
from tests.integrations.meta_ads.support import static_token

CDN = "https://scontent.xx.fbcdn.net/v/t45/full.png"


def png(width: int, height: int) -> bytes:
    output = BytesIO()
    Image.new("RGBA", (width, height), (255, 0, 0, 128)).save(output, format="PNG")
    return output.getvalue()


def graph(image_url: str = CDN):
    def handle(request: httpx2.Request) -> httpx2.Response:
        edge = request.url.path.rsplit("/", 1)[-1]
        rows = {
            "adimages": [{"hash": "abc123", "url": image_url, "status": "ACTIVE"}],
            "advideos": [{"id": "77", "title": "launch.mp4", "status": {"video_status": "ready"}}],
            "thumbnails": [{"uri": CDN, "is_preferred": True}],
            "promote_pages": [{"id": "11", "name": "Acme", "picture": {"data": {"url": CDN}}}],
        }[edge]
        return httpx2.Response(200, json={"data": rows}, request=request)

    return handle


async def preview(media_type, media_id, *, cdn, image_url=CDN, fetched=None):
    fetched = [] if fetched is None else fetched

    def serve(request: httpx2.Request) -> httpx2.Response:
        fetched.append(str(request.url))
        assert "authorization" not in request.headers
        return httpx2.Response(200, content=cdn, request=request)

    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(graph(image_url))) as http,
        httpx2.AsyncClient(transport=httpx2.MockTransport(serve)) as download,
    ):
        return await preview_media(
            MetaAdsClient(static_token, client=http),
            account_id="123",
            media_type=media_type,
            media_id=media_id,
            download_client=download,
        )


async def test_image_is_re_encoded_as_a_bounded_jpeg():
    content, width, height = await preview("image", "abc123", cdn=png(2000, 1000))

    data = base64.b64decode(content.removeprefix("data:image/jpeg;base64,"))
    assert Image.open(BytesIO(data)).format == "JPEG"
    assert (width, height) == (720, 360)
    assert len(content) < 200_000


async def test_video_outside_the_account_library_is_refused_without_fetching():
    fetched: list[str] = []
    with pytest.raises(IntegrationValidationError, match="500 most recent"):
        await preview("video", "99", cdn=png(10, 10), fetched=fetched)

    assert fetched == []


async def test_page_the_account_cannot_advertise_as_is_refused_without_fetching():
    fetched: list[str] = []
    with pytest.raises(IntegrationValidationError, match="can't advertise as this Page"):
        await preview("page", "12", cdn=png(10, 10), fetched=fetched)

    assert fetched == []
    assert (await preview("page", "11", cdn=png(64, 64)))[1:] == (64, 64)


async def test_address_off_meta_hosts_is_never_fetched():
    fetched: list[str] = []
    with pytest.raises(IntegrationValidationError, match="address"):
        await preview(
            "image",
            "abc123",
            cdn=png(10, 10),
            image_url="https://evil.example/x.png",
            fetched=fetched,
        )

    assert fetched == []


async def test_bytes_that_are_not_an_image_are_refused():
    with pytest.raises(IntegrationValidationError, match="isn't an image"):
        await preview("image", "abc123", cdn=b"<svg onload='alert(1)'></svg>")


async def test_preview_without_a_conversation_ad_account_is_refused():
    request = IntegrationPreviewRequest(
        ref="image_abc123", scope_id=None, actor=SimpleNamespace(), workspace=SimpleNamespace()
    )

    with pytest.raises(IntegrationValidationError, match="needs an ad account"):
        await fetch_media_preview(None, SimpleNamespace(id=uuid4()), request)
