# apps/api/tests/integrations/google_ads/test_upload_media_tool.py

"""Google Ads media uploads: the approval check, pins, exact payloads, and unclear replies."""

import asyncio
import base64
import hashlib
import importlib
from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from PIL import Image

from core.exceptions.integration import IntegrationFailureDisposition, IntegrationValidationError
from integrations.google_ads.operations.media import ImageSource, image_fits, youtube_video_id
from integrations.google_ads.tools import upload_media as tool_module
from integrations.google_ads.tools.schemas.media import GoogleAdsMediaUploadOutput
from integrations.google_ads.tools.utils.accounts import approval_accounts
from services.integrations.context.domain import ResolvedActiveContext
from services.integrations.files import FileReference
from tests.integrations.google_ads.support import _writable_google_ads_entry

_C = "customers/111"
_ENTRY = replace(
    _writable_google_ads_entry(),
    permissions_metadata={
        "login_customer_id": "999",
        "currency_code": "GBP",
        "time_zone": "Europe/London",
    },
)


def _png(width: int, height: int) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, "PNG")
    return buffer.getvalue()


def _source(name: str, data: bytes, *, size_bytes: int | None = None) -> ImageSource:
    revision = SimpleNamespace(
        id=uuid4(),
        content_hash=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data) if size_bytes is None else size_bytes,
        content_type="image/png",
        extension=".png",
        data=data,
    )
    return ImageSource(SimpleNamespace(id=uuid4(), name=name), revision)


class _Google:
    """Serves asset creates and searches.

    `lose` drops the reply to the first create; `cancel_read` cancels the run at the read-back.
    """

    def __init__(self, *, lose: bool = False, cancel_read: bool = False) -> None:
        self.lose = lose
        self.cancel_read = cancel_read
        self.creates: list[dict[str, Any]] = []
        self.assets: dict[str, dict[str, Any]] = {}

    async def post(self, path: str, **kwargs: Any) -> Any:
        body = kwargs["json"]
        if path.endswith("googleAds:searchStream"):
            return [{"results": self._search(body["query"])}]
        assert path == f"{_C}/assets:mutate"
        ((operation,),) = [body["operations"]]
        create = operation["create"]
        self.creates.append(create)
        asset_id = str(900 + len(self.creates))
        self.assets[asset_id] = create
        if self.lose:
            self.lose = False
            raise IntegrationValidationError(
                "Google Ads didn't reply.",
                provider_key="google_ads",
                failure_disposition=IntegrationFailureDisposition.AMBIGUOUS,
            )
        return {"results": [{"resourceName": f"{_C}/assets/{asset_id}"}]}

    def _search(self, query: str) -> list[dict[str, Any]]:
        if self.cancel_read and "asset.id IN" in query:
            raise asyncio.CancelledError
        if "asset.name = " in query:
            return [
                {"asset": {"id": key}}
                for key, asset in self.assets.items()
                if f"asset.name = '{asset.get('name')}'" in query
            ]
        return [
            {"asset": {"id": key, "youtubeVideoAsset": {"youtubeVideoTitle": "Trail Fit 2026"}}}
            for key, asset in self.assets.items()
            if "youtubeVideoAsset" in asset and key in query
        ]


def _deps(sources: list[ImageSource], monkeypatch) -> SimpleNamespace:
    by_id = {source.file.id: source for source in sources}

    async def resolve(_db, *, workspace_id, file_id):
        return by_id[file_id]

    async def read(revision):
        return revision.data

    monkeypatch.setattr(tool_module, "resolve_image_source", resolve)
    reader = importlib.import_module("services.integrations.files.read_pinned_file_source")
    monkeypatch.setattr(reader, "read_file_source", read)
    return SimpleNamespace(
        active_context=ResolvedActiveContext(entries=(_ENTRY,)),
        db=None,
        user=None,
        workspace=SimpleNamespace(id=uuid4()),
        agent=SimpleNamespace(id=uuid4(), name="Ads agent"),
        run=SimpleNamespace(id=uuid4(), user_id=uuid4()),
    )


def _files(sources: list[ImageSource]) -> list[FileReference]:
    return [FileReference(entity_id=source.file.id, label=source.file.name) for source in sources]


def _display(*sources: ImageSource) -> dict[str, Any]:
    return {
        "_accounts": approval_accounts([_ENTRY]),
        "_files": [source.approval_details() for source in sources],
    }


async def _run(monkeypatch, deps, google: _Google, *, display, files, videos=None, audits=None):
    audits = [] if audits is None else audits

    async def audit(**kwargs):
        audits.append(kwargs)
        return uuid4()

    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    monkeypatch.setattr(tool_module, "google_ads_client", AsyncMock(return_value=google))
    monkeypatch.setattr(tool_module, "approved_display_args", lambda _ctx: display)
    ctx = SimpleNamespace(
        deps=deps,
        tool_call_approved=display is not None,
        tool_name="google_ads_upload_media",
        tool_call_id="upload-media-call",
    )
    result = await tool_module.google_ads_upload_media(ctx, files, videos)
    GoogleAdsMediaUploadOutput.model_validate(result)
    return result["results"][0], audits


