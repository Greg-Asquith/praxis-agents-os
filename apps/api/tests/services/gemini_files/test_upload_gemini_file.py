"""Gemini Files API upload tests: what we send to Google and what we accept back."""

import importlib
from datetime import UTC, datetime
from uuid import uuid4

import httpx2 as httpx
import pytest
from pydantic import SecretStr

from core.settings import settings
from services.gemini_files import GeminiFileError, upload_gemini_file
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.factory import get_storage_provider
from tests.support.storage import reset_storage_provider_cache

# The package re-exports functions under the module names.
upload_module = importlib.import_module("services.gemini_files.upload_gemini_file")
delete_module = importlib.import_module("services.gemini_files.delete_gemini_file")

BASE = "https://generativelanguage.googleapis.com"
UPLOAD_URL = f"{BASE}/upload/v1beta/files?upload_id=session-1"


@pytest.fixture
async def stored_video(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", SecretStr("gemini-key"))
    monkeypatch.setattr(upload_module, "GEMINI_UPLOAD_CHUNK_BYTES", 4)
    monkeypatch.setattr(upload_module, "GEMINI_PROCESSING_POLL_SECONDS", 0)
    reset_storage_provider_cache()
    ref = make_storage_object_ref(StorageBucket.PRIVATE, f"workspaces/{uuid4()}/clip.mp4")
    await get_storage_provider().put_object(ref, b"0123456789", content_type="video/mp4")
    try:
        yield ref
    finally:
        reset_storage_provider_cache()


def _mock_google(monkeypatch: pytest.MonkeyPatch, poll_state: str) -> list[httpx.Request]:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.headers.get("x-goog-upload-command") == "start":
            return httpx.Response(200, headers={"x-goog-upload-url": UPLOAD_URL})
        if request.headers.get("x-goog-upload-command") == "upload, finalize":
            return httpx.Response(200, json={"file": {"name": "files/abc", "state": "PROCESSING"}})
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "name": "files/abc",
                    "state": poll_state,
                    "uri": f"{BASE}/v1beta/files/abc",
                    "expirationTime": "2026-10-14T10:00:00.123456789Z",
                },
            )
        return httpx.Response(200, json={})

    def client() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(respond))

    monkeypatch.setattr(upload_module, "gemini_files_client", client)
    monkeypatch.setattr(delete_module, "gemini_files_client", client)
    return requests


async def test_upload_streams_chunks_and_waits_until_active(stored_video, monkeypatch):
    requests = _mock_google(monkeypatch, poll_state="ACTIVE")

    uploaded = await upload_gemini_file(
        stored_video, size_bytes=10, media_type="video/mp4", display_name="revision"
    )

    start, *chunks, poll = requests
    assert start.headers["x-goog-api-key"] == "gemini-key"
    assert start.headers["x-goog-upload-header-content-length"] == "10"
    assert [(c.headers["x-goog-upload-offset"], c.content) for c in chunks] == [
        ("0", b"0123"),
        ("4", b"4567"),
        ("8", b"89"),
    ]
    assert [c.headers["x-goog-upload-command"] for c in chunks][-1] == "upload, finalize"
    # The session URL authorises the bytes; the key goes only to Google's API endpoints.
    assert all("x-goog-api-key" not in c.headers for c in chunks)
    assert str(poll.url) == f"{BASE}/v1beta/files/abc"
    assert uploaded.uri == f"{BASE}/v1beta/files/abc"
    assert uploaded.expires_at == datetime(2026, 10, 14, 10, 0, 0, 123456, tzinfo=UTC)


async def test_upload_that_google_cannot_process_is_deleted(stored_video, monkeypatch):
    requests = _mock_google(monkeypatch, poll_state="FAILED")

    with pytest.raises(GeminiFileError, match="couldn't process"):
        await upload_gemini_file(
            stored_video, size_bytes=10, media_type="video/mp4", display_name="revision"
        )

    assert (requests[-1].method, str(requests[-1].url)) == ("DELETE", f"{BASE}/v1beta/files/abc")
