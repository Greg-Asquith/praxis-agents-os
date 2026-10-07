"""Meta media uploads: File policy, the approval pin, proof for unclear replies, and lifecycle."""

import asyncio
import hashlib
import importlib
import json
import re
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qsl
from uuid import uuid4

import httpx2
import pytest
from pydantic_ai import ModelRetry

from core.exceptions.integration import IntegrationValidationError
from integrations.meta_ads.client import MetaAdsClient
from integrations.meta_ads.operations import media_source, upload_media as upload_module
from integrations.meta_ads.operations.media_source import MediaSource, resolve_media_source
from integrations.meta_ads.operations.upload_media import upload_media
from integrations.meta_ads.tools.schemas.media import MetaAdsMediaUploadOutput
from integrations.meta_ads.tools.upload_media import meta_ads_upload_media, upload_entry
from services.integrations.context.domain import ResolvedActiveContext
from services.integrations.files import FileReference
from tests.integrations.meta_ads.support import context_entry, static_token

IMAGE = b"\x89PNG image bytes"
VIDEO = b"0123456789" * 3


def source(content: bytes, content_type: str, extension: str, *, name="spring") -> MediaSource:
    revision = SimpleNamespace(
        id=uuid4(),
        content_hash=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        content_type=content_type,
        extension=extension,
    )
    file = SimpleNamespace(id=uuid4(), name=f"{name}{extension}")
    return MediaSource(file, revision, "image" if content_type.startswith("image/") else "video")


def store(monkeypatch, content: bytes) -> SimpleNamespace:
    """Serves `content` as every File's stored bytes, in small chunks; reports open streams."""
    streams = SimpleNamespace(open=0)

    class Storage:
        async def stat_object(self, _ref):
            return SimpleNamespace(size_bytes=len(content))

        async def stream_object(self, _ref):
            streams.open += 1
            try:
                for start in range(0, len(content), 7):
                    yield content[start : start + 7]
            finally:
                streams.open -= 1

    seam = importlib.import_module("services.integrations.files.stream_file_source")
    monkeypatch.setattr(seam, "get_storage_provider", Storage)
    monkeypatch.setattr(seam, "file_revision_ref", lambda revision: revision)
    monkeypatch.setattr(media_source, "read_file_source", AsyncMock(return_value=content))
    return streams


def form(request: httpx2.Request) -> dict[str, str]:
    body = request.content.decode("latin-1")
    if "multipart/form-data" in request.headers.get("content-type", ""):
        return dict(
            re.findall(r'name="(\w+)"(?:; filename="[^"]*")?\r\n(?:[^\r]*\r\n)*?\r\n([^\r]*)', body)
        )
    return dict(parse_qsl(body))


class MediaGraph:
    """Serves Meta's image and chunked video upload edges from memory."""

    def __init__(
        self,
        *,
        image_reply="ok",
        start_reply="ok",
        transfer_reply="ok",
        finish_reply="ok",
        video_status="processing",
    ):
        self.image_reply = image_reply
        self.start_reply = start_reply
        self.transfer_reply = transfer_reply
        self.finish_reply = finish_reply
        self.video_status = video_status
        self.images: dict[str, dict] = {}
        self.image_posts = 0
        self.phases: list[str] = []
        self.status_reads = 0
        self.received = b""

    async def handle(self, request: httpx2.Request) -> httpx2.Response:
        edge = request.url.path.rsplit("/", 1)[-1]
        if request.method == "GET":
            return await self.read(request, edge)
        if edge == "adimages":
            return self.image(request)
        return self.video_phase(request, form(request))

    def image(self, request):
        self.image_posts += 1
        if self.image_reply == "reject":
            error = {"code": 100, "error_user_msg": "The image is invalid.", "fbtrace_id": "t"}
            return httpx2.Response(400, json={"error": error}, request=request)
        image_hash = hashlib.md5(IMAGE, usedforsecurity=False).hexdigest()
        if self.image_reply != "lost":
            self.images[image_hash] = {
                "hash": image_hash,
                "name": "spring.png",
                "status": "ACTIVE",
                "width": 1080,
                "height": 1080,
            }
        if self.image_reply in ("timeout", "lost"):
            raise httpx2.ReadTimeout("lost", request=request)
        return httpx2.Response(
            200, json={"images": {"spring.png": {"hash": image_hash}}}, request=request
        )

    def video_phase(self, request, values):
        phase = values["upload_phase"]
        self.phases.append(phase)
        if phase == "start":
            reply = {
                "video_id": "77",
                "upload_session_id": "5",
                "start_offset": "0",
                "end_offset": "16",
            }
            if self.start_reply == "bad_video_id":
                reply["video_id"] = "7" * 129
            if self.start_reply == "throttle":
                usage = json.dumps({"acc_id_util_pct": 100, "reset_time_duration": 60})
                headers = {"x-ad-account-usage": usage}
                return httpx2.Response(200, json=reply, headers=headers, request=request)
        elif phase == "transfer" and self.transfer_reply == "reject":
            error = {"code": 100, "error_user_msg": "The chunk is invalid.", "fbtrace_id": "t"}
            return httpx2.Response(400, json={"error": error}, request=request)
        elif phase == "transfer":
            start = int(values["start_offset"])
            chunk = request.content.split(b"\r\n\r\n")[-1].split(b"\r\n--")[0]
            self.received += chunk
            end = start + len(chunk)
            reply = {"start_offset": str(end), "end_offset": str(min(end + 16, len(VIDEO)))}
        elif phase == "finish" and self.finish_reply == "timeout":
            raise httpx2.ReadTimeout("lost", request=request)
        elif phase == "finish" and self.finish_reply == "reject":
            error = {"code": 100, "error_user_msg": "The video is invalid.", "fbtrace_id": "t"}
            return httpx2.Response(400, json={"error": error}, request=request)
        elif phase == "finish" and self.finish_reply == "cancel":
            raise asyncio.CancelledError
        else:
            reply = {"success": True}
        return httpx2.Response(200, json=reply, request=request)

    async def read(self, request, edge):
        if edge == "adimages":
            return httpx2.Response(200, json={"data": list(self.images.values())}, request=request)
        self.status_reads += 1
        if self.video_status == "stall":
            await asyncio.Event().wait()
        if self.video_status == "cancel":
            raise asyncio.CancelledError
        status = {"video_status": self.video_status}
        return httpx2.Response(
            200, json={"id": edge, "title": "spring.mp4", "status": status}, request=request
        )


