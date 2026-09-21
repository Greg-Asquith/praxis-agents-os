"""SharePoint conflict handling, upload recovery, verification, and cancellation."""

import asyncio
import json
import threading

import httpx2
import pytest

from core.exceptions.integration import (
    IntegrationError,
    IntegrationFailureDisposition,
    IntegrationUnverifiedMutationError,
)
from integrations.sharepoint.operations.create_folder import create_folder
from integrations.sharepoint.operations.replace_item import replace_item
from integrations.sharepoint.operations.upload_item import upload_item
from integrations.sharepoint.operations.upload_session import FRAGMENT_BYTES
from integrations.sharepoint.operations.write_utils import DriveWriteState
from tests.integrations.sharepoint.support import fixture, graph
from utils.quickxorhash import quickxorhash

UPLOAD_URL = fixture("upload_session.json")["uploadUrl"]


@pytest.fixture(autouse=True)
def public_upload_host(monkeypatch):
    async def resolve(host, port):
        return ("8.8.8.8",)

    monkeypatch.setattr("services.integrations.microsoft_graph.client._resolve_host", resolve)


def uploaded(data=b"text", **changes):
    item = fixture("upload_complete.json")
    if data != b"text":
        item["size"] = len(data)
        item["file"]["hashes"]["quickXorHash"] = quickxorhash(data)
    return item | changes


async def save(client, data=b"text", state=None):
    return await upload_item(
        client,
        drive_id="drive",
        parent_id=None,
        name="notes.txt",
        data=data,
        state=state,
    )


def session_response(request):
    assert request.method == "POST"
    assert request.url.path.endswith("/createUploadSession")
    assert json.loads(request.content) == {"item": {"@microsoft.graph.conflictBehavior": "fail"}}
    return httpx2.Response(200, json=fixture("upload_session.json"))


async def test_create_folder_conflict_policy_and_public_version(caplog):
    def handler(request):
        assert request.url.path == "/v1.0/drives/drive/items/parent/children"
        assert json.loads(request.content) == {
            "name": "Reports",
            "folder": {},
            "@microsoft.graph.conflictBehavior": "fail",
        }
        return httpx2.Response(201, json=fixture("folder_created.json"))

    state = DriveWriteState()
    async with graph(handler) as client:
        result = await create_folder(
            client, drive_id="drive", parent_id="parent", name="Reports", state=state
        )
    assert result["version"] == '"folder-1"'
    assert state.committed and state.item_id == "folder"
    assert UPLOAD_URL not in str(result) + repr(state) + caplog.text


@pytest.mark.parametrize("data", [b"text", b"x" * (2 * FRAGMENT_BYTES + 1)])
async def test_single_and_three_fragment_uploads_have_exact_ranges(data, caplog):
    ranges = []
    completed = uploaded(data)

    def handler(request):
        if request.method == "POST":
            return session_response(request)
        ranges.append(request.headers["Content-Range"])
        assert "authorization" not in request.headers
        assert request.headers["Content-Length"] == str(len(request.content))
        offset = len(ranges) * FRAGMENT_BYTES
        if offset >= len(data):
            return httpx2.Response(201, json=completed)
        return httpx2.Response(202, json={"nextExpectedRanges": [f"{offset}-"]})

    state = DriveWriteState()
    async with graph(handler) as client:
        result = await save(client, data, state)
    assert ranges == [
        f"bytes {offset}-{min(offset + FRAGMENT_BYTES, len(data)) - 1}/{len(data)}"
        for offset in range(0, len(data), FRAGMENT_BYTES)
    ]
    assert state.bytes_sent == len(data) and state.hash_matched is True and state.committed
    assert UPLOAD_URL not in str(result) + repr(state) + caplog.text


