# apps/api/tests/integrations/google_ads/test_upload_media_tool.py

"""Google Ads media uploads: the approval check, pins, payloads, videos, and unclear replies."""

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

import httpx2
import pytest
from PIL import Image
from pydantic_ai import ModelRetry

from core.exceptions.integration import (
    IntegrationConnectionError,
    IntegrationFailureDisposition,
    IntegrationValidationError,
)
from integrations.google_ads.client import GOOGLE_ADS_UPLOAD_BASE_URL, GoogleAdsClient
from integrations.google_ads.operations import (
    upload_media as operation_module,
    video_upload as video_module,
)
from integrations.google_ads.operations.media import (
    ImageSource,
    VideoSource,
    image_fits,
    youtube_video_id,
)
from integrations.google_ads.tools import upload_media as tool_module
from integrations.google_ads.tools.schemas.media import (
    GoogleAdsMediaUploadOutput,
    GoogleAdsVideoDetails,
)
from integrations.google_ads.tools.utils.accounts import approval_accounts
from services.integrations.context.domain import ResolvedActiveContext
from services.integrations.files import FileReference
from tests.integrations.google_ads.support import _writable_google_ads_entry

_C = "customers/111"
_UPLOAD_URL = (
    f"{GOOGLE_ADS_UPLOAD_BASE_URL}/customers/111/"
    "youTubeVideoUploads:create?upload_id=ADPycdv7&upload_protocol=resumable"
)
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


def _video(name: str, data: bytes) -> VideoSource:
    revision = SimpleNamespace(
        id=uuid4(),
        content_hash=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        content_type="video/mp4",
        extension=".mp4",
        data=data,
        media_metadata={"duration_ms": 12_000, "has_audio": True, "rotation": 0},
    )
    return VideoSource(SimpleNamespace(id=uuid4(), name=name), revision)


class _Google:
    """Serves asset creates, searches, and resumable video uploads.

    `lose` drops the reply to the first create; `cancel_read` cancels the run at the read-back.
    `cut_at` loses the reply to the chunk at that offset after Google kept two of its bytes.
    `state` is what Google reports for upload 555 once it's finalised.
    """

    def __init__(
        self,
        *,
        lose: bool = False,
        cancel_read: bool = False,
        cut_at: int | None = None,
        state: str = "PROCESSED",
    ) -> None:
        self.lose = lose
        self.cancel_read = cancel_read
        self.cut_at = cut_at
        self.state = state
        self.creates: list[dict[str, Any]] = []
        self.assets: dict[str, dict[str, Any]] = {}
        self.uploads: list[tuple[str, str, dict[str, str], Any]] = []
        self.received = b""
        self.finalised = False

    async def upload_request(self, method: str, url: str, **kwargs: Any) -> httpx2.Response:
        headers = kwargs["headers"]
        command = headers["X-Goog-Upload-Command"]
        self.uploads.append((method, command, headers, kwargs.get("json", kwargs.get("content"))))
        if command == "start":
            return httpx2.Response(
                200,
                headers={"x-goog-upload-url": _UPLOAD_URL, "x-goog-upload-chunk-granularity": "4"},
            )
        assert url == _UPLOAD_URL
        if command == "query":
            return httpx2.Response(
                200,
                headers={
                    "x-goog-upload-status": "active",
                    "x-goog-upload-size-received": str(len(self.received)),
                },
            )
        offset = int(headers["X-Goog-Upload-Offset"])
        assert offset == len(self.received)
        self.received += kwargs["content"]
        if offset == self.cut_at:
            self.cut_at = None
            self.received = self.received[: offset + 2]
            raise IntegrationConnectionError(
                "Google Ads didn't reply.",
                provider_key="google_ads",
                failure_disposition=IntegrationFailureDisposition.AMBIGUOUS,
            )
        if command == "upload, finalize":
            self.finalised = True
            return httpx2.Response(200, json={"resourceName": f"{_C}/youTubeVideoUploads/555"})
        return httpx2.Response(200, headers={"x-goog-upload-status": "active"})

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
        if "FROM you_tube_video_upload" in query:
            video_id = "Vj3hTq9kLm0" if self.state == "PROCESSED" else None
            upload = {"videoUploadId": "555", "state": self.state, "videoId": video_id}
            return [{"youTubeVideoUpload": upload}] if self.finalised else []
        if "youtube_video_id = " in query:
            return [
                {"asset": {"id": key}}
                for key, asset in self.assets.items()
                if f"'{asset['youtubeVideoAsset']['youtubeVideoId']}'" in query
            ]
        if "asset.name = " in query:
            return [
                {"asset": {"id": key}}
                for key, asset in self.assets.items()
                if f"asset.name = '{asset.get('name')}'" in query
            ]
        return [
            {
                "asset": {"id": key, "youtubeVideoAsset": {"youtubeVideoTitle": "Trail Fit 2026"}}
                if "youtubeVideoAsset" in asset
                # Google's own check disagrees with an image nobody declared.
                else {
                    "id": key,
                    "syntheticContentInfo": {
                        **asset.get("syntheticContentInfo", {}),
                        "systemAttestation": {"status": "IS_SYNTHETIC"},
                    },
                }
            }
            for key, asset in self.assets.items()
            if key in query
        ]