async def run_upload(graph: MediaGraph, sources, *, poll_seconds=0):
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle)) as http:
        return await upload_media(
            MetaAdsClient(static_token, client=http),
            account_id="123",
            scope_label="Acme",
            sources=sources,
            poll_seconds=poll_seconds,
        )


async def test_unsupported_and_oversized_files_are_rejected_before_upload(monkeypatch):
    gif = source(b"GIF89a", "image/gif", ".gif")
    large = source(b"x" * 11, "image/png", ".png")
    workspace = SimpleNamespace(id=uuid4())
    reference = FileReference(entity_id=uuid4(), label="File")
    monkeypatch.setattr(media_source.meta_ads_settings, "META_ADS_IMAGE_MAX_UPLOAD_BYTES", 10)

    for candidate, code in ((gif, "unsupported_type"), (large, "too_large")):
        monkeypatch.setattr(
            media_source,
            "resolve_workspace_file_source",
            AsyncMock(return_value=(candidate.file, candidate.revision)),
        )
        with pytest.raises(IntegrationValidationError) as rejected:
            await resolve_media_source(None, workspace=workspace, reference=reference)
        assert rejected.value.error_code == code


async def test_unclear_image_reply_is_settled_by_finding_its_content_hash(monkeypatch):
    store(monkeypatch, IMAGE)
    graph = MediaGraph(image_reply="timeout")

    uploads, ledger = await run_upload(graph, [source(IMAGE, "image/png", ".png")])

    expected = hashlib.md5(IMAGE, usedforsecurity=False).hexdigest()
    assert uploads[0].outcome == "uploaded"
    assert uploads[0].recovered is True
    assert uploads[0].media.image_hash == expected
    assert ledger.external_refs == (expected,)


async def test_video_whose_stored_bytes_changed_is_never_finished(monkeypatch):
    store(monkeypatch, b"9" * len(VIDEO))
    graph = MediaGraph()

    uploads, ledger = await run_upload(graph, [source(VIDEO, "video/mp4", ".mp4")])

    assert graph.phases == ["start", "transfer", "transfer", "cancel"]
    assert uploads[0].outcome == "failed"
    assert ledger.parents[0].effects[0].error_code == "source_changed"


async def test_unclear_finish_counts_as_uploaded_once_meta_is_processing_it(monkeypatch):
    store(monkeypatch, VIDEO)
    graph = MediaGraph(finish_reply="timeout", video_status="processing")

    uploads, ledger = await run_upload(graph, [source(VIDEO, "video/mp4", ".mp4")])

    assert graph.received == VIDEO
    assert graph.phases == ["start", "transfer", "transfer", "finish"]
    assert uploads[0].recovered is True
    # Processing outlasted the wait, so the video is returned as not ready yet.
    assert uploads[0].outcome == "processing"
    assert ledger.parents[0].outcome == "applied"
    fields = dict(ledger.parents[0].effects[0].fields)
    assert fields["media_status"] == "processing" and fields["recovered"] == "true"


