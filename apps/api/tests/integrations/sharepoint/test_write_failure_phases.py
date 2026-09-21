"""Audited writes distinguish preparation failures from uncertain commits."""

import asyncio
from unittest.mock import patch

import httpx2
import pytest

from core.exceptions.integration import IntegrationConnectionError, IntegrationFailureDisposition
from tests.integrations.sharepoint.support import graph
from tests.integrations.sharepoint.test_write_tools import (
    CONTENT,
    NAME,
    invoke,
    provider as provider,
)


def terminal_evidence(provider, *, status):
    pending, terminal = [call.kwargs for call in provider.audit.await_args_list]
    assert str(pending["status"]) == "pending"
    assert str(terminal["status"]) == status
    assert terminal["related_event_id"] == provider.audit.return_value
    detail = terminal["operation_detail"]
    assert detail.effect_counts.failed == int(status == "failure")
    assert detail.effect_counts.unverified == int(status == "unverified")
    assert all(marker not in str(terminal) for marker in (CONTENT, NAME, "PRIVATE_UPLOAD_SECRET"))
    return detail.outcome_groups[0].outcomes[0].effects[0].fields


@pytest.mark.parametrize("name", ["write_file", "update_file"])
@pytest.mark.parametrize(
    "payload", [{}, {"uploadUrl": None}, {"uploadUrl": ""}, {"uploadUrl": 1}, []]
)
async def test_invalid_session_response_is_an_audited_undispatched_failure(provider, name, payload):
    provider.client.post.side_effect = None
    provider.client.post.return_value = payload
    from integrations.sharepoint.tools.write_utils import failed_write_outcome

    with patch(
        "integrations.sharepoint.tools.write_utils.failed_write_outcome",
        wraps=failed_write_outcome,
    ) as failed:
        result = await invoke(name)
    assert (
        failed.call_args.args[-1].failure_disposition
        is IntegrationFailureDisposition.NOT_DISPATCHED
    )
    assert result["results"][0]["data"]["outcome"] == "failed"
    fields = terminal_evidence(provider, status="failure")
    assert fields["committed"] is False and fields["session_created"] is False
    assert fields["bytes_sent"] == 0 and fields["hash_matched"] is None
    provider.client.upload_fragment.assert_not_awaited()


@pytest.mark.parametrize(
    "change",
    [
        None,
        [],
        {"file": None},
        {"file": []},
        {"folder": {}},
        {"folder": None},
        {"package": {}},
        {"parentReference": None},
        {"id": "different"},
        {"eTag": None},
        {"eTag": "invalid token"},
        {"eTag": []},
    ],
)
async def test_invalid_second_replacement_read_is_an_audited_undispatched_failure(provider, change):
    second_item = {**provider.item, **change} if isinstance(change, dict) else change
    provider.client.get.side_effect = [provider.item, second_item]
    from integrations.sharepoint.tools.write_utils import failed_write_outcome

    with patch(
        "integrations.sharepoint.tools.write_utils.failed_write_outcome",
        wraps=failed_write_outcome,
    ) as failed:
        result = await invoke("update_file")
    assert (
        failed.call_args.args[-1].failure_disposition
        is IntegrationFailureDisposition.NOT_DISPATCHED
    )
    assert result["results"][0]["data"]["outcome"] == "failed"
    fields = terminal_evidence(provider, status="failure")
    assert fields["committed"] is False and fields["session_created"] is False
    assert fields["bytes_sent"] == 0 and fields["hash_matched"] is None
    assert fields["etag_before"] == '"version-1"' and fields["etag_after"] is None
    provider.client.post.assert_not_awaited()
    provider.client.upload_fragment.assert_not_awaited()


@pytest.mark.parametrize("folder", [{}, None])
async def test_mixed_file_and_folder_metadata_fails_before_pending_intent(provider, folder):
    provider.client.get.side_effect = None
    provider.client.get.return_value = {**provider.item, "folder": folder}
    result = await invoke("update_file")
    assert result["results"][0]["error_code"] == "unsupported_type"
    assert provider.audit.await_count == 1
    assert str(provider.audit.await_args.kwargs["status"]) == "failure"
    provider.client.post.assert_not_awaited()
    provider.client.upload_fragment.assert_not_awaited()


