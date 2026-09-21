"""Write outcomes require the approved item identity and acknowledged progress."""

import asyncio

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
from tests.integrations.sharepoint.support import file_metadata, graph
from utils.quickxorhash import quickxorhash

UPLOAD_URL = "https://93.184.216.34/upload?token=PRIVATE_UPLOAD_SECRET"


def saved_item(**changes):
    return (
        file_metadata(
            size=4,
            file={"mimeType": "text/plain", "hashes": {"quickXorHash": quickxorhash(b"text")}},
            parentReference={"driveId": "drive", "id": "parent"},
        )
        | changes
    )


async def save(client, state, *, parent_id="parent", data=b"text"):
    return await upload_item(
        client,
        drive_id="drive",
        parent_id=parent_id,
        name="notes.txt",
        data=data,
        state=state,
    )


@pytest.mark.parametrize("reconcile", [False, True])
@pytest.mark.parametrize(
    "changes",
    [
        {"name": "different.txt"},
        {"parentReference": {"driveId": "drive", "id": "different"}},
        {"parentReference": {"driveId": "drive"}},
        {"folder": {}},
        {"file": None},
    ],
)
async def test_new_file_must_match_approved_name_parent_and_kind(changes, reconcile):
    def handler(request):
        if request.method == "POST":
            return httpx2.Response(200, json={"uploadUrl": UPLOAD_URL})
        if request.method == "PUT" and reconcile:
            raise httpx2.ReadError("The response was lost.", request=request)
        if request.url.path == "/upload" and request.method == "GET":
            return httpx2.Response(404)
        return httpx2.Response(200, json=saved_item(**changes))

    state = DriveWriteState()
    async with graph(handler) as client:
        with pytest.raises(IntegrationUnverifiedMutationError):
            await save(client, state)
    assert state.item is None
    assert state.hash_matched is not True


@pytest.mark.parametrize("reconcile", [False, True])
async def test_replace_does_not_return_a_different_item_with_matching_content(reconcile):
    def handler(request):
        if request.method == "POST":
            return httpx2.Response(200, json={"uploadUrl": UPLOAD_URL})
        if request.method == "PUT" and reconcile:
            raise httpx2.ReadError("The response was lost.", request=request)
        if request.url.path == "/upload" and request.method == "GET":
            return httpx2.Response(404)
        if state.final_fragment_started:
            return httpx2.Response(200, json=saved_item(id="different"))
        return httpx2.Response(200, json=saved_item())

    state = DriveWriteState()
    async with graph(handler) as client:
        with pytest.raises(IntegrationUnverifiedMutationError):
            await replace_item(
                client,
                drive_id="drive",
                item_id="file",
                data=b"text",
                expected_version='"version-1"',
                state=state,
            )
    assert state.item_id == "file"
    assert state.item is None


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "different"},
        {"parentReference": {"driveId": "drive", "id": "different"}},
        {"parentReference": {"driveId": "drive"}},
        {"file": {}},
        {"folder": None},
    ],
)
async def test_folder_must_match_approved_name_parent_and_kind(changes):
    item = saved_item(name="Reports", folder={})
    item.pop("file")
    item.update(changes)

    state = DriveWriteState()
    async with graph(lambda _: httpx2.Response(201, json=item)) as client:
        with pytest.raises(IntegrationError):
            await create_folder(
                client,
                drive_id="drive",
                parent_id="parent",
                name="Reports",
                state=state,
            )
    assert state.committed and state.item is None


@pytest.mark.parametrize("parent_id", [None, "parent"])
async def test_matching_new_item_is_verified(parent_id):
    def handler(request):
        if request.method == "POST":
            return httpx2.Response(200, json={"uploadUrl": UPLOAD_URL})
        return httpx2.Response(201, json=saved_item())

    state = DriveWriteState()
    async with graph(handler) as client:
        result = await save(client, state, parent_id=parent_id)
    assert result["kind"] == "file"
    assert state.hash_matched is True and state.bytes_sent == 4


async def test_refused_upload_url_records_no_sent_bytes():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx2.Response(200, json={"uploadUrl": "https://127.0.0.1/upload"})

    state = DriveWriteState()
    async with graph(handler) as client:
        with pytest.raises(IntegrationError):
            await save(client, state)
    assert [request.method for request in requests] == ["POST"]
    assert state.bytes_sent == 0


@pytest.mark.parametrize("final", [False, True])
async def test_interrupted_fragment_does_not_claim_unacknowledged_bytes(final):
    def handler(request):
        if request.method == "POST":
            return httpx2.Response(200, json={"uploadUrl": UPLOAD_URL})
        if request.method == "DELETE":
            return httpx2.Response(204)
        raise asyncio.CancelledError

    state = DriveWriteState()
    async with graph(handler) as client:
        with pytest.raises(asyncio.CancelledError):
            await save(client, state, data=b"text" if final else b"x" * (FRAGMENT_BYTES + 1))
    assert state.bytes_sent == 0


