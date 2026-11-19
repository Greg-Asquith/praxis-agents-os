# apps/api/tests/integrations/gmail/test_gmail_merge_sender.py

"""Gmail merge sends: the draft sent, reconcile from draft and thread IDs, and send errors."""

import base64
import json
from email import message_from_bytes

import httpx2
import pytest

from core.exceptions.integration import (
    IntegrationFailureDisposition,
    IntegrationRateLimitError,
    IntegrationSendingLimitError,
)
from integrations.gmail.client import GmailClient
from integrations.gmail.operations.send_merge_message import GmailMergeSender
from services.integrations.plugin import MailMergeDraft, MailMergeMessage

pytestmark = pytest.mark.asyncio


async def _token(_force: bool) -> str:
    return "access-token"


def _sender(handler) -> GmailMergeSender:
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    return GmailMergeSender(GmailClient(_token, client=client, send_errors=True))


async def test_a_merge_draft_has_one_recipient_and_its_send_reads_the_sent_message_id() -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        path = request.url.path
        if path.endswith("/users/me/drafts"):
            return httpx2.Response(
                200, json={"id": "r1", "message": {"id": "m0", "threadId": "t1"}}
            )
        if path.endswith("/users/me/drafts/send"):
            return httpx2.Response(200, json={"id": "m1", "threadId": "t1", "labelIds": ["SENT"]})
        assert path.endswith("/users/me/messages/m1")
        return httpx2.Response(
            200,
            json={
                "payload": {"headers": [{"name": "Message-ID", "value": "<sent@mail.gmail.com>"}]}
            },
        )

    sender = _sender(handler)
    draft = await sender.create_draft(
        MailMergeMessage(to="dana@example.com", subject="Hello Dana", body_html="<p>Hi Dana</p>")
    )
    delivery = await sender.send_draft(draft)

    raw = json.loads(requests[0].content)["message"]["raw"]
    mime = message_from_bytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    assert (mime["To"], mime["Cc"], mime["Bcc"]) == ("dana@example.com", None, None)
    assert (draft.draft_id, draft.thread_id) == ("r1", "t1")
    assert json.loads(requests[1].content) == {"id": "r1"}
    assert (delivery.state, delivery.provider_message_id, delivery.message_id_header) == (
        "sent",
        "m1",
        "<sent@mail.gmail.com>",
    )


async def test_reconcile_reads_the_draft_then_the_thread_it_was_sent_in() -> None:
    drafts = {"waiting": 200, "sent": 404, "deleted": 404}
    threads = {
        "t-sent": {"messages": [{"id": "m9", "labelIds": ["SENT"]}]},
        "t-deleted": {"messages": [{"id": "m8", "labelIds": ["INBOX"]}]},
    }

    def handler(request: httpx2.Request) -> httpx2.Response:
        kind, _, ref = request.url.path.rpartition("/users/me/")[2].partition("/")
        if kind == "drafts":
            return httpx2.Response(drafts[ref], json={"id": ref})
        if kind == "threads":
            return httpx2.Response(200, json=threads[ref])
        return httpx2.Response(200, json={"payload": {"headers": []}})

    sender = _sender(handler)

    waiting = await sender.check_draft(MailMergeDraft(draft_id="waiting", thread_id="t-waiting"))
    sent = await sender.check_draft(MailMergeDraft(draft_id="sent", thread_id="t-sent"))
    deleted = await sender.check_draft(MailMergeDraft(draft_id="deleted", thread_id="t-deleted"))

    assert waiting.state == "unsent"
    assert (sent.state, sent.provider_message_id) == ("sent", "m9")
    assert deleted.state == "unknown"


async def test_send_errors_tell_throttling_from_the_daily_limit() -> None:
    responses = [
        httpx2.Response(
            403,
            json={"error": {"errors": [{"reason": "userRateLimitExceeded"}], "message": "slow"}},
        ),
        httpx2.Response(
            429,
            headers={"Retry-After": "30"},
            json={"error": {"message": "Too many concurrent requests for user"}},
        ),
        httpx2.Response(
            429, json={"error": {"message": "User-rate limit exceeded (Mail sending)"}}
        ),
    ]
    sender = _sender(lambda request: responses.pop(0))
    draft = MailMergeDraft(draft_id="r1", thread_id="t1")

    with pytest.raises(IntegrationRateLimitError) as per_minute:
        await sender.send_draft(draft)
    with pytest.raises(IntegrationRateLimitError) as concurrent:
        await sender.send_draft(draft)
    with pytest.raises(IntegrationSendingLimitError) as daily:
        await sender.send_draft(draft)

    # Gmail refused each one, so the sender may wait and send the same draft again.
    for error in (per_minute.value, concurrent.value, daily.value):
        assert error.failure_disposition == IntegrationFailureDisposition.REJECTED
    assert concurrent.value.retry_after_seconds == 30


async def test_the_projects_api_quota_is_told_apart_from_the_mailboxs_own_limit() -> None:
    quota = httpx2.Response(
        403, json={"error": {"errors": [{"reason": "dailyLimitExceeded"}], "message": "quota"}}
    )
    sender = _sender(lambda request: quota)

    with pytest.raises(IntegrationRateLimitError) as error:
        await sender.send_draft(MailMergeDraft(draft_id="r1", thread_id="t1"))

    assert not isinstance(error.value, IntegrationSendingLimitError)
    assert error.value.error_code == "platform_quota"


async def test_a_client_that_did_not_opt_in_keeps_a_throttled_send_ambiguous() -> None:
    client = httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda request: httpx2.Response(429, json={}))
    )
    sender = GmailMergeSender(GmailClient(_token, client=client))

    with pytest.raises(IntegrationRateLimitError) as error:
        await sender.send_draft(MailMergeDraft(draft_id="r1", thread_id="t1"))

    assert error.value.failure_disposition == IntegrationFailureDisposition.AMBIGUOUS