@pytest.mark.parametrize("name", ["write_file", "update_file"])
@pytest.mark.parametrize(
    "url", ["http://example.com/upload", "invalid URL", "https://127.0.0.1/upload"]
)
async def test_refused_session_url_has_undispatched_audit_and_no_fragment_request(
    provider, name, url
):
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "GET":
            return httpx2.Response(200, json=provider.item)
        assert request.method == "POST"
        return httpx2.Response(200, json={"uploadUrl": url})

    from integrations.sharepoint.tools.write_utils import failed_write_outcome

    async with graph(handler) as client:
        provider.factory.return_value = client
        with patch(
            "integrations.sharepoint.tools.write_utils.failed_write_outcome",
            wraps=failed_write_outcome,
        ) as failed:
            result = await invoke(name)
    assert (
        failed.call_args.args[-1].failure_disposition
        is IntegrationFailureDisposition.NOT_DISPATCHED
    )
    assert result["results"][0]["data"]["outcome"] == "failed"
    fields = terminal_evidence(provider, status="failure")
    assert fields["bytes_sent"] == 0 and fields["committed"] is False
    assert [request.method for request in requests] == (
        ["GET", "GET", "POST"] if name == "update_file" else ["POST"]
    )


@pytest.mark.parametrize("phase", ["session", "replacement_read", "commit", "reconcile"])
async def test_cancellation_audit_preserves_the_file_mutation_boundary(provider, phase):
    name = "update_file" if phase == "replacement_read" else "write_file"
    if phase == "session":
        provider.client.post.side_effect = asyncio.CancelledError
    elif phase == "replacement_read":
        provider.client.get.side_effect = [provider.item, asyncio.CancelledError()]
    elif phase == "reconcile":
        provider.client.upload_fragment.side_effect = IntegrationConnectionError(
            "The upload response was lost.",
            failure_disposition=IntegrationFailureDisposition.AMBIGUOUS,
        )
        cancellation = asyncio.CancelledError()
        cancellation.failure_disposition = IntegrationFailureDisposition.NOT_DISPATCHED
        provider.client.upload_status.side_effect = cancellation
    else:
        provider.client.upload_fragment.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError) as caught:
        await invoke(name)
    disposition = (
        IntegrationFailureDisposition.AMBIGUOUS
        if phase in {"commit", "reconcile"}
        else IntegrationFailureDisposition.NOT_DISPATCHED
    )
    assert caught.value.failure_disposition is disposition
    uncertain = phase in {"commit", "reconcile"}
    fields = terminal_evidence(provider, status="unverified" if uncertain else "failure")
    assert fields["bytes_sent"] == 0 and fields["committed"] is False
    assert fields["session_created"] is uncertain
    assert provider.client.upload_fragment.await_count == int(uncertain)
    provider.client.cancel_upload.assert_not_awaited()


async def test_backoff_cancellation_records_undispatched_terminal_evidence(provider, monkeypatch):
    monkeypatch.setattr("integrations.sharepoint.operations.upload_session.FRAGMENT_BYTES", 4)

    async def sleep(delay):
        assert delay == 1
        raise asyncio.CancelledError

    monkeypatch.setattr("integrations.sharepoint.operations.upload_session.asyncio.sleep", sleep)
    provider.client.upload_fragment.side_effect = IntegrationConnectionError(
        "Upload interrupted.",
        error_code="upload_interrupted",
        failure_disposition=IntegrationFailureDisposition.AMBIGUOUS,
    )
    with pytest.raises(asyncio.CancelledError) as caught:
        await invoke("write_file")
    assert caught.value.failure_disposition is IntegrationFailureDisposition.NOT_DISPATCHED
    fields = terminal_evidence(provider, status="failure")
    assert fields["session_created"] is True
    assert fields["bytes_sent"] == 0 and fields["committed"] is False
    provider.client.upload_fragment.assert_awaited_once()
    provider.client.cancel_upload.assert_awaited_once()
    provider.client.upload_status.assert_not_awaited()