async def test_middle_fragment_resumes_only_from_session_status():
    data = b"x" * (2 * FRAGMENT_BYTES + 1)
    completed = uploaded(data)
    puts = []
    status_reads = []

    def handler(request):
        if request.method == "POST":
            return session_response(request)
        if request.method == "GET":
            status_reads.append(request)
            return httpx2.Response(200, json=fixture("upload_progress.json"))
        puts.append(request.headers["Content-Range"])
        if len(puts) == 2:
            return httpx2.Response(503)
        if len(puts) == 4:
            return httpx2.Response(201, json=completed)
        offset = FRAGMENT_BYTES if len(puts) == 1 else 2 * FRAGMENT_BYTES
        return httpx2.Response(202, json={"nextExpectedRanges": [f"{offset}-"]})

    async with graph(handler) as client:
        await save(client, data)
    assert len(status_reads) == 1 and len(puts) == 4
    assert puts[1] == puts[2]


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (404, "upload_session_expired"),
        (409, "name_exists"),
        (412, "version_conflict"),
        (423, "locked"),
        (507, "quota_exceeded"),
    ],
)
async def test_final_fragment_errors_keep_stable_codes_without_secrets(status, code, caplog):
    def handler(request):
        if request.method == "POST":
            return session_response(request)
        filenames = {409: "conflict_error.json", 412: "precondition_error.json"}
        payload = fixture(filenames[status]) if status in filenames else {"error": {}}
        payload["error"]["message"] = UPLOAD_URL
        return httpx2.Response(status, json=payload)

    async with graph(handler) as client:
        with pytest.raises(IntegrationError) as caught:
            await save(client)
    assert caught.value.error_code == code
    assert UPLOAD_URL not in str(caught.value) + caplog.text


@pytest.mark.parametrize("hash_value", [None, "mismatch"])
@pytest.mark.parametrize("reconcile", [False, True])
async def test_missing_or_wrong_hash_reports_unverified(hash_value, reconcile):
    item = uploaded()
    item["file"]["hashes"] = {} if hash_value is None else {"quickXorHash": hash_value}

    def handler(request):
        if request.method == "POST":
            return session_response(request)
        if request.method == "PUT" and reconcile:
            raise httpx2.ReadError("The response was lost.", request=request)
        if request.method == "GET" and request.url.path == "/upload":
            return httpx2.Response(404)
        return httpx2.Response(200, json=item)

    state = DriveWriteState()
    async with graph(handler) as client:
        with pytest.raises(IntegrationUnverifiedMutationError):
            await save(client, state=state)
    assert state.committed is (not reconcile)
    if reconcile:
        assert state.hash_matched is None and state.item is None
    else:
        assert state.hash_matched is False
        assert state.item["version"] == '"version-1"'


@pytest.mark.parametrize("matches", [False, True])
async def test_lost_final_response_reconciles_once(matches, monkeypatch):
    calls = []
    hash_threads = []

    def local_hash(data):
        hash_threads.append(threading.get_ident())
        return quickxorhash(data)

    monkeypatch.setattr("integrations.sharepoint.operations.write_utils.quickxorhash", local_hash)

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == "POST":
            return session_response(request)
        if request.method == "PUT":
            raise httpx2.ReadError("connection dropped", request=request)
        if request.url.path == "/upload":
            return httpx2.Response(404)
        assert request.url.path == "/v1.0/drives/drive/root:/notes.txt"
        return httpx2.Response(200, json=uploaded(b"text" if matches else b"xxxx"))

    state = DriveWriteState()
    async with graph(handler) as client:
        with pytest.raises(IntegrationUnverifiedMutationError):
            await save(client, state=state)
    assert [method for method, _ in calls] == ["POST", "PUT", "GET", "GET"]
    assert not state.committed
    assert state.session_status == "missing"
    assert (state.hash_matched is True) is matches
    assert state.bytes_sent == 0
    assert len(hash_threads) == 1
    assert hash_threads[0] != threading.get_ident()


