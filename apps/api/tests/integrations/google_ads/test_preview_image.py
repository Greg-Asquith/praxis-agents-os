# apps/api/tests/integrations/google_ads/test_preview_image.py

"""Google Ads image previews: the account's own image, Google-only hosts, re-encoded pictures."""

from io import BytesIO

import httpx2
import pytest
from PIL import Image
from pydantic import SecretStr

from core.exceptions.integration import IntegrationValidationError
from integrations.google_ads.client import GoogleAdsClient
from integrations.google_ads.operations.preview_image import preview_image

HOST = "https://tpc.googlesyndication.com/simgad/123"


async def _token(_force: bool) -> str:
    return "access-token"


def _png(width: int, height: int) -> bytes:
    output = BytesIO()
    Image.new("RGBA", (width, height), (0, 0, 255, 128)).save(output, format="PNG")
    return output.getvalue()


async def _preview(*, image_url: str, fetched: list[str], queries: list[str]):
    def search(request: httpx2.Request) -> httpx2.Response:
        queries.append(f"{request.url.path} {request.read().decode()}")
        row = {"asset": {"id": "301", "imageAsset": {"fullSize": {"url": image_url}}}}
        return httpx2.Response(200, json=[{"results": [row]}], request=request)

    def serve(request: httpx2.Request) -> httpx2.Response:
        fetched.append(str(request.url))
        assert "authorization" not in request.headers
        return httpx2.Response(200, content=_png(1200, 628), request=request)

    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(search)) as http,
        httpx2.AsyncClient(transport=httpx2.MockTransport(serve)) as download,
    ):
        return await preview_image(
            GoogleAdsClient(_token, developer_token=SecretStr("dev"), client=http),
            customer_id="123-456-7890",
            login_customer_id="111",
            asset_id="301",
            download_client=download,
        )


async def test_transparent_image_in_the_account_stays_a_bounded_png() -> None:
    fetched: list[str] = []
    queries: list[str] = []

    content, width, height = await _preview(image_url=HOST, fetched=fetched, queries=queries)

    # Logos are often round on a transparent square, so the transparency is kept.
    assert content.startswith("data:image/png;base64,")
    assert (width, height) == (720, 377)
    assert fetched == [HOST]
    # Read in the conversation's customer, so another account's image isn't found.
    assert "customers/1234567890/googleAds:searchStream" in queries[0]
    assert "asset.id = 301" in queries[0]


async def test_address_off_google_hosts_is_never_fetched() -> None:
    fetched: list[str] = []
    with pytest.raises(IntegrationValidationError, match="address"):
        await _preview(
            image_url="https://tpc.googlesyndication.com.evil.example/x.png",
            fetched=fetched,
            queries=[],
        )

    assert fetched == []
