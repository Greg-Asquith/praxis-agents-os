# apps/api/integrations/outlook_mail/operations/create_reply_draft.py

"""Creates a reply or forward draft and preserves its quoted conversation."""

from typing import Literal

from core.exceptions.integration import IntegrationFailureDisposition, IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy
from services.integrations.microsoft_graph import MicrosoftGraphClient

from .utils import MailWriteState, graph_recipients, message_path


async def create_reply_draft(
    client: MicrosoftGraphClient,
    *,
    state: MailWriteState,
    message_id: str,
    action: Literal["createReply", "createReplyAll", "createForward"],
    body_html: str,
    to: list[str] | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
) -> None:
    state.step = "draft"
    payload = await client.post(
        f"{message_path(message_id)}/{action}",
        operation="create_reply_draft",
        policy=IntegrationRequestPolicy.MUTATION,
        headers={"Prefer": 'outlook.body-content-type="html"'},
    )
    state.created(payload)
    state.step = "patch"
    body = payload.get("body")
    if (
        not isinstance(body, dict)
        or str(body.get("contentType", "")).lower() != "html"
        or not isinstance(body.get("content"), str)
        or not body["content"]
        or len(body["content"].encode("utf-8")) > 1_000_000
    ):
        raise IntegrationValidationError(
            "Outlook did not return a bounded HTML conversation. Check the message in Outlook.",
            provider_key="outlook_mail",
            operation="create_reply_draft",
            failure_disposition=IntegrationFailureDisposition.NOT_DISPATCHED,
            error_code="quoted_conversation_unavailable",
        )
    changes = {"body": {"contentType": "html", "content": body_html + body["content"]}}
    for key, values in (("toRecipients", to), ("ccRecipients", cc), ("bccRecipients", bcc)):
        if values is not None:
            changes[key] = graph_recipients(values)
    await client.patch(
        message_path(state.message_id),
        operation="update_reply_draft",
        policy=IntegrationRequestPolicy.MUTATION,
        json=changes,
    )
    state.applied_steps.append(state.step)