async def test_resume_status_acknowledges_a_fragment_after_lost_response():
    data = b"x" * (FRAGMENT_BYTES + 1)
    progress = []

    def handler(request):
        if request.method == "POST":
            return httpx2.Response(200, json={"uploadUrl": UPLOAD_URL})
        if request.method == "GET":
            progress.append(state.bytes_sent)
            return httpx2.Response(200, json={"nextExpectedRanges": [f"{FRAGMENT_BYTES}-"]})
        if request.headers["Content-Range"].startswith("bytes 0-"):
            raise httpx2.ReadError("The response was lost.", request=request)
        progress.append(state.bytes_sent)
        item = saved_item(size=len(data))
        item["file"]["hashes"]["quickXorHash"] = quickxorhash(data)
        return httpx2.Response(201, json=item)

    state = DriveWriteState()
    async with graph(handler) as client:
        await save(client, state, data=data)
    assert progress == [0, FRAGMENT_BYTES]
    assert state.bytes_sent == len(data)


async def test_cancellation_during_replacement_version_read_is_not_dispatched():
    methods = []

    def handler(request):
        methods.append(request.method)
        raise asyncio.CancelledError

    state = DriveWriteState()
    async with graph(handler) as client:
        with pytest.raises(asyncio.CancelledError) as caught:
            await replace_item(
                client,
                drive_id="drive",
                item_id="file",
                data=b"text",
                expected_version='"version-1"',
                state=state,
            )
    assert methods == ["GET"]
    assert caught.value.failure_disposition is IntegrationFailureDisposition.NOT_DISPATCHED
    assert not state.session_created and not state.committed
    assert state.bytes_sent == 0


@pytest.mark.parametrize("replace", [False, True])
@pytest.mark.parametrize("version", ['"version-1"', '"version-2"'])
@pytest.mark.parametrize("status", ["incomplete", "missing", "unavailable", "unknown"])
async def test_matching_destination_never_proves_a_lost_commit(replace, version, status):
    methods = []

    def handler(request):
        methods.append(request.method)
        if request.method == "POST":
            return httpx2.Response(200, json={"uploadUrl": UPLOAD_URL})
        if request.method == "PUT":
            raise httpx2.ReadError("The response was lost.", request=request)
        if request.url.path == "/upload":
            if status == "missing":
                return httpx2.Response(404)
            if status == "unavailable":
                return httpx2.Response(503)
            return httpx2.Response(
                200, json={"nextExpectedRanges": ["0-"]} if status == "incomplete" else {}
            )
        return httpx2.Response(
            200, json=saved_item(eTag=version if state.final_fragment_started else '"version-1"')
        )

    state = DriveWriteState()
    async with graph(handler) as client:
        with pytest.raises(IntegrationUnverifiedMutationError) as caught:
            if replace:
                await replace_item(
                    client,
                    drive_id="drive",
                    item_id="file",
                    data=b"text",
                    expected_version='"version-1"',
                    state=state,
                )
            else:
                await save(client, state)
    assert methods == (["GET"] if replace else []) + ["POST", "PUT", "GET", "GET"]
    assert caught.value.failure_disposition is IntegrationFailureDisposition.AMBIGUOUS
    assert not state.committed and state.bytes_sent == 0
    assert state.session_status == status
    assert state.hash_matched is True
    assert state.etag_after == version
    assert state.item["reference"].item_id == "file"


@pytest.mark.parametrize("phase", ["status", "metadata"])
async def test_reconciliation_cancellation_preserves_ambiguity_without_replay(phase):
    methods = []

    def handler(request):
        methods.append(request.method)
        if request.method == "POST":
            return httpx2.Response(200, json={"uploadUrl": UPLOAD_URL})
        if request.method == "PUT":
            raise httpx2.ReadError("The response was lost.", request=request)
        if request.url.path == "/upload" and phase == "metadata":
            return httpx2.Response(404)
        raise asyncio.CancelledError

    state = DriveWriteState()
    async with graph(handler) as client:
        with pytest.raises(asyncio.CancelledError) as caught:
            await save(client, state)
    assert methods == ["POST", "PUT", "GET"] + (["GET"] if phase == "metadata" else [])
    assert caught.value.failure_disposition is IntegrationFailureDisposition.AMBIGUOUS
    assert not state.committed and state.bytes_sent == 0
    assert state.session_status == ("missing" if phase == "metadata" else None)


@pytest.mark.parametrize("ranges", [None, [], "0-", {}, ["invalid"], [1]])
async def test_malformed_reconciliation_status_is_unknown(ranges):
    def handler(request):
        if request.method == "POST":
            return httpx2.Response(200, json={"uploadUrl": UPLOAD_URL})
        if request.method == "PUT":
            raise httpx2.ReadError("The response was lost.", request=request)
        if request.url.path == "/upload":
            return httpx2.Response(200, json={"nextExpectedRanges": ranges})
        return httpx2.Response(200, json=saved_item())

    state = DriveWriteState()
    async with graph(handler) as client:
        with pytest.raises(IntegrationUnverifiedMutationError):
            await save(client, state)
    assert state.session_status == "unknown"
    assert not state.committed
