"""Meta asset reads: per-kind permission notes, paging, and untrusted provider values."""

import httpx2
import pytest

from core.exceptions.integration import IntegrationValidationError
from integrations.meta_ads.client import MetaAdsClient
from integrations.meta_ads.operations.list_assets import ASSET_KINDS, list_assets
from tests.integrations.meta_ads.support import static_token

META_THUMBNAIL = "https://scontent.xx.fbcdn.net/v/t45/thumb.jpg"


def graph(request: httpx2.Request) -> httpx2.Response:
    edge = request.url.path.rsplit("/", 1)[-1]
    if edge == "promote_pages":
        error = {"code": 200, "message": "Permissions error", "fbtrace_id": "t"}
        return httpx2.Response(403, json={"error": error}, request=request)
    rows = {
        "connected_instagram_accounts": [
            {"id": "17841", "username": "acme", "profile_pic": "https://evil.example/pic.jpg"}
        ],
        "adimages": [
            {"hash": "abc123", "name": "spring.png", "status": "ACTIVE", "url_128": META_THUMBNAIL},
            {"hash": "def456", "name": "old.png", "status": "DELETED"},
        ],
        "advideos": [{"id": "77", "title": "launch.mp4", "status": {"video_status": "error"}}],
    }[edge]
    return httpx2.Response(200, json={"data": rows}, request=request)


async def read(handler=graph, kinds=None):
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http:
        return await list_assets(
            MetaAdsClient(static_token, client=http),
            account_id="123",
            scope_label="Acme",
            kinds=kinds or ASSET_KINDS,
        )


async def test_refused_kind_becomes_a_note_and_other_kinds_still_return():
    result = await read()

    assert result.pages == []
    assert len(result.notes) == 1 and "pages_show_list" in result.notes[0]
    assert [image.image_hash for image in result.images] == ["abc123"]
    assert result.videos[0].media_status == "failed"


async def test_only_meta_hosted_addresses_are_kept():
    result = await read()

    assert result.images[0].thumbnail_url == META_THUMBNAIL
    assert result.instagram_accounts[0].picture_url is None
    assert result.instagram_accounts[0].label == "@acme"


async def test_inactive_and_short_pages_do_not_hide_later_active_images():
    pages = {
        None: [{"hash": "dead01", "status": "DELETED"}],
        "p2": [{"hash": "dead02", "status": "DELETED"}],
        "p3": [{"hash": "abc123", "name": "spring.png", "status": "ACTIVE"}],
    }
    following = {None: "p2", "p2": "p3", "p3": None}

    def library(request: httpx2.Request) -> httpx2.Response:
        after = request.url.params.get("after")
        body = {"data": pages[after]}
        if following[after]:
            next_url = f"https://graph.facebook.com{request.url.path}?after={following[after]}"
            body["paging"] = {"next": next_url}
        return httpx2.Response(200, json=body, request=request)

    result = await read(library, kinds=["images"])

    assert [image.image_hash for image in result.images] == ["abc123"]
    assert result.truncated == []


async def test_malformed_page_id_fails_as_a_typed_error_without_the_value():
    page_id = "9" * 200

    def pages(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"data": [{"id": page_id}]}, request=request)

    with pytest.raises(IntegrationValidationError) as failure:
        await read(pages, kinds=["pages"])

    assert page_id not in str(failure.value)