async def test_normal_commit_hashes_once_off_the_event_loop(monkeypatch):
    hash_threads = []

    def local_hash(data):
        hash_threads.append(threading.get_ident())
        return quickxorhash(data)

    monkeypatch.setattr("integrations.sharepoint.operations.write_utils.quickxorhash", local_hash)

    def handler(request):
        if request.method == "POST":
            return session_response(request)
        return httpx2.Response(201, json=uploaded())

    async with graph(handler) as client:
        await save(client)
    assert len(hash_threads) == 1
    assert hash_threads[0] != threading.get_ident()


@pytest.mark.parametrize("at_session", [False, True])
async def test_replace_requires_current_version_and_conditional_session(at_session):
    calls = []

    def handler(request):
        calls.append(request.method)
        if request.method == "GET":
            assert "eTag" in request.url.params["$select"]
            return httpx2.Response(
                200, json=uploaded(eTag='"version-1"' if at_session else '"version-2"')
            )
        assert request.headers["If-Match"] == '"version-1"'
        return httpx2.Response(412)

    async with graph(handler) as client:
        with pytest.raises(IntegrationError) as caught:
            await replace_item(
                client,
                drive_id="drive",
                item_id="file",
                data=b"text",
                expected_version='"version-1"',
            )
    assert caught.value.error_code == "version_conflict"
    assert calls == (["GET", "POST"] if at_session else ["GET"])


@pytest.mark.parametrize("final", [False, True])
async def test_cancellation_deletes_only_before_final_fragment(final):
    methods = []

    def handler(request):
        methods.append(request.method)
        if request.method == "POST":
            return session_response(request)
        if request.method == "DELETE":
            return httpx2.Response(204)
        raise asyncio.CancelledError()

    state = DriveWriteState()
    async with graph(handler) as client:
        with pytest.raises(asyncio.CancelledError) as caught:
            await save(client, b"text" if final else b"x" * (FRAGMENT_BYTES + 1), state)
    assert methods == (["POST", "PUT"] if final else ["POST", "PUT", "DELETE"])
    assert not state.committed
    assert getattr(
        caught.value, "failure_disposition", IntegrationFailureDisposition.AMBIGUOUS
    ) == (
        IntegrationFailureDisposition.AMBIGUOUS
        if final
        else IntegrationFailureDisposition.NOT_DISPATCHED
    )


async def test_nonfinal_session_expiry_cancels_and_is_not_dispatched():
    methods = []

    def handler(request):
        methods.append(request.method)
        if request.method == "POST":
            return session_response(request)
        return httpx2.Response(404)

    async with graph(handler) as client:
        with pytest.raises(IntegrationError) as caught:
            await save(client, b"x" * (FRAGMENT_BYTES + 1))
    assert caught.value.failure_disposition is IntegrationFailureDisposition.NOT_DISPATCHED
    assert methods == ["POST", "PUT", "DELETE"]


async def test_replace_success_retains_item_identity_and_both_versions():
    state = DriveWriteState()

    def handler(request):
        if request.method == "GET":
            return httpx2.Response(200, json=uploaded())
        if request.method == "POST":
            assert request.headers["If-Match"] == '"version-1"'
            assert request.url.path == "/v1.0/drives/drive/items/file/createUploadSession"
            return session_response(request)
        return httpx2.Response(200, json=uploaded(eTag='"version-2"'))

    async with graph(handler) as client:
        result = await replace_item(
            client,
            drive_id="drive",
            item_id="file",
            data=b"text",
            expected_version='"version-1"',
            state=state,
        )
    assert state.item_id == "file" and state.hash_matched is True
    assert state.etag_before == '"version-1"' and state.etag_after == '"version-2"'
    assert result["version"] == state.etag_after