def _deps(sources: list[ImageSource | VideoSource], monkeypatch) -> SimpleNamespace:
    by_id = {source.file.id: source for source in sources}

    async def resolve(_db, *, workspace_id, file_id):
        return by_id[file_id]

    async def read(revision):
        return revision.data

    monkeypatch.setattr(tool_module, "resolve_media_source", resolve)
    reader = importlib.import_module("services.integrations.files.read_pinned_file_source")
    monkeypatch.setattr(reader, "read_file_source", read)

    class Storage:
        async def stat_object(self, revision):
            return SimpleNamespace(size_bytes=len(revision.data))

        async def stream_object(self, revision):
            for start in range(0, len(revision.data), 3):
                yield revision.data[start : start + 3]

    streamer = importlib.import_module("services.integrations.files.stream_file_source")
    monkeypatch.setattr(streamer, "get_storage_provider", Storage)
    monkeypatch.setattr(streamer, "file_revision_ref", lambda revision: revision)
    # Chunks of Google's 4-byte granularity, and no waiting for processing.
    monkeypatch.setattr(video_module, "_CHUNK_BYTES", 4)
    monkeypatch.setattr(operation_module, "PROCESSING_WAIT_SECONDS", 0)
    return SimpleNamespace(
        active_context=ResolvedActiveContext(entries=(_ENTRY,)),
        db=None,
        user=None,
        workspace=SimpleNamespace(id=uuid4()),
        agent=SimpleNamespace(id=uuid4(), name="Ads agent"),
        run=SimpleNamespace(id=uuid4(), user_id=uuid4()),
    )


def _files(sources: list[ImageSource | VideoSource]) -> list[FileReference]:
    return [FileReference(entity_id=source.file.id, label=source.file.name) for source in sources]


def _display(*sources: ImageSource | VideoSource) -> dict[str, Any]:
    return {
        "_accounts": approval_accounts([_ENTRY]),
        "_files": [source.approval_details() for source in sources],
    }