async def test_card_shows_where_each_image_fits_and_flags_one_google_wont_take(monkeypatch):
    square = _source("logo-mark.png", _png(400, 400))
    large = _source("trail-hero-wide.png", b"x", size_bytes=6_200 * 1024)
    deps = _deps([square, large], monkeypatch)
    args = {"files": [ref.model_dump(mode="json") for ref in _files([square, large])]}

    display = await tool_module._approval_display_args(deps, args)

    shown, refused = display["_files"]
    # 400 x 400 fits the square shapes, and has the wrong shape for landscape.
    assert (shown["width"], shown["height"], shown["problem"]) == (400, 400, None)
    assert shown["fits"] == ["SQUARE_MARKETING_IMAGE", "LOGO"]
    assert shown["too_small"] == []
    assert refused["problem"] is not None and refused["width"] is None
    assert image_fits(500, 262) == ([], ["MARKETING_IMAGE"])


async def test_approved_upload_sends_each_asset_once_and_audits_provenance_without_bytes(
    monkeypatch,
):
    image = _source("grip-sole-square.png", _png(1200, 1200))
    deps = _deps([image], monkeypatch)
    google = _Google()

    entry, audits = await _run(
        monkeypatch,
        deps,
        google,
        display=_display(image),
        files=_files([image]),
        videos=["https://youtu.be/dQw4w9WgXcQ"],
    )

    assert google.creates == [
        {
            "name": f"grip-sole-square.png ({image.revision.content_hash[:8]})",
            "type": "IMAGE",
            "imageAsset": {"data": base64.b64encode(image.revision.data).decode("ascii")},
        },
        {"type": "YOUTUBE_VIDEO", "youtubeVideoAsset": {"youtubeVideoId": "dQw4w9WgXcQ"}},
    ]
    uploads = entry["data"]["uploads"]
    assert [(row["outcome"], row["asset"]["asset_id"]) for row in uploads] == [
        ("uploaded", "901"),
        ("linked", "902"),
    ]
    assert uploads[0]["fits"] == ["SQUARE_MARKETING_IMAGE", "LOGO"]
    assert uploads[1]["name"] == "Trail Fit 2026"
    detail = audits[-1]["operation_detail"]
    image_intent = detail.intent_groups[0].items[0].fields
    assert image_intent["content_hash"] == image.revision.content_hash
    assert image_intent["revision_id"] == str(image.revision.id)
    assert google.creates[0]["imageAsset"]["data"] not in str(detail.model_dump())


async def test_oversized_image_is_refused_before_anything_is_sent(monkeypatch):
    large = _source("trail-hero-wide.png", b"x", size_bytes=6_200 * 1024)
    deps = _deps([large], monkeypatch)
    google = _Google()

    entry, _audits = await _run(monkeypatch, deps, google, display=None, files=_files([large]))

    assert entry["error_code"] == "unsupported_image"
    assert google.creates == []


async def test_file_changed_after_approval_is_not_uploaded(monkeypatch):
    reviewed = _source("runner-portrait.png", _png(960, 1200))
    current = replace(
        reviewed, revision=SimpleNamespace(**{**vars(reviewed.revision), "id": uuid4()})
    )
    deps = _deps([current], monkeypatch)
    google = _Google()

    entry, _audits = await _run(
        monkeypatch, deps, google, display=_display(reviewed), files=_files([current])
    )

    assert entry["error_code"] == "source_changed"
    assert google.creates == []


async def test_account_changed_after_approval_is_not_uploaded_to(monkeypatch):
    image = _source("grip-sole-square.png", _png(1200, 1200))
    deps = _deps([image], monkeypatch)
    other = replace(_ENTRY, display_name="Another account")
    display = {**_display(image), "_accounts": approval_accounts([other])}
    google = _Google()

    entry, _audits = await _run(monkeypatch, deps, google, display=display, files=_files([image]))

    assert entry["status"] == "error"
    assert google.creates == []


async def test_file_that_is_not_the_image_it_claims_is_not_sent(monkeypatch):
    fake = _source("notes.png", b"not an image")
    deps = _deps([fake], monkeypatch)
    google = _Google()

    entry, _audits = await _run(monkeypatch, deps, google, display=None, files=_files([fake]))

    (upload,) = entry["data"]["uploads"]
    assert (upload["outcome"], upload["error_code"]) == ("failed", "unsupported_image")
    assert google.creates == []


async def test_cancel_during_the_read_back_keeps_the_uploads_in_the_audit_record(monkeypatch):
    image = _source("grip-sole-square.png", _png(1200, 1200))
    deps = _deps([image], monkeypatch)
    audits: list[dict[str, Any]] = []

    with pytest.raises(asyncio.CancelledError):
        await _run(
            monkeypatch,
            deps,
            _Google(cancel_read=True),
            display=None,
            files=_files([image]),
            audits=audits,
        )

    (outcome,) = audits[-1]["operation_detail"].outcome_groups[0].outcomes
    assert outcome.status == "applied"
    assert outcome.effects[0].external_ref == f"{_C}/assets/901"


async def test_unclear_reply_is_settled_by_finding_the_asset_and_never_resent(monkeypatch):
    image = _source("forest-run-wide.png", _png(1200, 628))
    deps = _deps([image], monkeypatch)
    google = _Google(lose=True)

    entry, _audits = await _run(monkeypatch, deps, google, display=None, files=_files([image]))

    (upload,) = entry["data"]["uploads"]
    assert (upload["outcome"], upload["recovered"]) == ("uploaded", True)
    assert upload["asset"]["asset_id"] == "901"
    assert upload["fits"] == ["MARKETING_IMAGE"]
    assert len(google.creates) == 1


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30", "dQw4w9WgXcQ"),
        ("youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtube.evil.example/watch?v=dQw4w9WgXcQ", None),
        ("http://[bad/watch?v=dQw4w9WgXcQ", None),
    ],
)
def test_youtube_links_give_their_video_id_only_from_youtube(value, expected) -> None:
    assert youtube_video_id(value) == expected