async def test_nonfinal_resume_attempts_are_bounded_and_cancelled(monkeypatch):
    methods = []
    delays = []

    async def sleep(delay):
        delays.append(delay)
        assert methods[-1] == "PUT"

    monkeypatch.setattr("integrations.sharepoint.operations.upload_session.asyncio.sleep", sleep)

    def handler(request):
        methods.append(request.method)
        if request.method == "POST":
            return session_response(request)
        if request.method == "GET":
            return httpx2.Response(200, json={"nextExpectedRanges": ["0-"]})
        if request.method == "DELETE":
            return httpx2.Response(204)
        return httpx2.Response(503)

    async with graph(handler) as client:
        with pytest.raises(IntegrationError) as caught:
            await save(client, b"x" * (FRAGMENT_BYTES + 1))
    assert methods == ["POST", "PUT", "GET", "PUT", "GET", "PUT", "GET", "PUT", "DELETE"]
    assert caught.value.failure_disposition == IntegrationFailureDisposition.NOT_DISPATCHED
    assert delays == [1, 2, 4]


@pytest.mark.parametrize("ranges", [[], ["0-"], ["1-"], [f"{2 * FRAGMENT_BYTES}-"], ["invalid"]])
async def test_malformed_or_nonprogressing_ranges_fail_closed(ranges):
    methods = []

    def handler(request):
        methods.append(request.method)
        if request.method == "POST":
            return session_response(request)
        if request.method == "DELETE":
            return httpx2.Response(204)
        return httpx2.Response(202, json={"nextExpectedRanges": ranges})

    async with graph(handler) as client:
        with pytest.raises(IntegrationError):
            await save(client, b"x" * (FRAGMENT_BYTES + 1))
    assert methods == ["POST", "PUT", "DELETE"]


@pytest.mark.parametrize(
    "change",
    [
        {"size": 3},
        {"eTag": "invalid token"},
        {"parentReference": {"driveId": "other"}},
        {"remoteItem": {}},
    ],
)
@pytest.mark.parametrize("reconcile", [False, True])
async def test_commit_with_wrong_size_or_unsafe_metadata_remains_unverified(change, reconcile):
    item = {**uploaded(), **change}

    def handler(request):
        if request.method == "POST":
            return session_response(request)
        if request.method == "PUT" and reconcile:
            raise httpx2.ReadError("The response was lost.", request=request)
        if request.method == "GET" and request.url.path == "/upload":
            return httpx2.Response(404)
        return httpx2.Response(200, json=item)

    state = DriveWriteState()
    async with graph(handler) as client:
        with pytest.raises(IntegrationUnverifiedMutationError):
            await save(client, state=state)
    assert state.committed is (not reconcile)
    assert state.hash_matched is not True


async def test_session_creation_cancellation_is_not_a_file_mutation():
    def handler(request):
        raise asyncio.CancelledError()

    state = DriveWriteState()
    async with graph(handler) as client:
        with pytest.raises(asyncio.CancelledError) as caught:
            await save(client, state=state)
    assert caught.value.failure_disposition == IntegrationFailureDisposition.NOT_DISPATCHED
    assert not state.session_created and not state.committed
    assert state.bytes_sent == 0


async def test_cancellation_during_resume_backoff_cleans_up_without_replay(monkeypatch):
    methods = []

    async def sleep(delay):
        assert delay == 1
        raise asyncio.CancelledError

    monkeypatch.setattr("integrations.sharepoint.operations.upload_session.asyncio.sleep", sleep)

    def handler(request):
        methods.append(request.method)
        if request.method == "POST":
            return session_response(request)
        return httpx2.Response(204 if request.method == "DELETE" else 503)

    state = DriveWriteState()
    async with graph(handler) as client:
        with pytest.raises(asyncio.CancelledError) as caught:
            await save(client, b"x" * (FRAGMENT_BYTES + 1), state)
    assert methods == ["POST", "PUT", "DELETE"]
    assert caught.value.failure_disposition is IntegrationFailureDisposition.NOT_DISPATCHED
    assert not state.committed and not state.final_fragment_started and state.bytes_sent == 0