async def test_published_video_that_fails_processing_stays_applied_with_its_state(monkeypatch):
    store(monkeypatch, VIDEO)

    uploads, ledger = await run_upload(
        MediaGraph(video_status="error"), [source(VIDEO, "video/mp4", ".mp4")]
    )

    assert uploads[0].outcome == "failed"
    assert ledger.parents[0].outcome == "applied"
    assert dict(ledger.parents[0].effects[0].fields)["media_status"] == "failed"


async def test_rejected_transfer_releases_storage_before_returning(monkeypatch):
    streams = store(monkeypatch, VIDEO)
    graph = MediaGraph(transfer_reply="reject")

    uploads, _ledger = await run_upload(graph, [source(VIDEO, "video/mp4", ".mp4")])

    assert streams.open == 0
    assert graph.phases == ["start", "transfer", "cancel"]
    assert uploads[0].outcome == "failed"


async def test_throttle_learned_at_start_stops_the_transfer(monkeypatch):
    streams = store(monkeypatch, VIDEO)
    graph = MediaGraph(start_reply="throttle")

    uploads, ledger = await run_upload(graph, [source(VIDEO, "video/mp4", ".mp4")])

    # The known throttle also skips the best-effort cancel; nothing was published.
    assert graph.phases == ["start"]
    assert streams.open == 0
    assert uploads[0].outcome == "failed"
    assert ledger.parents[0].effects[0].error_code == "IntegrationRateLimitError"


async def test_stalled_status_read_ends_the_wait_with_readiness_unknown(monkeypatch):
    store(monkeypatch, VIDEO)
    monkeypatch.setattr(upload_module, "_MIN_READ_SECONDS", 0.05)
    graph = MediaGraph(video_status="stall")
    videos = [source(VIDEO, "video/mp4", ".mp4"), source(VIDEO, "video/mp4", ".mp4")]

    uploads, ledger = await run_upload(graph, videos)

    # The first read used the whole budget, so the second video was never polled.
    assert graph.status_reads == 1
    assert [upload.outcome for upload in uploads] == ["uploaded", "uploaded"]
    assert [upload.readiness for upload in uploads] == ["unknown", "unknown"]
    fields = [dict(parent.effects[0].fields) for parent in ledger.parents]
    assert [item["media_status"] for item in fields] == ["unknown", "unknown"]
    assert [parent.outcome for parent in ledger.parents] == ["applied", "applied"]


async def test_unclear_image_reply_without_a_match_stays_unverified_and_is_not_resent(
    monkeypatch,
):
    store(monkeypatch, IMAGE)
    graph = MediaGraph(image_reply="lost")

    uploads, ledger = await run_upload(graph, [source(IMAGE, "image/png", ".png")])

    assert graph.image_posts == 1
    assert uploads[0].outcome == "unverified"
    assert ledger.parents[0].outcome == "unverified"


async def test_confirmed_failure_does_not_stop_later_files(monkeypatch):
    store(monkeypatch, VIDEO)
    graph = MediaGraph(image_reply="reject", video_status="ready")
    files = [source(IMAGE, "image/png", ".png"), source(VIDEO, "video/mp4", ".mp4")]

    uploads, ledger = await run_upload(graph, files)

    assert [upload.outcome for upload in uploads] == ["failed", "uploaded"]
    assert [parent.outcome for parent in ledger.parents] == ["failed", "applied"]
    assert graph.phases[-1] == "finish"


async def test_cancelled_finish_leaves_it_unverified_and_later_files_undispatched(monkeypatch):
    store(monkeypatch, VIDEO)
    graph = MediaGraph(finish_reply="cancel")
    files = [
        source(VIDEO, "video/mp4", ".mp4"),
        source(VIDEO, "video/mp4", ".mp4"),
        source(VIDEO, "video/mp4", ".mp4"),
    ]
    original_phase = graph.video_phase

    def finish_second(request, values):
        # Lets the first video finish, then cancels during the second finish.
        if values["upload_phase"] == "finish" and graph.phases.count("finish") == 0:
            graph.phases.append("finish")
            return httpx2.Response(200, json={"success": True}, request=request)
        return original_phase(request, values)

    graph.video_phase = finish_second

    with pytest.raises(asyncio.CancelledError) as cancelled:
        await run_upload(graph, files)

    ledger = cancelled.value.ledger
    assert [parent.outcome for parent in ledger.parents] == ["applied", "unverified", "failed"]
    assert ledger.parents[2].effects[0].error_code == "NOT_DISPATCHED"
    assert graph.phases.count("start") == 2


