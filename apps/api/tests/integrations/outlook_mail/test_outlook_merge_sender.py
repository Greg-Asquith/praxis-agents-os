# apps/api/tests/integrations/outlook_mail/test_outlook_merge_sender.py

"""Outlook merge sends: IDs kept before the send, reconcile by draft ID, and throttling."""

import json

import httpx2
import pytest

from core.exceptions.integration import IntegrationFailureDisposition, IntegrationRateLimitError
from integrations.outlook_mail.operations.send_merge_message import OutlookMergeSender
from services.integrations.microsoft_graph import MicrosoftGraphClient, fixed_access_token
from services.integrations.plugin import MailMergeDraft, MailMergeMessage

pytestmark = pytest.mark.asyncio


def _sender(transport: httpx2.AsyncClient) -> OutlookMergeSender:
    return OutlookMergeSender(
        MicrosoftGraphClient(
            fixed_access_token("token"),
            provider_key="outlook_mail",
            client=transport,
            send_errors=True,
        )
    )


async def test_a_merge_draft_keeps_its_immutable_and_internet_message_ids_for_reconcile() -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx2.Response(
                201,
                json={"id": "draft/==", "internetMessageId": "<merge@outlook.com>"},
            )
        return httpx2.Response(200, json={"id": "draft/==", "isDraft": False})

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as transport:
        sender = _sender(transport)
        draft = await sender.create_draft(
            MailMergeMessage(to="dana@example.com", subject="Hello", body_html="<p>Hi</p>")
        )
        delivery = await sender.check_draft(draft)

    body = json.loads(requests[0].content)
    assert [item["emailAddress"]["address"] for item in body["toRecipients"]] == [
        "dana@example.com"
    ]
    assert body["ccRecipients"] == body["bccRecipients"] == []
    assert requests[0].headers["Prefer"] == 'IdType="ImmutableId"'
    assert (draft.draft_id, draft.message_id_header) == ("draft/==", "<merge@outlook.com>")
    assert (delivery.state, delivery.provider_message_id) == ("sent", "draft/==")


async def test_a_throttled_send_is_rejected_with_retry_after() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            429,
            headers={"Retry-After": "12"},
            json={"error": {"code": "MailboxConcurrency", "message": "Too many requests"}},
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as transport:
        sender = _sender(transport)
        with pytest.raises(IntegrationRateLimitError) as throttled:
            await sender.send_draft(MailMergeDraft(draft_id="draft/=="))

    assert throttled.value.failure_disposition == IntegrationFailureDisposition.REJECTED
    assert throttled.value.retry_after_seconds == 12