async def _run(
    monkeypatch,
    deps,
    google: _Google,
    *,
    display,
    files,
    videos=None,
    audits=None,
    details=None,
    uploads=None,
    made_with_ai=None,
):
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
    result = await tool_module.google_ads_upload_media(
        ctx, files, videos, details, uploads, made_with_ai
    )
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
        made_with_ai=[image.file.id],
    )

    assert google.creates == [
        {
            "name": f"grip-sole-square.png ({image.revision.content_hash[:8]})",
            "type": "IMAGE",
            "imageAsset": {"data": base64.b64encode(image.revision.data).decode("ascii")},
            "syntheticContentInfo": {
                "advertiserAttestation": {"status": "IS_SYNTHETIC", "source": "ADVERTISER_ATTESTED"}
            },
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
    assert [row["made_with_ai"] for row in uploads] == [True, None]
    detail = audits[-1]["operation_detail"]
    image_intent = detail.intent_groups[0].items[0].fields
    assert image_intent["content_hash"] == image.revision.content_hash
    assert image_intent["revision_id"] == str(image.revision.id)
    assert image_intent["made_with_ai"] is True
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
    # Nothing is declared for a File that isn't marked, and Google's own answer still shows.
    assert "syntheticContentInfo" not in google.creates[0]
    assert (upload["made_with_ai"], upload["google_made_with_ai"]) == (False, True)


async def test_video_file_streams_in_googles_chunks_and_becomes_one_asset(monkeypatch):
    video = _video("trail-fit-launch.mp4", b"VIDEOBYTES")
    deps = _deps([video], monkeypatch)
    google = _Google()
    details = [
        GoogleAdsVideoDetails(
            file_id=video.file.id, title="Trail Fit Launch", description="Our autumn range."
        )
    ]

    entry, audits = await _run(
        monkeypatch,
        deps,
        google,
        display=_display(video),
        files=_files([video]),
        details=details,
        made_with_ai=[video.file.id],
    )

    start, *chunks = google.uploads
    assert start == (
        "POST",
        "start",
        {
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": "10",
        },
        {
            "customer_id": "111",
            "you_tube_video_upload": {
                "video_title": "Trail Fit Launch",
                "video_description": "Our autumn range.",
                "video_content_metadata": {"generative_content_disclosure": "GENERATIVE_CONTENT"},
            },
        },
    )
    assert [
        (command, headers["X-Goog-Upload-Offset"], body) for _m, command, headers, body in chunks
    ] == [
        ("upload", "0", b"VIDE"),
        ("upload", "4", b"OBYT"),
        ("upload, finalize", "8", b"ES"),
    ]
    assert google.creates == [
        {"type": "YOUTUBE_VIDEO", "youtubeVideoAsset": {"youtubeVideoId": "Vj3hTq9kLm0"}}
    ]
    (upload,) = entry["data"]["uploads"]
    assert (upload["kind"], upload["outcome"], upload["upload_id"]) == ("video", "uploaded", "555")
    assert upload["asset"]["asset_id"] == "901"
    # The session is recorded before the first chunk, then the upload once Google names it.
    checkpoints = [c for audit in audits for c in audit.get("checkpoints") or ()]
    assert checkpoints[0].references == {"upload_session": "ADPycdv7"}
    assert checkpoints[-1].references["video_upload_id"] == "555"
    detail = audits[-1]["operation_detail"]
    intent = detail.intent_groups[0].items[0].fields
    assert intent["content_hash"] == video.revision.content_hash
    assert intent["revision_id"] == str(video.revision.id)
    assert "VIDEOBYTES" not in str(detail.model_dump())


async def test_unclear_chunk_reply_resumes_from_what_google_received(monkeypatch):
    video = _video("trail-fit-launch.mp4", b"VIDEOBYTES")
    deps = _deps([video], monkeypatch)
    google = _Google(cut_at=4)

    entry, _audits = await _run(monkeypatch, deps, google, display=None, files=_files([video]))

    sent = [
        (command, headers.get("X-Goog-Upload-Offset"), body)
        for _m, command, headers, body in google.uploads
    ]
    assert sent[1:] == [
        ("upload", "0", b"VIDE"),
        ("upload", "4", b"OBYT"),
        ("query", None, None),
        # Google kept "OB", so only the rest of that chunk goes again.
        ("upload", "6", b"YT"),
        ("upload, finalize", "8", b"ES"),
    ]
    assert [command for _m, command, _h, _b in google.uploads].count("start") == 1
    assert google.received == b"VIDEOBYTES"
    assert entry["data"]["uploads"][0]["outcome"] == "uploaded"


async def test_video_still_processing_is_finished_by_a_later_call_once(monkeypatch):
    video = _video("trail-fit-launch.mp4", b"VIDEOBYTES")
    deps = _deps([video], monkeypatch)
    google = _Google(state="UPLOADED")

    entry, _audits = await _run(monkeypatch, deps, google, display=None, files=_files([video]))

    (upload,) = entry["data"]["uploads"]
    assert (upload["outcome"], upload["upload_id"], upload["asset"]) == ("processing", "555", None)
    assert google.creates == []

    google.state = "PROCESSED"
    for _call in range(2):
        entry, _audits = await _run(
            monkeypatch,
            deps,
            google,
            display=None,
            files=None,
            uploads=[f"{_C}/youTubeVideoUploads/555"],
        )
        (upload,) = entry["data"]["uploads"]
        assert (upload["outcome"], upload["asset"]["asset_id"]) == ("uploaded", "901")
    # The second call finds the asset the first one made.
    assert len(google.creates) == 1
    assert [command for _m, command, _h, _b in google.uploads].count("start") == 1


async def test_ai_mark_for_a_file_that_isnt_uploaded_is_refused(monkeypatch):
    image = _source("grip-sole-square.png", _png(1200, 1200))
    google = _Google()

    with pytest.raises(ModelRetry, match="made_with_ai"):
        await _run(
            monkeypatch,
            _deps([image], monkeypatch),
            google,
            display=None,
            files=_files([image]),
            made_with_ai=[uuid4()],
        )

    assert google.creates == []


async def test_video_title_with_angle_brackets_is_refused_before_any_request(monkeypatch):
    video = _video("trail-fit-launch.mp4", b"VIDEOBYTES")
    deps = _deps([video], monkeypatch)
    google = _Google()
    details = [GoogleAdsVideoDetails(file_id=video.file.id, title="<b>Trail Fit</b>")]

    with pytest.raises(ModelRetry, match="< or >"):
        await _run(monkeypatch, deps, google, display=None, files=_files([video]), details=details)

    assert google.uploads == []


async def test_videos_over_one_gigabyte_in_total_are_refused_before_any_request(monkeypatch):
    videos = [_video(f"reel-{number}.mp4", b"VIDEOBYTES") for number in range(2)]
    for video in videos:
        video.revision.size_bytes = 600 * 1024 * 1024
    google = _Google()

    entry, _audits = await _run(
        monkeypatch, _deps(videos, monkeypatch), google, display=None, files=_files(videos)
    )

    assert entry["status"] == "error" and "at most 1 GB" in entry["error_message"]
    assert google.uploads == []


def test_an_emptied_video_description_is_no_description() -> None:
    details = GoogleAdsVideoDetails(file_id=uuid4(), title="Trail Fit", description=" ")

    assert details.description is None


async def test_upload_address_off_googles_host_never_gets_the_token() -> None:
    sent: list[httpx2.Request] = []
    transport = httpx2.MockTransport(lambda request: sent.append(request) or httpx2.Response(200))
    async with httpx2.AsyncClient(transport=transport) as http:
        client = GoogleAdsClient(_token, client=http)
        with pytest.raises(IntegrationValidationError) as raised:
            await client.upload_request(
                "PUT",
                "https://uploads.example.com/upload?upload_id=ADPycdv7",
                operation="upload_media",
                headers={"X-Goog-Upload-Command": "upload"},
                content=b"VIDE",
            )

    assert raised.value.failure_disposition is IntegrationFailureDisposition.NOT_DISPATCHED
    assert sent == []


async def _token(_force: bool) -> str:
    return "access-token"


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