async def test_invalid_video_id_is_never_finished_and_keeps_earlier_uploads(monkeypatch):
    store(monkeypatch, VIDEO)
    graph = MediaGraph(start_reply="bad_video_id")
    files = [source(IMAGE, "image/png", ".png"), source(VIDEO, "video/mp4", ".mp4")]

    uploads, ledger = await run_upload(graph, files)

    # The session is still cancelled, since its ID was valid.
    assert graph.phases == ["start", "cancel"]
    assert [upload.outcome for upload in uploads] == ["uploaded", "failed"]
    assert [parent.outcome for parent in ledger.parents] == ["applied", "failed"]


async def test_unexpected_error_keeps_the_proof_of_earlier_uploads(monkeypatch):
    store(monkeypatch, VIDEO)
    monkeypatch.setattr(upload_module, "_upload_video", AsyncMock(side_effect=RuntimeError))
    files = [source(IMAGE, "image/png", ".png"), source(VIDEO, "video/mp4", ".mp4")]

    with pytest.raises(RuntimeError) as failed:
        await run_upload(MediaGraph(), files)

    ledger = failed.value.ledger
    assert [parent.outcome for parent in ledger.parents] == ["applied", "failed"]
    assert ledger.parents[1].effects[0].error_code == "UPLOAD_FAILED"


async def test_rejected_finish_cancels_the_session_and_stays_failed(monkeypatch):
    store(monkeypatch, VIDEO)
    graph = MediaGraph(finish_reply="reject")

    uploads, _ledger = await run_upload(graph, [source(VIDEO, "video/mp4", ".mp4")])

    assert graph.phases[-2:] == ["finish", "cancel"]
    assert uploads[0].outcome == "failed"


async def test_files_with_identical_bytes_each_get_the_image_details(monkeypatch):
    store(monkeypatch, IMAGE)
    files = [source(IMAGE, "image/png", ".png"), source(IMAGE, "image/png", ".png", name="copy")]

    uploads, _ledger = await run_upload(MediaGraph(), files)

    assert [upload.media.width for upload in uploads] == [1080, 1080]
    assert [upload.media.label for upload in uploads] == ["spring.png", "copy.png"]


async def test_cancelled_read_back_keeps_proved_uploads_applied(monkeypatch):
    store(monkeypatch, VIDEO)
    graph = MediaGraph(video_status="cancel")

    with pytest.raises(asyncio.CancelledError) as cancelled:
        await run_upload(graph, [source(VIDEO, "video/mp4", ".mp4")])

    ledger = cancelled.value.ledger
    assert ledger.parents[0].outcome == "applied"
    assert ledger.external_refs == ("77",)


def test_upload_needs_exactly_one_writable_account():
    entries = tuple(replace(context_entry(item), write_allowed=True) for item in ("1", "2"))
    deps = SimpleNamespace(active_context=ResolvedActiveContext(entries=entries))

    with pytest.raises(ModelRetry):
        upload_entry(deps)


async def test_approved_upload_fails_when_the_file_changed_after_review(monkeypatch):
    reviewed = source(IMAGE, "image/png", ".png")
    changed = SimpleNamespace(**{**vars(reviewed.revision), "id": uuid4()})
    current = MediaSource(reviewed.file, changed, "image")
    graph = MediaGraph()
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    module = "integrations.meta_ads.tools.upload_media"
    monkeypatch.setattr(f"{module}.resolve_media_source", AsyncMock(return_value=current))
    entry = replace(context_entry("123"), write_allowed=True)
    monkeypatch.setattr(
        f"{module}.approved_display_args",
        lambda _ctx: {
            "_account": {"account_id": "123", "resource_id": str(entry.integration_resource_id)},
            "_files": [reviewed.approval_details()],
        },
    )
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(graph.handle))

    async def client(_ctx, _entry):
        return MetaAdsClient(static_token, client=http)

    monkeypatch.setattr(f"{module}.meta_ads_client", client)
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(entry,)),
            db=None,
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4(), name="Ads agent"),
            run=SimpleNamespace(id=uuid4(), user_id=uuid4()),
        ),
        tool_call_approved=True,
        tool_name="meta_ads_upload_media",
        tool_call_id="call-meta-upload",
    )

    async with http:
        result = await meta_ads_upload_media(
            ctx, files=[FileReference(entity_id=reviewed.file.id, label="spring.png")]
        )

    MetaAdsMediaUploadOutput.model_validate(result)
    assert result["results"][0]["error_code"] == "source_changed"
    assert graph.images == {}
    assert graph.phases == []
